"""Scrapers: configuration, runs, the data they collect, its history, and exports."""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import can_edit, get_current_user, get_owned
from app.models import AlertEvent, AlertRule, Item, ItemChange, Run, Scraper, User, utcnow
from app.scraper.config import ScraperConfig
from app.scraper.extract import Row, extract_detail_page, extract_list_page, fill_rates
from app.services import runs as run_service
from app.services.alerts import ALERT_KINDS
from app.services.pages import fetch_page
from app.services.serializers import change_out, item_out, rule_out, run_brief, scraper_out
from app.worker import worker

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

MAX_EXPORT_ROWS = 50_000


@router.get("")
def list_scrapers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scrapers = db.scalars(select(Scraper).where(Scraper.workspace_id == user.workspace_id).order_by(Scraper.name)).all()
    return [scraper_out(db, s) for s in scrapers]


@router.post("", status_code=201)
def create_scraper(body: schemas.ScraperIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    scraper = Scraper(
        workspace_id=user.workspace_id, name=body.name.strip(), description=body.description.strip(),
        start_urls=body.start_urls, config=body.config.model_dump(), schedule_minutes=body.schedule_minutes,
        enabled=body.enabled, created_by_id=user.id,
    )
    scraper.next_run_at = run_service.next_run_time(scraper)
    db.add(scraper)
    db.commit()
    return scraper_out(db, scraper, detail=True)


@router.get("/{scraper_id}")
def get_scraper(scraper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return scraper_out(db, get_owned(db, Scraper, scraper_id, user.workspace_id), detail=True)


@router.patch("/{scraper_id}")
def update_scraper(scraper_id: str, body: schemas.ScraperUpdate, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    data = body.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        scraper.config = body.config.model_dump()
    for key in ("name", "description", "start_urls", "enabled"):
        if data.get(key) is not None:
            setattr(scraper, key, data[key].strip() if isinstance(data[key], str) else data[key])
    if "schedule_minutes" in data:
        scraper.schedule_minutes = data["schedule_minutes"]
    if {"schedule_minutes", "enabled"} & data.keys():
        scraper.next_run_at = run_service.next_run_time(scraper)
    scraper.updated_at = utcnow()
    db.commit()
    return scraper_out(db, scraper, detail=True)


@router.delete("/{scraper_id}", status_code=204)
def delete_scraper(scraper_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    if run_service.active_run(db, scraper.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the run in progress first.")
    db.delete(scraper)
    db.commit()


@router.post("/{scraper_id}/runs", status_code=201)
def start_run(scraper_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    run = run_service.enqueue(db, scraper, trigger="manual", user_id=user.id)
    db.commit()
    worker.wake()
    return run_brief(run)


# ---- data ----

def _sort_expr(sort: str | None, config: ScraperConfig):
    if not sort:
        return [Item.last_changed_at.desc()]
    desc = sort.startswith("-")
    name = sort.lstrip("-")
    if name in ("first_seen_at", "last_seen_at", "last_changed_at"):
        col = getattr(Item, name)
    else:
        field = next((f for f in config.fields if f.name == name), None)
        if field is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown sort field {name!r}.")
        col = Item.data[name]
        col = col.as_float() if field.type in ("number", "integer", "price") else col.as_string()
    return [col.desc() if desc else col.asc(), Item.id]


def _items_query(scraper: Scraper, q: str | None, include_removed: bool, only_removed: bool = False):
    stmt = select(Item).where(Item.scraper_id == scraper.id)
    if only_removed:
        stmt = stmt.where(Item.removed_at.is_not(None))
    elif not include_removed:
        stmt = stmt.where(Item.removed_at.is_(None))
    if q:
        stmt = stmt.where(or_(cast(Item.data, String).ilike(f"%{q}%"), Item.key.ilike(f"%{q}%")))
    return stmt


@router.get("/{scraper_id}/items")
def list_items(
    scraper_id: str,
    q: str | None = None,
    include_removed: bool = False,
    only_removed: bool = False,
    sort: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    config = ScraperConfig.model_validate(scraper.config)
    stmt = _items_query(scraper, q, include_removed, only_removed)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(*_sort_expr(sort, config)).limit(limit).offset(offset)).all()
    return {"total": total, "items": [item_out(i) for i in rows],
            "columns": [{"name": f.name, "type": f.type, "multiple": f.multiple} for f in config.fields]}


@router.get("/{scraper_id}/items/{item_id}")
def get_item(scraper_id: str, item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    item = db.get(Item, item_id)
    if item is None or item.scraper_id != scraper.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    history = db.scalars(select(ItemChange).where(ItemChange.item_id == item.id).order_by(ItemChange.at.desc())).all()
    alerts = db.scalars(select(AlertEvent).where(AlertEvent.item_id == item.id).order_by(AlertEvent.at.desc()).limit(20)).all()
    config = ScraperConfig.model_validate(scraper.config)
    # Numeric series for charts (e.g. price history): one point per value change, oldest first.
    numeric = [f.name for f in config.fields if f.type in ("number", "integer", "price") and not f.multiple]
    series: dict[str, list] = {name: [] for name in numeric}
    current: dict = {}
    for c in reversed(history):
        changes = c.changes or {}
        if c.kind.value == "new":
            current.update({k: v for k, v in changes.items() if k in numeric})
        elif c.kind.value in ("changed", "returned"):
            for k, v in changes.items():
                if k in numeric and isinstance(v, list):
                    if not series[k] and isinstance(v[0], (int, float)):  # baseline value from before the first change
                        series[k].append({"at": item.first_seen_at, "value": v[0]})
                    current[k] = v[1]
        for name in numeric:
            value = current.get(name)
            if isinstance(value, (int, float)) and (not series[name] or series[name][-1]["value"] != value):
                series[name].append({"at": c.at, "value": value})
    for name in numeric:
        if not series[name] and isinstance(item.data.get(name), (int, float)):
            series[name].append({"at": item.first_seen_at, "value": item.data[name]})
        if series[name]:
            series[name].append({"at": item.removed_at or item.last_seen_at, "value": series[name][-1]["value"]})
    series = {k: v for k, v in series.items() if v}
    return {
        "item": item_out(item),
        "columns": [{"name": f.name, "type": f.type, "multiple": f.multiple} for f in config.fields],
        "history": [change_out(c) for c in history],
        "series": series,
        "alerts": [{"id": a.id, "message": a.message, "at": a.at, "rule_name": a.rule.name} for a in alerts],
    }


@router.get("/{scraper_id}/changes")
def scraper_changes(
    scraper_id: str,
    kind: str | None = None,
    run_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    stmt = select(ItemChange).where(ItemChange.scraper_id == scraper.id)
    if kind:
        stmt = stmt.where(ItemChange.kind == kind)
    if run_id:
        stmt = stmt.where(ItemChange.run_id == run_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ItemChange.at.desc(), ItemChange.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [change_out(c, scraper) for c in rows]}


@router.get("/{scraper_id}/runs")
def scraper_runs(
    scraper_id: str, limit: int = Query(30, ge=1, le=200), user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    rows = db.scalars(select(Run).where(Run.scraper_id == scraper.id).order_by(Run.created_at.desc()).limit(limit)).all()
    return [run_brief(r) for r in rows]


# ---- export ----

def _flat(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return value


@router.get("/{scraper_id}/export")
def export(
    scraper_id: str,
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
    q: str | None = None,
    include_removed: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    config = ScraperConfig.model_validate(scraper.config)
    items = db.scalars(_items_query(scraper, q, include_removed).order_by(Item.first_seen_at, Item.id).limit(MAX_EXPORT_ROWS)).all()
    names = [f.name for f in config.fields]
    meta = ["first_seen_at", "last_changed_at", "last_seen_at", "removed_at", "source_url"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"{''.join(c if c.isalnum() else '-' for c in scraper.name.lower()).strip('-')}-{stamp}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    def meta_values(i: Item) -> list:
        return [i.first_seen_at.isoformat(), i.last_changed_at.isoformat(), i.last_seen_at.isoformat(),
                i.removed_at.isoformat() if i.removed_at else "", i.source_url or ""]

    if format == "json":
        body = json.dumps([{**{n: i.data.get(n) for n in names}, **dict(zip(meta, meta_values(i)))} for i in items],
                          ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json", headers=headers)
    if format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook(write_only=False)
        ws = wb.active
        ws.title = "".join(c for c in scraper.name if c not in '[]:*?/\\')[:31].strip() or "Data"  # Excel's sheet-name rules
        ws.append(names + meta)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for i in items:
            ws.append([_flat(i.data.get(n)) for n in names] + meta_values(i))
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

    def rows():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(names + meta)
        for i in items:
            writer.writerow([_flat(i.data.get(n)) for n in names] + meta_values(i))
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    return StreamingResponse(rows(), media_type="text/csv; charset=utf-8", headers=headers)


# ---- preview ----

@router.post("/preview")
async def preview(body: schemas.PreviewIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Run a config against one live page without saving anything."""
    render = body.config.render
    fetched = await fetch_page(db, user.workspace, body.url, render=render, wait_for=body.config.wait_for_selector)
    html, url = fetched.page.html, fetched.page.url
    if body.page_kind == "detail":
        row = Row(data={}, source_url=url)
        extract_detail_page(html, url, body.config, row)
        rows, count, next_url = [row], 1, None
        names = {f.name for f in body.config.fields_for("detail")}
    else:
        page = extract_list_page(html, url, body.config)
        rows, count, next_url = page.rows, page.item_count, page.next_url
        names = {f.name for f in body.config.fields_for("list")}
    data = [r.data for r in rows]
    return {
        "url": url,
        "render": fetched.render,
        "notes": fetched.notes,
        "item_count": count,
        "rows": [{k: v for k, v in d.items() if k in names} for d in data[:25]],
        "fill_rates": {k: v for k, v in fill_rates(data, body.config).items() if k in names},
        "errors": sorted({e for r in rows for e in r.errors})[:10],
        "next_url": next_url,
        "detail_url": next((r.detail_url for r in rows if r.detail_url), None),
    }


# ---- alert rules for this scraper ----

@router.get("/{scraper_id}/alert-rules")
def list_rules(scraper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    rules = db.scalars(select(AlertRule).where(AlertRule.scraper_id == scraper.id).order_by(AlertRule.created_at)).all()
    return [rule_out(r) for r in rules]


@router.post("/{scraper_id}/alert-rules", status_code=201)
def create_rule(scraper_id: str, body: schemas.AlertRuleIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    _validate_rule(body.kind, body.params, ScraperConfig.model_validate(scraper.config))
    rule = AlertRule(workspace_id=user.workspace_id, scraper_id=scraper.id, name=body.name.strip(), kind=body.kind,
                     params=body.params, enabled=body.enabled)
    db.add(rule)
    db.commit()
    return rule_out(rule)


def _validate_rule(kind: str, params: dict, config: ScraperConfig) -> None:
    if kind not in ALERT_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown alert type.")
    names = {f.name for f in config.fields}
    if kind == "field_change":
        if params.get("field") not in names:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a field of this scraper.")
        if params.get("direction", "any") not in ("any", "up", "down"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Direction must be any, up or down.")
        try:
            float(params.get("min_percent") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Minimum change must be a number.") from None
    if kind == "new_item" and params.get("field") and params["field"] not in names:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a field of this scraper.")
