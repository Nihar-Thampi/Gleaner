"""Queueing runs and scheduling."""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ACTIVE_RUN_STATUSES, Run, RunStatus, Scraper, utcnow


def active_run(db: Session, scraper_id: str) -> Run | None:
    return db.scalar(select(Run).where(Run.scraper_id == scraper_id, Run.status.in_(ACTIVE_RUN_STATUSES)).limit(1))


def next_number(db: Session, scraper_id: str) -> int:
    return (db.scalar(select(func.max(Run.number)).where(Run.scraper_id == scraper_id)) or 0) + 1


def snapshot(scraper: Scraper) -> dict:
    return {**scraper.config, "start_urls": list(scraper.start_urls)}


def enqueue(db: Session, scraper: Scraper, *, trigger: str, user_id: str | None = None) -> Run:
    """Queue a run. One run per scraper at a time."""
    if active_run(db, scraper.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scraper already has a run in progress.")
    run = Run(
        workspace_id=scraper.workspace_id,
        scraper_id=scraper.id,
        number=next_number(db, scraper.id),
        trigger=trigger,
        triggered_by_id=user_id,
        config_snapshot=snapshot(scraper),
    )
    db.add(run)
    db.flush()
    return run


def next_run_time(scraper: Scraper, after: datetime | None = None) -> datetime | None:
    if not scraper.enabled or not scraper.schedule_minutes:
        return None
    return (after or utcnow()) + timedelta(minutes=scraper.schedule_minutes)


def queue_due_scrapers(db: Session, now: datetime | None = None) -> list[Run]:
    now = now or utcnow()
    due = db.scalars(
        select(Scraper).where(Scraper.enabled.is_(True), Scraper.schedule_minutes.is_not(None), Scraper.next_run_at <= now)
    ).all()
    runs = []
    for scraper in due:
        scraper.next_run_at = next_run_time(scraper, now)
        if active_run(db, scraper.id):
            continue  # still busy from last time; try again at the next slot
        runs.append(enqueue(db, scraper, trigger="schedule"))
    db.commit()
    return runs


def fail_interrupted_runs(db: Session) -> int:
    """Runs left 'running' by a restart can't resume; mark them failed so they don't block."""
    stuck = db.scalars(select(Run).where(Run.status == RunStatus.running)).all()
    for run in stuck:
        run.status, run.finished_at = RunStatus.failed, utcnow()
        run.error = "Interrupted: the server restarted while this run was in progress."
    db.commit()
    return len(stuck)
