"""Roles, data access, exports and the API-key data API."""
import io

from openpyxl import load_workbook

from tests.conftest import ADMIN, EDITOR, VIEWER


def test_login_and_me(client, login):
    me = client.get("/api/auth/me", headers=login(VIEWER)["headers"]).json()
    assert me["user"]["role"] == "viewer" and me["workspace"]["name"] == "Meridian Market Intelligence"
    assert client.post("/api/auth/login", json={"email": ADMIN, "password": "wrong"}).status_code == 401


def test_viewers_read_but_cannot_change_anything(client, h, scraper_id):
    sid = scraper_id("Ridgeline")
    assert client.get(f"/api/scrapers/{sid}/items", headers=h(VIEWER)).status_code == 200
    assert client.post(f"/api/scrapers/{sid}/runs", headers=h(VIEWER)).status_code == 403
    assert client.patch(f"/api/scrapers/{sid}", headers=h(VIEWER), json={"enabled": False}).status_code == 403
    assert client.get("/api/users", headers=h(VIEWER)).status_code == 403


def test_only_admins_approve_domains(client, h):
    r = client.post("/api/domains", headers=h(EDITOR), json={"url": "news.example.org", "approve": True, "basis": "x"})
    assert r.status_code == 403
    r = client.post("/api/domains", headers=h(EDITOR), json={"url": "news.example.org", "basis": "Client's own site"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    domain_id = r.json()["id"]
    assert client.patch(f"/api/domains/{domain_id}", headers=h(EDITOR), json={"status": "approved"}).status_code == 403
    approved = client.patch(f"/api/domains/{domain_id}", headers=h(ADMIN), json={"status": "approved"}).json()
    assert approved["status"] == "approved" and approved["reviewed_by"] == "Jordan Lee"


def test_approval_needs_a_recorded_basis(client, h):
    r = client.post("/api/domains", headers=h(ADMIN), json={"url": "https://data.example.net", "approve": True})
    assert r.status_code == 400


def test_invalid_selectors_are_rejected(client, h):
    r = client.post("/api/scrapers", headers=h(EDITOR), json={
        "name": "Bad", "start_urls": ["https://books.toscrape.com/"],
        "config": {"item_selector": "div[[", "fields": [{"name": "Title!", "selector": "h3"}]}})
    assert r.status_code == 422
    messages = " ".join(e["msg"] for e in r.json()["detail"])
    assert "Invalid CSS selector" in messages and "lowercase" in messages


def test_items_search_sort_and_history(client, h, scraper_id):
    sid = scraper_id("Ridgeline")
    page = client.get(f"/api/scrapers/{sid}/items", headers=h(), params={"sort": "-price", "limit": 5}).json()
    prices = [i["data"]["price"] for i in page["items"]]
    assert prices == sorted(prices, reverse=True) and page["total"] >= 50
    found = client.get(f"/api/scrapers/{sid}/items", headers=h(), params={"q": "tent"}).json()
    assert found["total"] >= 3 and all("tent" in str(i["data"]).lower() for i in found["items"])
    changed = client.get(f"/api/scrapers/{sid}/changes", headers=h(), params={"kind": "changed", "limit": 1}).json()["items"][0]
    detail = client.get(f"/api/scrapers/{sid}/items/{changed['item']['id']}", headers=h()).json()
    assert detail["history"] and detail["series"]
    removed = client.get(f"/api/scrapers/{sid}/items", headers=h(), params={"only_removed": True}).json()
    assert removed["total"] >= 1  # discontinued products stay queryable


def test_exports(client, h, scraper_id):
    sid = scraper_id("Ridgeline")
    csv = client.get(f"/api/scrapers/{sid}/export", headers=h(VIEWER), params={"format": "csv"})
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("name,url,brand,price")
    data = client.get(f"/api/scrapers/{sid}/export", headers=h(VIEWER), params={"format": "json"}).json()
    assert data and "price" in data[0]
    xlsx = client.get(f"/api/scrapers/{sid}/export", headers=h(VIEWER), params={"format": "xlsx"})
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert sheet.max_row == len(data) + 1


def test_api_keys(client, h, scraper_id):
    created = client.post("/api/api-keys", headers=h(ADMIN), json={"name": "Warehouse sync"}).json()
    key = {"X-API-Key": created["key"]}
    sid = scraper_id("Ridgeline")
    assert any(s["id"] == sid for s in client.get("/api/v1/scrapers", headers=key).json())
    items = client.get(f"/api/v1/scrapers/{sid}/items", headers=key, params={"limit": 3}).json()
    assert len(items["items"]) == 3
    assert client.post(f"/api/v1/scrapers/{sid}/runs", headers=key).status_code == 403  # read-only key
    client.post(f"/api/api-keys/{created['id']}/revoke", headers=h(ADMIN))
    assert client.get("/api/v1/scrapers", headers=key).status_code == 401
    # Keys are workspace-scoped and stored hashed: the listing never shows the key again.
    listed = client.get("/api/api-keys", headers=h(ADMIN)).json()
    assert all("key" not in k for k in listed)


def test_cancel_a_queued_run(client, h, scraper_id):
    sid = scraper_id("Countries")
    run = client.post(f"/api/scrapers/{sid}/runs", headers=h(EDITOR)).json()
    assert client.post(f"/api/scrapers/{sid}/runs", headers=h(EDITOR)).status_code == 409  # one at a time
    cancelled = client.post(f"/api/runs/{run['id']}/cancel", headers=h(EDITOR)).json()
    assert cancelled["status"] == "cancelled"


def test_dashboard(client, h):
    d = client.get("/api/dashboard", headers=h(VIEWER)).json()
    assert d["kpis"]["items_tracked"] > 0 and len(d["changes_by_day"]) == 14
    assert any(day["changed"] for day in d["changes_by_day"])


def test_ai_activity_is_admin_only(client, h):
    assert client.get("/api/ai/requests", headers=h(EDITOR)).status_code == 403
    log = client.get("/api/ai/requests", headers=h(ADMIN)).json()
    assert log["stats"]["requests"] >= 0


# ---- Local LLM client ----

import pytest  # noqa: E402

from app.ai import client as ai_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import AIRequest, Workspace  # noqa: E402


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_local_model_call_sends_schema_and_context(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, body=json)
        return _FakeResponse({"message": {"content": '{"answer": "yes"}'}, "done_reason": "stop",
                              "prompt_eval_count": 12, "eval_count": 5})

    monkeypatch.setattr(ai_client.httpx, "post", fake_post)
    schema = ai_client.obj({"answer": ai_client.STR})
    data, tokens_in, tokens_out = ai_client._call_local("system", "prompt", schema, 500)
    settings = ai_client.get_settings()
    assert data == {"answer": "yes"} and (tokens_in, tokens_out) == (12, 5)
    assert sent["url"].endswith("/api/chat")
    assert sent["body"]["format"] == schema and sent["body"]["model"] == settings.local_llm_model
    assert sent["body"]["options"]["num_ctx"] == settings.local_llm_context


def test_cut_off_answer_is_an_error(monkeypatch):
    monkeypatch.setattr(ai_client.httpx, "post", lambda *a, **k: _FakeResponse(
        {"message": {"content": '{"answer": "ye'}, "done_reason": "length"}))
    with pytest.raises(ai_client.AIError):
        ai_client._call_local("system", "prompt", {}, 500)


def test_local_model_failure_falls_back_to_rules_and_is_logged(monkeypatch):
    monkeypatch.setattr(ai_client.get_settings(), "ai_provider", "local")

    def boom(*args, **kwargs):
        raise ai_client.AIError("simulated outage")

    monkeypatch.setattr(ai_client, "_call_local", boom)
    with SessionLocal() as db:
        workspace_id = db.query(Workspace).first().id
        result = ai_client.run_json(
            db=db, workspace_id=workspace_id, user_id=None, feature="fallback-test", system="s", prompt="p",
            schema={}, demo=lambda: {"ok": True},
        )
        db.commit()
        assert result.provider == "demo-fallback" and result.data == {"ok": True}
        row = db.query(AIRequest).filter_by(feature="fallback-test").one()
        assert row.success is False and "simulated outage" in row.error


def test_auto_mode_uses_rules_when_no_local_model(monkeypatch):
    settings = ai_client.get_settings()
    monkeypatch.setattr(settings, "ai_provider", "auto")
    monkeypatch.setattr(ai_client, "local_model_available", lambda: (False, "not running"))
    assert ai_client.provider_status() == ("demo", ai_client.DEMO_MODEL)
    monkeypatch.setattr(ai_client, "local_model_available", lambda: (True, ""))
    assert ai_client.provider_status() == ("local", settings.local_llm_model)
