"""Data API for other systems, authenticated with an API key (X-API-Key header)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_api_key, get_owned
from app.models import ApiKey, Item, ItemChange, Run, Scraper
from app.services import runs as run_service
from app.services.serializers import change_out, item_out, run_brief, run_out, scraper_out
from app.worker import worker

router = APIRouter(prefix="/v1", tags=["data API (API key)"])


@router.get("/scrapers")
def scrapers(key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    rows = db.scalars(select(Scraper).where(Scraper.workspace_id == key.workspace_id).order_by(Scraper.name)).all()
    return [{k: v for k, v in scraper_out(db, s).items() if k not in ("domain_status",)} for s in rows]


@router.get("/scrapers/{scraper_id}/items")
def items(
    scraper_id: str,
    updated_since: datetime | None = Query(None, description="Only items changed at or after this time (ISO 8601)"),
    include_removed: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, key.workspace_id)
    stmt = select(Item).where(Item.scraper_id == scraper.id)
    if not include_removed:
        stmt = stmt.where(Item.removed_at.is_(None))
    if updated_since:
        stmt = stmt.where(Item.last_changed_at >= updated_since)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Item.first_seen_at, Item.id).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [item_out(i) for i in rows]}


@router.get("/scrapers/{scraper_id}/changes")
def changes(
    scraper_id: str,
    since: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    scraper = get_owned(db, Scraper, scraper_id, key.workspace_id)
    stmt = select(ItemChange).where(ItemChange.scraper_id == scraper.id)
    if since:
        stmt = stmt.where(ItemChange.at >= since)
    rows = db.scalars(stmt.order_by(ItemChange.at.desc(), ItemChange.id.desc()).limit(limit).offset(offset)).all()
    return {"items": [change_out(c, scraper) for c in rows]}


@router.get("/runs/{run_id}")
def run(run_id: str, key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    out = run_out(get_owned(db, Run, run_id, key.workspace_id))
    out.pop("config", None)
    return out


@router.post("/scrapers/{scraper_id}/runs", status_code=201)
def trigger(scraper_id: str, key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    if not key.can_trigger_runs:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This API key can read data but not start runs.")
    scraper = get_owned(db, Scraper, scraper_id, key.workspace_id)
    r = run_service.enqueue(db, scraper, trigger="api")
    db.commit()
    worker.wake()
    return run_brief(r)
