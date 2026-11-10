from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import can_edit, get_current_user, get_owned
from app.models import ACTIVE_RUN_STATUSES, Run, RunLog, RunStatus, User, utcnow
from app.services.serializers import run_brief, run_out

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(
    scraper_id: str | None = None,
    status_: RunStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Run).where(Run.workspace_id == user.workspace_id)
    if scraper_id:
        stmt = stmt.where(Run.scraper_id == scraper_id)
    if status_:
        stmt = stmt.where(Run.status == status_)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Run.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [run_brief(r) for r in rows]}


@router.get("/{run_id}")
def get_run(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_out(get_owned(db, Run, run_id, user.workspace_id))


@router.get("/{run_id}/logs")
def run_logs(
    run_id: str,
    after: int = Query(0, ge=0, description="Only entries with a larger id (for live tailing)"),
    level: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = get_owned(db, Run, run_id, user.workspace_id)
    stmt = select(RunLog).where(RunLog.run_id == run.id, RunLog.id > after)
    if level:
        stmt = stmt.where(RunLog.level == level)
    rows = db.scalars(stmt.order_by(RunLog.id).limit(limit)).all()
    return [{"id": r.id, "at": r.at, "level": r.level, "message": r.message, "url": r.url} for r in rows]


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    run = get_owned(db, Run, run_id, user.workspace_id)
    if run.status not in ACTIVE_RUN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This run has already finished.")
    if run.status == RunStatus.queued:
        run.status, run.finished_at, run.cancel_requested = RunStatus.cancelled, utcnow(), True
        db.add(RunLog(run_id=run.id, level="warning", message=f"Cancelled by {user.full_name} before it started."))
    else:
        run.cancel_requested = True
        db.add(RunLog(run_id=run.id, level="warning", message=f"{user.full_name} asked to cancel; stopping after the current page."))
    db.commit()
    return run_brief(run)
