import asyncio
import os
import tempfile

import pytest

# Point the app at a throwaway database before anything imports it. The crawler fetches
# from the app itself (the practice store) through an in-process transport, so tests
# need no network.
_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["AI_PROVIDER"] = "demo"
os.environ["RUN_WORKER"] = "false"
os.environ["SEED_LIVE"] = "0"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["BROWSER_ENABLED"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import seed  # noqa: E402
from app.main import app  # noqa: E402
from app.scraper import fetcher, policy  # noqa: E402

PASSWORD = seed.DEMO_PASSWORD
ADMIN, EDITOR, VIEWER = "admin@meridian.demo", "aisha@meridian.demo", "tom@meridian.demo"


@pytest.fixture(scope="session", autouse=True)
def demo_data():
    seed.main()


@pytest.fixture(scope="session", autouse=True)
def in_process_web():
    fetcher.DEFAULT_TRANSPORT = httpx.ASGITransport(app=app)
    original = policy.min_interval_seconds
    policy.min_interval_seconds = lambda domain: 0.0  # no politeness delay against ourselves
    yield
    fetcher.DEFAULT_TRANSPORT = None
    policy.min_interval_seconds = original


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def login(client):
    cache = {}

    def _login(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            body = r.json()
            cache[email] = {"headers": {"Authorization": f"Bearer {body['token']}"}, **body}
        return cache[email]

    return _login


@pytest.fixture
def h(login):
    return lambda email=ADMIN: login(email)["headers"]


@pytest.fixture
def run_now(client, h):
    """Queue a run through the API and execute it in-process (the worker is off in tests)."""
    from app.scraper.engine import execute_run

    def _run(scraper_id: str) -> dict:
        r = client.post(f"/api/scrapers/{scraper_id}/runs", headers=h())
        assert r.status_code == 201, r.text
        asyncio.run(execute_run(r.json()["id"]))
        return client.get(f"/api/runs/{r.json()['id']}", headers=h()).json()

    return _run


@pytest.fixture
def scraper_id(client, h):
    def _find(prefix: str) -> str:
        return next(s["id"] for s in client.get("/api/scrapers", headers=h()).json() if s["name"].startswith(prefix))

    return _find
