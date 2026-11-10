"""AI features: selector assistant, scraper repair, and the AI activity log."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import schemas
from app.ai.client import provider_status
from app.ai.heuristics import parse_field_requests
from app.ai.selectors import evaluate, repair, suggest
from app.db import get_db
from app.deps import admin_only, can_edit, get_current_user, get_owned
from app.models import AIRequest, Run, RunStatus, Scraper, User
from app.scraper.config import ScraperConfig
from app.services.pages import fetch_page
from app.services.serializers import ai_request_out

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status(user: User = Depends(get_current_user)):
    provider, model = provider_status()
    return {"provider": provider, "model": model, "is_demo": provider == "demo"}


@router.post("/suggest")
async def suggest_selectors(body: schemas.SuggestIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Describe the fields in plain English; get a verified config and a live preview."""
    descriptions = parse_field_requests(body.fields)
    if not descriptions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "List at least one field you want.")
    fetched = await fetch_page(db, user.workspace, body.url, render="auto")
    check, result = suggest(
        db=db, workspace_id=user.workspace_id, user_id=user.id, url=fetched.page.url, page_html=fetched.page.html,
        descriptions=descriptions, page_kind=body.page_kind,
    )
    db.commit()
    if check.get("valid") and fetched.render == "browser":
        check["config"]["render"] = "browser"
    return {**check, "render": fetched.render, "notes": fetched.notes + check.get("notes", []),
            "provider": result.provider, "model": result.model}


@router.post("/repair/{scraper_id}")
async def repair_scraper(scraper_id: str, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Propose a fix for a scraper whose latest run broke. Nothing is saved until the user applies it."""
    scraper = get_owned(db, Scraper, scraper_id, user.workspace_id)
    config = ScraperConfig.model_validate(scraper.config)
    last = db.scalar(select(Run).where(Run.scraper_id == scraper.id, Run.status.not_in([RunStatus.queued, RunStatus.running]))
                     .order_by(Run.created_at.desc()).limit(1))
    symptoms = []
    if last:
        if last.error:
            symptoms.append(last.error)
        symptoms += [a["message"] for a in last.anomalies or []]
    symptoms = symptoms or ["The user reports the scraper isn't extracting the right data."]
    url = scraper.start_urls[0]
    fetched = await fetch_page(db, user.workspace, url, render="auto" if config.render == "static" else "browser",
                               wait_for=config.wait_for_selector)

    # Cheapest fix first: if the current selectors work once JavaScript has run, only the render mode changed.
    if fetched.render == "browser" and config.render == "static":
        as_browser = config.model_dump() | {"render": "browser"}
        check = evaluate(fetched.page.html, fetched.page.url, as_browser, "list")
        rates = check.get("fill_rates", {})
        required = {f.name for f in config.fields if f.required and f.source == "list"}
        works = (check.get("valid") and check["item_count"] and rates
                 and all(rates.get(n, 0) >= 0.9 for n in required) and sum(rates.values()) / len(rates) >= 0.75)
        if works:
            empty = [n for n, r in rates.items() if r < 0.5]
            return {**check, "render": "browser", "provider": "rules", "model": "render-check",
                    "notes": ["The page now builds its content with JavaScript. Your selectors still work once it's "
                              "rendered, so the fix is to switch this scraper to browser rendering."]
                    + ([f"Still empty after rendering: {', '.join(empty)}. That data may not be on this version of the page."] if empty else []),
                    "problems": [f"{n} filled for {rates[n]:.0%} of items" for n in empty], "symptoms": symptoms}

    check, result = repair(
        db=db, workspace_id=user.workspace_id, user_id=user.id, url=fetched.page.url, page_html=fetched.page.html,
        current=config, symptoms=symptoms,
    )
    db.commit()
    if check.get("valid") and fetched.render == "browser":
        check["config"]["render"] = "browser"
    return {**check, "render": fetched.render, "notes": fetched.notes + check.get("notes", []),
            "provider": result.provider, "model": result.model, "symptoms": symptoms}


@router.get("/requests")
def list_requests(
    feature: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    stmt = select(AIRequest).where(AIRequest.workspace_id == admin.workspace_id)
    if feature:
        stmt = stmt.where(AIRequest.feature == feature)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    stats = db.execute(
        select(func.count(), func.avg(AIRequest.latency_ms), func.sum(AIRequest.input_tokens), func.sum(AIRequest.output_tokens),
               func.sum(case((AIRequest.success.is_(False), 1), else_=0)))
        .where(AIRequest.workspace_id == admin.workspace_id)
    ).one()
    rows = db.scalars(stmt.order_by(AIRequest.created_at.desc()).limit(limit).offset(offset)).all()
    return {
        "total": total,
        "stats": {"requests": stats[0], "avg_latency_ms": int(stats[1] or 0), "input_tokens": stats[2] or 0,
                  "output_tokens": stats[3] or 0, "failures": int(stats[4] or 0)},
        "items": [ai_request_out(r) for r in rows],
    }


@router.get("/requests/{request_id}")
def get_request(request_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    return ai_request_out(get_owned(db, AIRequest, request_id, admin.workspace_id), full=True)
