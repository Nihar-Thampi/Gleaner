"""Execute one run end to end.

listing pages (+ pagination) -> rows -> detail pages -> ingest (changes) -> health checks
-> alerts -> AI summary -> webhooks

Progress is committed as the run goes, so the UI can show it live; a cancel request is
honoured between pages.
"""
import asyncio
import logging

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.summary import summarize
from app.db import SessionLocal
from app.models import Domain, Item, Run, RunLog, RunStatus, Workspace, utcnow
from app.scraper.config import ScraperConfig
from app.scraper.extract import Row, extract_detail_page, extract_list_page, looks_javascript_rendered
from app.scraper.fetcher import Blocked, FetchFailed, Fetcher
from app.scraper.policy import user_agent
from app.services import alerts, checks, ingest, webhooks

logger = logging.getLogger(__name__)

DETAIL_CONCURRENCY = 3


class Cancelled(Exception):
    pass


class RunContext:
    def __init__(self, db: Session, run: Run):
        self.db = db
        self.run = run

    def log(self, level: str, message: str, url: str | None = None) -> None:
        self.db.add(RunLog(run_id=self.run.id, level=level, message=message[:2000], url=url))

    def save(self) -> None:
        self.db.commit()

    def check_cancel(self) -> None:
        self.db.refresh(self.run, ["cancel_requested"])
        if self.run.cancel_requested:
            raise Cancelled()


async def _crawl(ctx: RunContext, fetcher: Fetcher, config: ScraperConfig, start_urls: list[str]) -> tuple[list[Row], bool, str | None]:
    """Returns (rows, complete, first_error). `complete` means every listing page was seen."""
    run = ctx.run
    rows: list[Row] = []
    complete = True
    first_error = None
    js_hint_logged = False

    for start in start_urls:
        url: str | None = start
        visited: set[str] = set()
        pages = 0
        while url:
            ctx.check_cancel()
            if pages >= config.max_pages:
                ctx.log("info", f"Stopped after {config.max_pages} pages (the scraper's page limit). Items on later pages weren't checked, so removals aren't detected this run.", url)
                complete = False
                break
            try:
                page = await fetcher.fetch(url, render=config.render, wait_for=config.wait_for_selector)
            except Blocked as e:
                run.requests_blocked += 1
                ctx.log("warning", f"Skipped: {e}", url)
                first_error = first_error or str(e)
                complete = False
                break
            except FetchFailed as e:
                run.pages_failed += 1
                ctx.log("error", f"Failed to load listing page: {e}", url)
                first_error = first_error or f"{e} ({url})"
                complete = False
                break
            run.pages_fetched += 1
            visited.add(url)
            visited.add(page.url)
            result = extract_list_page(page.html, page.url, config)
            if config.item_selector and result.item_count == 0:
                ctx.log("warning", f"No items matched “{config.item_selector}” on this page.", page.url)
                if config.render == "static" and not js_hint_logged and looks_javascript_rendered(page.html):
                    ctx.log("warning", "This page appears to build its content with JavaScript. Switch the scraper to browser rendering, or use AI repair.", page.url)
                    js_hint_logged = True
                complete = False
                ctx.save()
                break  # an empty page means the selectors are off; following more pages won't help
            else:
                ctx.log("info", f"Page {pages + 1}: {result.item_count} items.", page.url)

            page_rows = result.rows
            if config.has_detail:
                page_rows, ok = await _fetch_details(ctx, fetcher, config, page_rows)
                complete = complete and ok
            rows.extend(page_rows)
            run.items_extracted = len(rows)
            ctx.save()

            if config.max_items and len(rows) >= config.max_items:
                rows = rows[: config.max_items]
                run.items_extracted = len(rows)
                ctx.log("info", f"Reached the limit of {config.max_items} items.")
                complete = False
                break
            url = result.next_url if result.next_url not in visited else None
            pages += 1
    return rows, complete, first_error


async def _fetch_details(ctx: RunContext, fetcher: Fetcher, config: ScraperConfig, rows: list[Row]) -> tuple[list[Row], bool]:
    """Fill detail fields. A row whose detail page fails is dropped (rather than stored
    with blanks, which would look like a change), and removals are skipped this run."""
    run = ctx.run
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)
    kept: list[Row | None] = [None] * len(rows)
    ok = True

    async def one(i: int, row: Row) -> None:
        nonlocal ok
        if not row.detail_url:
            row.errors.append("detail: no link found on the listing page")
            kept[i] = row
            return
        async with sem:
            try:
                page = await fetcher.fetch(row.detail_url, render=config.render, wait_for=config.wait_for_selector)
            except Blocked as e:
                run.requests_blocked += 1
                ctx.log("warning", f"Skipped detail page: {e}", row.detail_url)
                ok = False
                return
            except FetchFailed as e:
                run.pages_failed += 1
                ctx.log("error", f"Failed to load detail page: {e}", row.detail_url)
                ok = False
                return
        run.pages_fetched += 1
        extract_detail_page(page.html, page.url, config, row)
        kept[i] = row

    tasks = [asyncio.create_task(one(i, r)) for i, r in enumerate(rows)]
    try:
        for n, task in enumerate(asyncio.as_completed(tasks), 1):
            await task
            if n % 10 == 0:
                ctx.save()
                ctx.check_cancel()
    except Cancelled:
        for t in tasks:
            t.cancel()
        raise
    return [r for r in kept if r is not None], ok


def _apply_fetch_stats(run: Run, fetcher: Fetcher) -> None:
    s = fetcher.stats
    run.retries = s.retries
    run.bytes_downloaded = s.bytes
    run.total_response_ms = s.total_ms
    run.status_codes = dict(s.status_codes)


async def execute_run(run_id: str, *, transport: httpx.AsyncBaseTransport | None = None, webhook_transport=None) -> None:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if run is None or run.status != RunStatus.queued:
            return
        ctx = RunContext(db, run)
        scraper = run.scraper
        workspace = db.get(Workspace, run.workspace_id)
        run.status, run.started_at = RunStatus.running, utcnow()
        config = ScraperConfig.model_validate(run.config_snapshot)
        start_urls = run.config_snapshot.get("start_urls") or scraper.start_urls
        ctx.log("info", f"Run #{run.number} started ({run.trigger}). {len(start_urls)} start URL(s), {config.render} fetching.")
        ctx.save()

        domains = {d.host: d for d in db.scalars(select(Domain).where(Domain.workspace_id == run.workspace_id))}
        fetcher = Fetcher(
            domains=domains,
            user_agent=user_agent(workspace),
            on_robots=lambda d: ctx.log("info", f"Fetched robots.txt for {d.host}: {('HTTP ' + str(d.robots_status)) if d.robots_status else 'unreachable'}" + (f", Crawl-delay {d.crawl_delay:g}s" if d.crawl_delay else "") + "."),
            on_retry=lambda url, why: ctx.log("warning", f"Retrying: {why}", url),
            transport=transport,
        )
        cancelled = False
        try:
            rows, complete, first_error = await _crawl(ctx, fetcher, config, start_urls)
        except Cancelled:
            cancelled, complete, first_error = True, False, None
            rows = []
            ctx.log("warning", "Cancelled by a user. Nothing from this run was stored.")
        finally:
            _apply_fetch_stats(run, fetcher)
            await fetcher.close()

        now = utcnow()
        tracked_before = db.scalar(select(func.count()).select_from(Item).where(Item.scraper_id == scraper.id, Item.removed_at.is_(None))) or 0
        changes = []
        if cancelled:
            run.status = RunStatus.cancelled
        elif run.pages_fetched == 0:
            run.status = RunStatus.failed
            run.error = first_error or "No pages could be fetched."
        elif config.item_selector and not rows:
            run.status = RunStatus.failed
            run.error = "The item selector matched nothing. The site's layout may have changed (try AI repair)."
            run.anomalies = [checks.anomaly("selector_broken", "critical", run.error)]
        else:
            result = ingest.ingest(db, scraper, run, rows, complete=complete, now=now)
            run.items_invalid = result.invalid
            run.items_new, run.items_changed = result.new + result.returned, result.changed
            run.items_removed, run.items_unchanged = result.removed, result.unchanged
            run.quality = result.quality
            changes = result.changes
            db.flush()
            run.anomalies = checks.run_checks(db, run, result, tracked_before)
            run.status = RunStatus.partial if (run.pages_failed or run.requests_blocked) else RunStatus.succeeded
            if result.baseline:
                ctx.log("info", f"First run: {result.new} items recorded as the baseline. Later runs report changes against it.")
            if not complete and not cancelled:
                ctx.log("info", "Not every listing page was read, so items missing from this run weren't marked as removed.")
        run.finished_at = utcnow()
        fired = alerts.evaluate(db, run, changes)
        ctx.log(
            "info" if run.status in (RunStatus.succeeded, RunStatus.partial) else "error",
            f"Finished: {run.status.value}. {run.items_extracted} items, {run.items_new} new, {run.items_changed} changed, "
            f"{run.items_removed} removed; {run.pages_fetched} pages, {run.pages_failed} failed, {run.requests_blocked} blocked."
            + (f" {len(fired)} alert(s) fired." if fired else ""),
        )
        ctx.save()

        if workspace.ai_run_summaries and run.status in (RunStatus.succeeded, RunStatus.partial) and (changes or run.anomalies):
            try:
                ai = summarize(db, run, changes)
                run.ai_summary = {**ai.data, "provider": ai.provider, "model": ai.model}
                ctx.save()
            except Exception:  # noqa: BLE001 - a summary is never worth failing a run over
                logger.exception("Run summary failed for %s", run.id)
                db.rollback()

        payload = run_payload(run)
        await webhooks.dispatch(db, run.workspace_id, "run.finished", payload, webhook_transport)
        if fired:
            await webhooks.dispatch(db, run.workspace_id, "alert.fired", {
                "run": {"id": run.id, "number": run.number, "scraper_id": run.scraper_id, "scraper": scraper.name},
                "alerts": [{"rule": e.rule.name, "kind": e.rule.kind, "message": e.message, "item_id": e.item_id} for e in fired],
            }, webhook_transport)
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("Run %s crashed", run_id)
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            run.status, run.finished_at = RunStatus.failed, utcnow()
            run.error = f"Internal error: {type(e).__name__}. Details are in the server log."
            db.add(RunLog(run_id=run_id, level="error", message=run.error))
            db.commit()
    finally:
        db.close()


def run_payload(run: Run) -> dict:
    return {
        "id": run.id,
        "number": run.number,
        "scraper_id": run.scraper_id,
        "scraper": run.scraper.name,
        "status": run.status.value,
        "trigger": run.trigger,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "items": {"found": run.items_extracted, "new": run.items_new, "changed": run.items_changed,
                  "removed": run.items_removed, "invalid": run.items_invalid},
        "pages": {"fetched": run.pages_fetched, "failed": run.pages_failed, "blocked": run.requests_blocked},
        "anomalies": run.anomalies,
        "summary": (run.ai_summary or {}).get("headline"),
        "error": run.error,
    }
