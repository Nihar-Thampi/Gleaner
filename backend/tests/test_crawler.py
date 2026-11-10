"""The crawl pipeline end to end, against the practice store served by the app itself."""
import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.scraper import policy
from app.scraper.config import ScraperConfig
from app.scraper.extract import Row, extract_list_page, parse_number
from app.services.webhooks import deliver
from tests.conftest import ADMIN, EDITOR

STORE = "http://testserver/practice/store"


@pytest.mark.parametrize("text,expected", [
    ("£1,299.00", 1299.0), ("1.299,00 €", 1299.0), ("12,50", 12.5), ("Only 3 left", 3.0),
    ("-3.5%", -3.5), ("R 15 000", 15000.0), ("no digits", None),
])
def test_number_parsing(text, expected):
    assert parse_number(text) == expected


def test_extraction_types_regex_and_value_map():
    html = """<ul><li class="p"><a href="/x/1" title="Full Name">Full…</a><span class="cost">£12.50</span>
    <p class="star-rating Four"></p><p class="avail">In stock</p><a class="tag">a</a><a class="tag">b</a></li></ul>"""
    config = ScraperConfig.model_validate({
        "item_selector": "li.p",
        "fields": [
            {"name": "name", "selector": "a", "attr": "title"},
            {"name": "url", "selector": "a", "attr": "href", "type": "url"},
            {"name": "price", "selector": "span.cost", "type": "price"},
            {"name": "rating", "selector": "p.star-rating", "attr": "class", "type": "integer",
             "regex": r"\b(One|Two|Three|Four|Five)\b", "value_map": {"Four": 4}},
            {"name": "in_stock", "selector": "p.avail", "type": "boolean", "regex": "in stock"},
            {"name": "tags", "selector": "a.tag", "multiple": True},
        ],
    })
    row = extract_list_page(html, "https://shop.test/list", config).rows[0]
    assert row.data == {"name": "Full Name", "url": "https://shop.test/x/1", "price": 12.5, "rating": 4,
                        "in_stock": True, "tags": ["a", "b"]}


def test_store_run_detects_todays_changes(client, h, run_now, scraper_id):
    """The seed stops at yesterday; today's store has moved prices and stock."""
    run = run_now(scraper_id("Ridgeline"))
    assert run["status"] == "succeeded", run
    assert run["items_extracted"] >= 50
    assert run["pages_fetched"] > run["items_extracted"]  # listing pages + one detail page per product
    assert run["items_changed"] > 0
    assert run["quality"]["fill_rates"]["sku"] == 1.0  # detail-page fields filled
    changes = client.get(f"/api/scrapers/{run['scraper_id']}/changes", headers=h(), params={"run_id": run["id"]}).json()
    assert changes["total"] == run["items_changed"] + run["items_new"] + run["items_removed"]
    assert run["ai_summary"]["headline"]


def test_first_run_is_a_baseline(client, h, run_now):
    body = {"name": "Store, tents only", "start_urls": [STORE + "?category=Tents"],
            "config": {"item_selector": "article.product-card", "key_fields": ["url"], "fields": [
                {"name": "url", "selector": "h2 a", "attr": "href", "type": "url", "required": True},
                {"name": "price", "selector": "span.price-now", "type": "price"}]}}
    sid = client.post("/api/scrapers", headers=h(EDITOR), json=body).json()["id"]
    run = run_now(sid)
    assert run["status"] == "succeeded" and run["items_new"] == run["items_extracted"] > 0
    assert client.get(f"/api/scrapers/{sid}/changes", headers=h()).json()["total"] == 0
    # Second run: same day, nothing changed.
    again = run_now(sid)
    assert again["items_new"] == again["items_changed"] == again["items_removed"] == 0


def test_broken_selector_fails_the_run_and_alerts(client, h, run_now):
    body = {"name": "Broken on purpose", "start_urls": [STORE],
            "config": {"item_selector": "article.product-tile", "fields": [{"name": "name", "selector": "h2"}]}}
    sid = client.post("/api/scrapers", headers=h(EDITOR), json=body).json()["id"]
    client.post(f"/api/scrapers/{sid}/alert-rules", headers=h(EDITOR), json={"name": "Failures", "kind": "run_failed"})
    run = run_now(sid)
    assert run["status"] == "failed"
    assert run["anomalies"][0]["kind"] == "selector_broken"
    alerts = client.get("/api/alerts", headers=h(), params={"scraper_id": sid}).json()["items"]
    assert alerts and "failed" in alerts[0]["message"]
    # AI repair (offline rules here) finds the real product cards again.
    fix = client.post(f"/api/ai/repair/{sid}", headers=h(EDITOR)).json()
    assert fix["config"]["item_selector"] == "article.product-card"
    assert fix["fill_rates"]["name"] == 1.0


def test_robots_txt_is_obeyed(client, h, run_now):
    body = {"name": "Basket (disallowed)", "start_urls": [STORE + "/cart"],
            "config": {"fields": [{"name": "title", "selector": "h1"}]}}
    sid = client.post("/api/scrapers", headers=h(EDITOR), json=body).json()["id"]
    run = run_now(sid)
    assert run["status"] == "failed" and run["requests_blocked"] == 1 and run["pages_fetched"] == 0
    assert "robots.txt disallows" in run["error"]
    check = client.post("/api/domains/check", headers=h(), json={"url": STORE + "/account"}).json()
    assert check["allowed"] is False


def test_unapproved_domains_are_never_fetched(client, h):
    r = client.post("/api/scrapers/preview", headers=h(EDITOR), json={
        "url": "https://shop.example.com/products", "config": {"fields": [{"name": "t", "selector": "h1"}]}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "domain_not_approved"
    blocked = client.post("/api/domains/check", headers=h(), json={"url": "https://www.linkedin.com/in/someone"}).json()
    assert blocked["allowed"] is False and "blocked" in blocked["reason"]


def test_private_addresses_are_refused():
    for url in ("http://10.0.0.5/", "http://169.254.169.254/latest/meta-data/", "http://[::1]:8080/"):
        assert asyncio.run(policy.check_network_target(url)), url


def test_robots_rules():
    robots = policy.Robots(200, "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n", None)
    assert robots.allows("https://a.test/public") and not robots.allows("https://a.test/private/x")
    assert robots.crawl_delay == 2.0
    assert policy.Robots(404, None, None).allows("https://a.test/anything")  # no robots.txt = allowed
    assert not policy.Robots(503, None, None).allows("https://a.test/")  # unreachable = disallowed


def test_ai_suggest_builds_a_working_config(client, h):
    r = client.post("/api/ai/suggest", headers=h(EDITOR), json={"url": STORE, "fields": "product name, price, stock, link, rating"})
    body = r.json()
    assert r.status_code == 200, body
    assert body["item_count"] == 12 and body["config"]["item_selector"] == "article.product-card"
    assert all(rate == 1.0 for rate in body["fill_rates"].values()), body["fill_rates"]
    assert body["config"]["next_page_selector"]
    assert isinstance(body["rows"][0]["price"], float)


def test_webhooks_are_signed():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = request.headers, request.content
        return httpx.Response(200)

    from app.models import Webhook

    hook = Webhook(id="w1", url="https://receiver.test/hook", secret="s3cret", events=["run.finished"])
    delivery = asyncio.run(deliver(hook, "run.finished", {"id": "r1"}, transport=httpx.MockTransport(handler)))
    assert delivery.ok and delivery.status_code == 200
    ts = seen["headers"]["x-gleaner-timestamp"]
    expected = "sha256=" + hmac.new(b"s3cret", ts.encode() + b"." + seen["body"], hashlib.sha256).hexdigest()
    assert seen["headers"]["x-gleaner-signature"] == expected
    assert json.loads(seen["body"])["data"] == {"id": "r1"}


def test_removals_need_a_complete_run(client, h):
    """An incomplete run (e.g. a failed page) must not mark unseen items as removed."""
    from app.db import SessionLocal
    from app.models import Item, Run, Scraper
    from app.services import runs as run_service
    from app.services.ingest import ingest
    from app.models import utcnow

    with SessionLocal() as db:
        scraper = db.query(Scraper).filter(Scraper.name.startswith("Ridgeline")).one()
        tracked = db.query(Item).filter_by(scraper_id=scraper.id, removed_at=None).count()
        run = run_service.enqueue(db, scraper, trigger="manual")
        result = ingest(db, scraper, run, [Row(data={}, source_url="x")], complete=False, now=utcnow())
        assert result.removed == 0
        db.rollback()
        assert db.query(Item).filter_by(scraper_id=scraper.id, removed_at=None).count() == tracked
        assert db.query(Run).filter_by(id=run.id).count() == 0
