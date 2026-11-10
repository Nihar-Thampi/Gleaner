"""Workspace-wide feeds: changes across all scrapers, alerts and alert rules."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import can_edit, get_current_user, get_owned
from app.models import AlertEvent, AlertRule, ItemChange, Scraper, User, utcnow
from app.routers.scrapers import _validate_rule
from app.scraper.config import ScraperConfig
from app.services.alerts import ALERT_KINDS
from app.services.serializers import change_out, event_out, rule_out

router = APIRouter(tags=["activity"])


@router.get("/changes")
def all_changes(
    kind: str | None = None,
    scraper_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scrapers = {s.id: s for s in db.scalars(select(Scraper).where(Scraper.workspace_id == user.workspace_id))}
    stmt = select(ItemChange).where(ItemChange.scraper_id.in_(list(scrapers) or [""]))
    if kind:
        stmt = stmt.where(ItemChange.kind == kind)
    if scraper_id:
        stmt = stmt.where(ItemChange.scraper_id == scraper_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ItemChange.at.desc(), ItemChange.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [change_out(c, scrapers[c.scraper_id]) for c in rows]}


@router.get("/alerts")
def list_alerts(
    unread: bool = False,
    scraper_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(AlertEvent).where(AlertEvent.workspace_id == user.workspace_id)
    if unread:
        stmt = stmt.where(AlertEvent.read.is_(False))
    if scraper_id:
        stmt = stmt.where(AlertEvent.scraper_id == scraper_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    unread_count = db.scalar(select(func.count()).select_from(AlertEvent).where(
        AlertEvent.workspace_id == user.workspace_id, AlertEvent.read.is_(False)))
    rows = db.scalars(stmt.order_by(AlertEvent.at.desc(), AlertEvent.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "unread": unread_count, "items": [event_out(e) for e in rows]}


@router.post("/alerts/read")
def mark_read(ids: list[int] | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mark the given alerts read, or all of them when no ids are sent."""
    stmt = update(AlertEvent).where(AlertEvent.workspace_id == user.workspace_id, AlertEvent.read.is_(False))
    if ids:
        stmt = stmt.where(AlertEvent.id.in_(ids))
    n = db.execute(stmt.values(read=True)).rowcount
    db.commit()
    return {"marked": n}


@router.get("/alert-rules")
def all_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=7)
    counts = dict(db.execute(
        select(AlertEvent.rule_id, func.count()).where(AlertEvent.workspace_id == user.workspace_id, AlertEvent.at >= since)
        .group_by(AlertEvent.rule_id)
    ).all())
    rules = db.scalars(select(AlertRule).where(AlertRule.workspace_id == user.workspace_id).order_by(AlertRule.created_at)).all()
    return {"kinds": ALERT_KINDS, "items": [rule_out(r, counts.get(r.id, 0)) for r in rules]}


@router.patch("/alert-rules/{rule_id}")
def update_rule(rule_id: str, body: schemas.AlertRuleUpdate, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    rule = get_owned(db, AlertRule, rule_id, user.workspace_id)
    data = body.model_dump(exclude_unset=True)
    if "params" in data and data["params"] is not None:
        _validate_rule(rule.kind, data["params"], ScraperConfig.model_validate(rule.scraper.config))
        rule.params = data["params"]
    if data.get("name"):
        rule.name = data["name"].strip()
    if data.get("enabled") is not None:
        rule.enabled = data["enabled"]
    db.commit()
    return rule_out(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    rule = get_owned(db, AlertRule, rule_id, user.workspace_id)
    db.delete(rule)
    db.commit()
