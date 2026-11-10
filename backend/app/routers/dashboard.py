from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AlertEvent, Item, ItemChange, Run, RunStatus, Scraper, User, utcnow
from app.scraper.policy import host_of
from app.services.serializers import change_out, event_out, run_brief, scraper_out

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DAYS = 14


@router.get("")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = user.workspace_id
    now = utcnow()
    since_day, since_week, since_chart = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=DAYS)
    scrapers = db.scalars(select(Scraper).where(Scraper.workspace_id == ws).order_by(Scraper.name)).all()
    ids = [s.id for s in scrapers] or [""]

    runs_week = db.scalars(select(Run).where(Run.workspace_id == ws, Run.created_at >= since_week)).all()
    finished = [r for r in runs_week if r.status not in (RunStatus.queued, RunStatus.running, RunStatus.cancelled)]
    ok = [r for r in finished if r.status in (RunStatus.succeeded, RunStatus.partial)]
    changes_day = db.scalar(select(func.count()).select_from(ItemChange).where(ItemChange.scraper_id.in_(ids), ItemChange.at >= since_day))
    changes_week = db.scalar(select(func.count()).select_from(ItemChange).where(ItemChange.scraper_id.in_(ids), ItemChange.at >= since_week))
    items = db.scalar(select(func.count()).select_from(Item).where(Item.scraper_id.in_(ids), Item.removed_at.is_(None)))
    unread = db.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.workspace_id == ws, AlertEvent.read.is_(False)))

    # Daily series (UTC days), oldest first, with empty days filled in.
    days = [(now - timedelta(days=i)).date() for i in range(DAYS - 1, -1, -1)]
    runs_by_day = {d: {"date": d.isoformat(), "succeeded": 0, "failed": 0} for d in days}
    for r in db.scalars(select(Run).where(Run.workspace_id == ws, Run.created_at >= since_chart)):
        d = r.created_at.date()
        if d in runs_by_day and r.status in (RunStatus.succeeded, RunStatus.partial):
            runs_by_day[d]["succeeded"] += 1
        elif d in runs_by_day and r.status == RunStatus.failed:
            runs_by_day[d]["failed"] += 1
    changes_by_day = {d: {"date": d.isoformat(), "new": 0, "changed": 0, "removed": 0} for d in days}
    for at, kind in db.execute(select(ItemChange.at, ItemChange.kind).where(ItemChange.scraper_id.in_(ids), ItemChange.at >= since_chart)):
        bucket = changes_by_day.get(at.date())
        if bucket is not None:
            bucket["new" if kind.value in ("new", "returned") else kind.value] += 1

    pages_by_host: dict[str, int] = {}
    scraper_hosts = {s.id: host_of(s.start_urls[0]) for s in scrapers if s.start_urls}
    for r in runs_week:
        host = scraper_hosts.get(r.scraper_id)
        if host:
            pages_by_host[host] = pages_by_host.get(host, 0) + r.pages_fetched

    summaries = [scraper_out(db, s) for s in scrapers]
    attention = [s for s in summaries if s["health"] in ("failing", "warning")]
    recent_runs = db.scalars(select(Run).where(Run.workspace_id == ws).order_by(Run.created_at.desc()).limit(8)).all()
    recent_alerts = db.scalars(select(AlertEvent).where(AlertEvent.workspace_id == ws).order_by(AlertEvent.at.desc()).limit(6)).all()
    by_id = {s.id: s for s in scrapers}
    notable = db.scalars(
        select(ItemChange).where(ItemChange.scraper_id.in_(ids), ItemChange.kind != "removed").order_by(ItemChange.at.desc()).limit(8)
    ).all()

    return {
        "kpis": {
            "scrapers": len(scrapers),
            "scrapers_enabled": sum(1 for s in scrapers if s.enabled),
            "items_tracked": items,
            "changes_24h": changes_day,
            "changes_7d": changes_week,
            "runs_7d": len(finished),
            "success_rate_7d": round(len(ok) / len(finished), 3) if finished else None,
            "pages_7d": sum(r.pages_fetched for r in runs_week),
            "blocked_7d": sum(r.requests_blocked for r in runs_week),
            "unread_alerts": unread,
        },
        "runs_by_day": list(runs_by_day.values()),
        "changes_by_day": list(changes_by_day.values()),
        "pages_by_host": sorted(({"host": h, "pages": n} for h, n in pages_by_host.items()), key=lambda x: -x["pages"]),
        "attention": attention,
        "scrapers": summaries,
        "recent_runs": [run_brief(r) for r in recent_runs],
        "recent_alerts": [event_out(e) for e in recent_alerts],
        "recent_changes": [change_out(c, by_id[c.scraper_id]) for c in notable],
    }
