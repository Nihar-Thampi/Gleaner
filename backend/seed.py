"""Demo data: a workspace, its team, approved domains, six scrapers and run history.

    python seed.py            # wipe and rebuild the demo database
    SEED_LIVE=0 python seed.py  # skip the live runs against the public sandbox sites

The practice store's 30-day history is rebuilt day by day with the real extractor and
ingest code, rendering the store as it looked on each date, so every change, alert and
anomaly in it was produced by the same pipeline a live run uses. The other scrapers get
one real run each against the public practice sites (books.toscrape.com and friends).
"""
import asyncio
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import Base, SessionLocal, engine
from app.deps import hash_api_key
from app.models import (
    AlertEvent, AlertRule, ApiKey, Domain, DomainStatus, Role, Run, RunLog, RunStatus, Scraper, User, Webhook, Workspace,
)
from app import practice
from app.ai.summary import _demo as demo_summary
from app.scraper.config import ScraperConfig
from app.scraper.extract import Row, extract_detail_page, extract_list_page
from app.scraper.policy import host_of
from app.services import alerts, checks, ingest, runs as run_service

DEMO_PASSWORD = "Gleaner!2026"
HISTORY_DAYS = 30


def f(name, selector="", **kw):
    return {"name": name, "selector": selector, **kw}


STORE_CONFIG = {
    "item_selector": "article.product-card",
    "fields": [
        f("name", "h2.product-name a", required=True),
        f("url", "h2.product-name a", attr="href", type="url", required=True),
        f("brand", "p.brand"),
        f("price", "span.price-now", type="price", required=True),
        f("was_price", "s.price-was", type="price"),
        f("stock", "p.stock"),
        f("rating", "div.rating", attr="data-rating", type="number"),
        f("reviews", "span.reviews", type="integer"),
        f("sku", "dd.sku", source="detail"),
        f("weight_g", "dd.weight", type="integer", source="detail"),
    ],
    "detail_link_selector": "h2.product-name a",
    "next_page_selector": "a.next",
    "max_pages": 10,
    "key_fields": ["url"],
}

BOOKS_CONFIG = {
    "item_selector": "article.product_pod",
    "fields": [
        f("title", "h3 a", attr="title", required=True),
        f("url", "h3 a", attr="href", type="url", required=True),
        f("price", "p.price_color", type="price", required=True),
        f("rating", "p.star-rating", attr="class", type="integer", regex=r"\b(One|Two|Three|Four|Five)\b",
          value_map={"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}),
        f("in_stock", "p.availability", type="boolean", regex=r"\bin stock\b"),
    ],
    "next_page_selector": "li.next a",
    "max_pages": 10,
    "key_fields": ["url"],
}

QUOTES_FIELDS = [
    f("text", "span.text", required=True),
    f("author", "small.author", required=True),
    f("tags", "a.tag", multiple=True),
    f("author_url", "span a", attr="href", type="url"),
]
QUOTES_CONFIG = {"item_selector": "div.quote", "fields": QUOTES_FIELDS, "next_page_selector": "li.next a", "max_pages": 10, "key_fields": ["text"]}

COUNTRIES_CONFIG = {
    "item_selector": "div.country",
    "fields": [
        f("name", "h3.country-name", required=True),
        f("capital", "span.country-capital"),
        f("population", "span.country-population", type="integer"),
        f("area_km2", "span.country-area", type="number"),
    ],
    "max_pages": 1,
    "key_fields": ["name"],
}

HOCKEY_CONFIG = {
    "item_selector": "tr.team",
    "fields": [
        f("team", "td.name", required=True),
        f("year", "td.year", type="integer", required=True),
        f("wins", "td.wins", type="integer"),
        f("losses", "td.losses", type="integer"),
        f("win_pct", "td.pct", type="number"),
        f("goals_for", "td.gf", type="integer"),
        f("goals_against", "td.ga", type="integer"),
    ],
    "next_page_selector": 'a[aria-label="Next"]',
    "max_pages": 5,
    "key_fields": ["team", "year"],
}


def reset() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def at(day: datetime.date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


def simulate_store_run(db, scraper: Scraper, day, *, fail_detail: str | None = None) -> Run:
    """One run of the practice-store scraper as of `day`, through the real extractor and ingest."""
    started = at(day, 6, 0) + timedelta(seconds=(day.toordinal() * 37) % 300)
    run = run_service.enqueue(db, scraper, trigger="schedule")
    run.created_at = run.started_at = started
    run.status = RunStatus.running
    db.flush()
    config = ScraperConfig.model_validate(run.config_snapshot)
    base = scraper.start_urls[0]
    logs = [RunLog(run_id=run.id, at=started, level="info", message=f"Run #{run.number} started (schedule). 1 start URL(s), static fetching.")]

    rows: list[Row] = []
    complete = True
    page, size, ms, requests = 1, 0, 0, 0
    while True:
        html = practice.render_listing(day, page)
        url = base if page == 1 else f"{base}?page={page}"
        result = extract_list_page(html, url, config)
        requests += 1
        size += len(html.encode())
        ms += 35 + (day.toordinal() + page) % 40
        logs.append(RunLog(run_id=run.id, at=started + timedelta(seconds=requests), level="info", message=f"Page {page}: {result.item_count} items.", url=url))
        for row in result.rows:
            slug = row.detail_url.rsplit("/", 1)[-1]
            if fail_detail and slug == fail_detail:
                run.pages_failed += 1
                complete = False
                logs.append(RunLog(run_id=run.id, at=started + timedelta(seconds=requests), level="error",
                                   message="Failed to load detail page: ReadTimeout after 4 attempts", url=row.detail_url))
                continue
            detail = practice.render_product(day, slug)
            requests += 1
            size += len(detail.encode())
            ms += 30 + (day.toordinal() + requests) % 50
            extract_detail_page(detail, row.detail_url, config, row)
            rows.append(row)
        if not result.next_url:
            break
        page += 1

    run.pages_fetched = requests
    run.bytes_downloaded, run.total_response_ms = size, ms
    run.status_codes = {"200": requests}
    if run.pages_failed:
        run.retries = 3
        run.status_codes["504"] = 4
    run.items_extracted = len(rows)
    finished = started + timedelta(seconds=requests // 2 + 4)
    tracked_before = sum(1 for i in db.query(ingest.Item).filter_by(scraper_id=scraper.id, removed_at=None))
    result = ingest.ingest(db, scraper, run, rows, complete=complete, now=finished)
    run.items_invalid, run.items_new, run.items_changed = result.invalid, result.new + result.returned, result.changed
    run.items_removed, run.items_unchanged = result.removed, result.unchanged
    run.quality = result.quality
    db.flush()
    run.anomalies = checks.run_checks(db, run, result, tracked_before)
    run.status = RunStatus.partial if run.pages_failed else RunStatus.succeeded
    run.finished_at = finished
    for e in alerts.evaluate(db, run, result.changes):
        e.at = finished
        e.read = (datetime.now(timezone.utc) - finished).days > 2
    if result.changes or run.anomalies:
        run.ai_summary = {**demo_summary(run, result.changes, config), "provider": "demo", "model": "rules-v1"}
    logs.append(RunLog(
        run_id=run.id, at=finished, level="info",
        message=f"Finished: {run.status.value}. {run.items_extracted} items, {run.items_new} new, {run.items_changed} changed, "
        f"{run.items_removed} removed; {run.pages_fetched} pages, {run.pages_failed} failed, 0 blocked.",
    ))
    if not complete:
        logs.append(RunLog(run_id=run.id, at=finished, level="info", message="Not every listing page was read, so items missing from this run weren't marked as removed."))
    db.add_all(logs)
    db.commit()
    return run


async def live_runs(run_ids: list[str]) -> None:
    from app.scraper.engine import execute_run

    await asyncio.gather(*(execute_run(rid) for rid in run_ids))


def main() -> None:
    settings = get_settings()
    reset()
    db = SessionLocal()

    ws = Workspace(name="Meridian Market Intelligence", contact_email="data-team@meridian.demo")
    db.add(ws)
    db.flush()
    pw = hash_password(DEMO_PASSWORD)
    admin = User(workspace_id=ws.id, email="admin@meridian.demo", full_name="Jordan Lee", role=Role.admin, password_hash=pw)
    editor = User(workspace_id=ws.id, email="aisha@meridian.demo", full_name="Aisha Khan", role=Role.editor, password_hash=pw)
    viewer = User(workspace_id=ws.id, email="tom@meridian.demo", full_name="Tom Becker", role=Role.viewer, password_hash=pw)
    db.add_all([admin, editor, viewer])
    db.flush()

    now = datetime.now(timezone.utc)
    store_url = settings.public_base_url.rstrip("/") + practice.BASE
    sandbox = "Public sandbox built for practising web scraping; no terms restrict automated access. robots.txt is honoured."
    approved = lambda host, basis, rpm, days_ago: Domain(  # noqa: E731
        workspace_id=ws.id, host=host, status=DomainStatus.approved, basis=basis, requests_per_minute=rpm,
        reviewed_by_id=admin.id, reviewed_at=now - timedelta(days=days_ago), created_at=now - timedelta(days=days_ago),
    )
    db.add_all([
        approved(host_of(store_url), "Our own practice store, served by this Gleaner server.", 240, 40),
        approved("books.toscrape.com", sandbox, 60, 21),
        approved("quotes.toscrape.com", sandbox, 30, 21),
        approved("www.scrapethissite.com", "Sandbox site for learning web scraping. Its robots.txt disallows /lessons/ and /faq/, which the crawler skips.", 20, 14),
        Domain(workspace_id=ws.id, host="shop.example.com", status=DomainStatus.pending,
               basis="Client wants their own product feed monitored; waiting for their written permission.", requests_per_minute=20,
               created_at=now - timedelta(days=1)),
        Domain(workspace_id=ws.id, host="www.linkedin.com", status=DomainStatus.blocked, requests_per_minute=1,
               basis="Not allowed: the user agreement prohibits scraping, and profiles are personal data behind a login.",
               reviewed_by_id=admin.id, reviewed_at=now - timedelta(days=9), created_at=now - timedelta(days=9)),
    ])

    def scraper(name, description, urls, config, schedule, created_days_ago, by=editor, enabled=True):
        s = Scraper(workspace_id=ws.id, name=name, description=description, start_urls=urls,
                    config=ScraperConfig.model_validate(config).model_dump(), schedule_minutes=schedule, enabled=enabled,
                    created_by_id=by.id, created_at=now - timedelta(days=created_days_ago), updated_at=now - timedelta(days=created_days_ago))
        db.add(s)
        db.flush()
        return s

    store = scraper(
        "Ridgeline Outfitters: prices & stock",
        "Competitor price monitoring: every product's price, sale price, stock level and rating, plus SKU and weight from each product page.",
        [store_url], STORE_CONFIG, 360, HISTORY_DAYS + 1, by=admin,
    )
    books = scraper("Books to Scrape: catalogue", "Book titles, prices, star ratings and availability (first 10 pages).",
                    ["https://books.toscrape.com/"], BOOKS_CONFIG, 1440, 6)
    quotes = scraper("Quotes to Scrape: quotes & tags", "Quotes with their authors and tags.", ["https://quotes.toscrape.com/"], QUOTES_CONFIG, None, 5)
    quotes_js = scraper("Quotes (JavaScript edition)", "Same quotes, but this version of the site builds the page with JavaScript.",
                        ["https://quotes.toscrape.com/js/"], QUOTES_CONFIG | {"max_pages": 3}, None, 2)
    countries = scraper("Countries of the world", "Every country with its capital, population and area.",
                        ["https://www.scrapethissite.com/pages/simple/"], COUNTRIES_CONFIG, 10080, 4)
    hockey = scraper("NHL team stats", "Season results per team from a paginated, searchable table (first 5 pages).",
                     ["https://www.scrapethissite.com/pages/forms/?page_num=1"], HOCKEY_CONFIG, None, 3)

    rule = lambda s, name, kind, params=None, days=HISTORY_DAYS: AlertRule(  # noqa: E731
        workspace_id=ws.id, scraper_id=s.id, name=name, kind=kind, params=params or {}, created_at=now - timedelta(days=days))
    db.add_all([
        rule(store, "Price drops of 15% or more", "field_change", {"field": "price", "direction": "down", "min_percent": 15}),
        rule(store, "New products", "new_item"),
        rule(store, "Discontinued products", "item_removed"),
        rule(store, "Data-quality warnings", "anomaly"),
        rule(store, "Run failures", "run_failed"),
        rule(books, "Run failures", "run_failed", days=6),
        rule(quotes_js, "Run failures", "run_failed", days=2),
    ])
    db.add(ApiKey(workspace_id=ws.id, name="BI dashboard (read-only)", prefix="glk_" + secrets.token_urlsafe(4)[:6],
                  key_hash=hash_api_key(secrets.token_urlsafe(32)), created_by_id=admin.id, created_at=now - timedelta(days=12),
                  last_used_at=now - timedelta(hours=3)))
    db.add(Webhook(workspace_id=ws.id, url="https://hooks.example.com/gleaner/price-alerts", secret="whsec_" + secrets.token_hex(24),
                   events=["alert.fired"], enabled=False, created_at=now - timedelta(days=8)))
    db.commit()

    # 30 days of the practice store, one scheduled run per day.
    today = now.date()
    for offset in range(HISTORY_DAYS, 0, -1):
        day = today - timedelta(days=offset)
        fail = practice.CATALOG[7].slug if offset == 12 else None  # one day with a timed-out product page
        simulate_store_run(db, store, day, fail_detail=fail)
    # Next scheduled run a few minutes after startup, so the demo shows a live run with today's changes.
    store.next_run_at = now + timedelta(minutes=3)
    db.commit()
    print(f"Practice store: {HISTORY_DAYS} days of history.")

    if os.environ.get("SEED_LIVE", "1") != "0":
        live = [books, quotes, quotes_js, countries, hockey]
        ids = []
        for s in live:
            r = run_service.enqueue(db, s, trigger="manual", user_id=editor.id)
            ids.append(r.id)
        db.commit()
        print("Running live scrapes against the public practice sites (about a minute)...")
        try:
            asyncio.run(live_runs(ids))
        except Exception as e:  # noqa: BLE001
            print(f"Live runs failed ({e}); the scrapers are there, run them from the app.")
        db.expire_all()
        for s in live:
            s.next_run_at = run_service.next_run_time(s)
            r = db.query(Run).filter_by(scraper_id=s.id).order_by(Run.created_at.desc()).first()
            print(f"  {s.name}: {r.status.value}, {r.items_extracted} items" + (f" ({r.error})" if r.error else ""))
        db.commit()

    db.close()
    print(f"Done. Sign in as admin@meridian.demo / {DEMO_PASSWORD} (also aisha@ editor, tom@ viewer).")


if __name__ == "__main__":
    main()
