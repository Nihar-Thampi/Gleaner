"""Fetching single pages for the editor (preview, AI suggest, AI repair).

These go through the same Fetcher as runs, so the editor can't be used to sidestep the
domain approval, robots.txt or rate limits.
"""
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Domain, Workspace
from app.scraper.extract import looks_javascript_rendered
from app.scraper.fetcher import Blocked, FetchFailed, Fetcher, Page
from app.scraper.policy import domain_block_reason, host_of, user_agent


@dataclass
class FetchedPage:
    page: Page
    render: str  # what was used: static or browser
    notes: list[str]


def _domains(db: Session, workspace_id: str) -> dict[str, Domain]:
    return {d.host: d for d in db.scalars(select(Domain).where(Domain.workspace_id == workspace_id))}


def require_approved(db: Session, workspace_id: str, url: str) -> None:
    host = host_of(url)
    domain = _domains(db, workspace_id).get(host)
    if reason := domain_block_reason(domain, host):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "domain_not_approved", "host": host, "status": domain.status.value if domain else None, "message": reason},
        )


async def fetch_page(db: Session, workspace: Workspace, url: str, render: str = "auto", wait_for: str | None = None) -> FetchedPage:
    """render: static, browser, or auto (static, then browser if the page looks JavaScript-built)."""
    require_approved(db, workspace.id, url)
    notes: list[str] = []
    fetcher = Fetcher(domains=_domains(db, workspace.id), user_agent=user_agent(workspace))
    try:
        mode = "browser" if render == "browser" else "static"
        page = await fetcher.fetch(url, render=mode, wait_for=wait_for)
        if render == "auto" and looks_javascript_rendered(page.html):
            try:
                page = await fetcher.fetch(url, render="browser", wait_for=wait_for)
                mode = "browser"
                notes.append("This page builds its content with JavaScript, so it was rendered in a headless browser.")
            except FetchFailed as e:
                notes.append(f"This page looks JavaScript-built, but browser rendering isn't available here ({e}).")
        db.commit()  # keep any robots.txt the fetch refreshed
        return FetchedPage(page=page, render=mode, notes=notes)
    except Blocked as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "blocked", "message": str(e)}) from None
    except FetchFailed as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't load the page: {e}") from None
    finally:
        await fetcher.close()
