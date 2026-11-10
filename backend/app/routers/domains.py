"""Domains: the compliance gate. Nothing is fetched from a site until an admin approves it
and records why scraping it is acceptable."""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import admin_only, can_edit, get_current_user, get_owned
from app.models import Domain, DomainStatus, Role, Scraper, User, utcnow
from app.scraper import policy
from app.scraper.fetcher import Fetcher
from app.services.serializers import domain_out

router = APIRouter(prefix="/domains", tags=["domains"])


def _scraper_counts(db: Session, workspace_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for urls in db.scalars(select(Scraper.start_urls).where(Scraper.workspace_id == workspace_id)):
        for host in {policy.host_of(u) for u in urls}:
            counts[host] = counts.get(host, 0) + 1
    return counts


@router.get("")
def list_domains(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = _scraper_counts(db, user.workspace_id)
    rows = db.scalars(select(Domain).where(Domain.workspace_id == user.workspace_id).order_by(Domain.host)).all()
    return [domain_out(d, counts.get(d.host, 0)) for d in rows]


@router.get("/{domain_id}")
def get_domain(domain_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_owned(db, Domain, domain_id, user.workspace_id)
    return domain_out(d, _scraper_counts(db, user.workspace_id).get(d.host, 0), with_robots=True)


@router.post("", status_code=201)
async def add_domain(body: schemas.DomainIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Editors request a domain (pending); admins can approve it in the same step."""
    if body.approve and user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can approve domains.")
    if body.approve and not body.basis.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Record why scraping this site is allowed before approving it.")
    domain = Domain(
        workspace_id=user.workspace_id, host=policy.host_of(body.url), basis=body.basis.strip(),
        requests_per_minute=body.requests_per_minute,
        status=DomainStatus.approved if body.approve else DomainStatus.pending,
        reviewed_by_id=user.id if body.approve else None, reviewed_at=utcnow() if body.approve else None,
    )
    db.add(domain)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{domain.host} is already on the list.")
    await _refresh(db, user, domain, urlsplit(body.url).scheme)
    return domain_out(domain, with_robots=True)


@router.patch("/{domain_id}")
def update_domain(domain_id: str, body: schemas.DomainUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    d = get_owned(db, Domain, domain_id, admin.workspace_id)
    data = body.model_dump(exclude_unset=True)
    if "basis" in data:
        d.basis = data["basis"].strip()
    if "requests_per_minute" in data:
        d.requests_per_minute = data["requests_per_minute"]
    if data.get("status") and data["status"] != d.status:
        if data["status"] == DomainStatus.approved and not d.basis:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Record why scraping this site is allowed before approving it.")
        d.status, d.reviewed_by_id, d.reviewed_at = data["status"], admin.id, utcnow()
    db.commit()
    db.refresh(d)
    return domain_out(d, with_robots=True)


@router.delete("/{domain_id}", status_code=204)
def delete_domain(domain_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    d = get_owned(db, Domain, domain_id, admin.workspace_id)
    if _scraper_counts(db, admin.workspace_id).get(d.host):
        raise HTTPException(status.HTTP_409_CONFLICT, "Scrapers still use this domain. Block it instead, or delete those scrapers first.")
    db.delete(d)
    db.commit()


async def _refresh(db: Session, user: User, domain: Domain, scheme: str = "https") -> None:
    fetcher = Fetcher(domains={domain.host: domain}, user_agent=policy.user_agent(user.workspace))
    try:
        await fetcher.refresh_robots(domain, scheme)
    finally:
        await fetcher.close()
    db.commit()


@router.post("/{domain_id}/robots")
async def refresh_robots(domain_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    d = get_owned(db, Domain, domain_id, user.workspace_id)
    scheme = "http" if d.host.startswith(("127.0.0.1", "localhost")) else "https"
    await _refresh(db, user, d, scheme)
    return domain_out(d, with_robots=True)


@router.post("/check")
async def check_url(body: schemas.UrlCheckIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Would the crawler fetch this URL? Explains the answer."""
    host = policy.host_of(body.url)
    domain = db.scalar(select(Domain).where(Domain.workspace_id == user.workspace_id, Domain.host == host))
    out = {"url": body.url, "host": host, "domain_status": domain.status.value if domain else None, "allowed": False}
    if reason := policy.domain_block_reason(domain, host):
        return {**out, "reason": reason}
    if policy.robots_is_stale(domain):
        await _refresh(db, user, domain, urlsplit(body.url).scheme)
    robots = policy.robots_from_domain(domain)
    allowed = robots.allows(body.url)
    return {
        **out,
        "allowed": allowed,
        "reason": "Allowed by robots.txt." if allowed and robots.status and robots.status < 400 else robots.summary if allowed
        else f"robots.txt disallows this path for {policy.BOT_NAME}." if robots.status and robots.status < 400 else robots.summary,
        "seconds_between_requests": round(policy.min_interval_seconds(domain), 2),
    }
