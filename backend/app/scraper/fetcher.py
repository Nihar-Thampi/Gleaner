"""HTTP (and optional headless-browser) fetching with the compliance rules applied.

Every request, including each redirect hop, goes through `policy`: approved domain,
robots.txt, rate limit, no private addresses. Transient failures (timeouts, 429, 5xx) are
retried with exponential backoff and jitter, honouring Retry-After.
"""
import asyncio
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.models import Domain, DomainStatus, utcnow
from app.scraper import policy

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
# Tests point every fetch at the app itself (httpx.ASGITransport); None = the real network.
DEFAULT_TRANSPORT: httpx.AsyncBaseTransport | None = None
MAX_REDIRECTS = 5
MAX_RETRY_AFTER = 120.0


class Blocked(Exception):
    """The request was not sent because policy forbids it (not a network failure)."""


class FetchFailed(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Page:
    url: str  # final URL after redirects
    status: int
    html: str
    elapsed_ms: int
    size: int


@dataclass
class FetchStats:
    requests: int = 0
    retries: int = 0
    bytes: int = 0
    total_ms: int = 0
    status_codes: dict[str, int] = field(default_factory=dict)

    def record(self, status: int, size: int, ms: int) -> None:
        self.requests += 1
        self.bytes += size
        self.total_ms += ms
        self.status_codes[str(status)] = self.status_codes.get(str(status), 0) + 1


class _HostThrottle:
    """Spaces requests to one host. Shared by every run and preview in this process (the
    worker and the API each have their own event loop), so two scrapers on the same site
    can't double its traffic. Each caller reserves the next free slot, then sleeps until it."""

    _lock = threading.Lock()
    _next_slot: dict[str, float] = {}

    @classmethod
    async def wait(cls, host: str, interval: float) -> None:
        with cls._lock:
            now = time.monotonic()
            slot = max(now, cls._next_slot.get(host, 0.0))
            cls._next_slot[host] = slot + interval
        if slot > now:
            await asyncio.sleep(slot - now)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._next_slot.clear()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(value)))
    except ValueError:
        try:
            return min(MAX_RETRY_AFTER, max(0.0, (parsedate_to_datetime(value) - utcnow()).total_seconds()))
        except (TypeError, ValueError):
            return None


class Fetcher:
    def __init__(
        self,
        *,
        domains: dict[str, Domain],
        user_agent: str,
        on_robots: Callable[[Domain], None] | None = None,
        on_retry: Callable[[str, str], None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        check_network: bool = True,
    ):
        settings = get_settings()
        transport = transport or DEFAULT_TRANSPORT
        self.domains = domains
        self.user_agent = user_agent
        self.on_robots = on_robots or (lambda d: None)
        self.on_retry = on_retry or (lambda url, why: None)
        self.check_network = check_network and transport is None  # injected transports are test doubles
        self.stats = FetchStats()
        self.max_bytes = settings.max_response_bytes
        self.max_retries = settings.max_retries
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
            follow_redirects=False,  # each hop is checked against policy
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en",
            },
        )
        self._browser = None
        self._playwright = None
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()
        if self._browser is not None:
            await self._browser.close()
            await self._playwright.stop()

    # ---- policy ----

    async def _ensure_robots(self, domain: Domain, scheme: str) -> policy.Robots:
        lock = self._robots_locks.setdefault(domain.host, asyncio.Lock())
        async with lock:
            if policy.robots_is_stale(domain):
                url = f"{scheme}://{domain.host}/robots.txt"
                try:
                    for _ in range(MAX_REDIRECTS + 1):  # RFC 9309: follow up to five redirects
                        if self.check_network and (reason := await policy.check_network_target(url)):
                            raise httpx.ConnectError(reason)
                        r = await self._client.get(url)
                        if not (r.is_redirect and "location" in r.headers):
                            break
                        url = urljoin(url, r.headers["location"])
                    domain.robots_status = r.status_code
                    domain.robots_txt = r.text[:200_000] if r.status_code < 400 else None
                except httpx.HTTPError as e:
                    logger.info("robots.txt fetch failed for %s: %s", domain.host, e)
                    domain.robots_status, domain.robots_txt = None, None
                domain.robots_fetched_at = utcnow()
                domain.crawl_delay = policy.robots_from_domain(domain).crawl_delay
                self.on_robots(domain)
        return policy.robots_from_domain(domain)

    async def refresh_robots(self, domain: Domain, scheme: str = "https") -> policy.Robots:
        domain.robots_fetched_at = None
        return await self._ensure_robots(domain, scheme)

    async def check(self, url: str) -> Domain:
        """Raise Blocked if policy forbids fetching `url`; otherwise return its domain."""
        if reason := policy.check_url_shape(url):
            raise Blocked(reason)
        host = policy.host_of(url)
        domain = self.domains.get(host)
        if reason := policy.domain_block_reason(domain, host):
            raise Blocked(reason)
        if self.check_network and (reason := await policy.check_network_target(url)):
            raise Blocked(reason)
        robots = await self._ensure_robots(domain, urlsplit(url).scheme)
        if not robots.allows(url):
            raise Blocked(f"robots.txt disallows {urlsplit(url).path or '/'} for {policy.BOT_NAME}." if robots.status and robots.status < 400 else robots.summary)
        return domain

    # ---- fetching ----

    async def fetch(self, url: str, *, render: str = "static", wait_for: str | None = None) -> Page:
        if render == "browser":
            return await self._fetch_browser(url, wait_for)
        for _ in range(MAX_REDIRECTS + 1):
            domain = await self.check(url)
            response = await self._get_with_retries(url, domain)
            if response.is_redirect and "location" in response.headers:
                url = urljoin(url, response.headers["location"])
                continue
            return self._to_page(url, response)
        raise FetchFailed(f"Too many redirects starting from {url}")

    async def _get_with_retries(self, url: str, domain: Domain) -> httpx.Response:
        attempt = 0
        while True:
            await _HostThrottle.wait(domain.host, policy.min_interval_seconds(domain))
            start = time.perf_counter()
            try:
                response = await self._read_limited(url)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= self.max_retries:
                    raise FetchFailed(f"{type(e).__name__} after {attempt + 1} attempts") from None
                why = "timed out" if isinstance(e, httpx.TimeoutException) else "connection error"
                delay = self._backoff(attempt)
            else:
                ms = int((time.perf_counter() - start) * 1000)
                self.stats.record(response.status_code, len(response.content), ms)
                if response.status_code not in RETRY_STATUSES or attempt >= self.max_retries:
                    return response
                why = f"HTTP {response.status_code}"
                delay = _retry_after(response) or self._backoff(attempt)
            attempt += 1
            self.stats.retries += 1
            self.on_retry(url, f"{why}; retrying in {delay:.1f}s (attempt {attempt + 1})")
            await asyncio.sleep(delay)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 1.5 * 2**attempt) * random.uniform(0.75, 1.25)

    async def _read_limited(self, url: str) -> httpx.Response:
        async with self._client.stream("GET", url) as response:
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise FetchFailed(f"Response larger than {self.max_bytes // 1_000_000} MB; skipped.")
                chunks.append(chunk)
            response._content = b"".join(chunks)  # noqa: SLF001 - make .text available after the stream closes
            return response

    def _to_page(self, url: str, response: httpx.Response) -> Page:
        if response.status_code >= 400:
            raise FetchFailed(f"HTTP {response.status_code}", status=response.status_code)
        ctype = response.headers.get("content-type", "")
        if ctype and "html" not in ctype and "xml" not in ctype:
            raise FetchFailed(f"Not an HTML page ({ctype.split(';')[0]}).", status=response.status_code)
        return Page(url=url, status=response.status_code, html=response.text, elapsed_ms=0, size=len(response.content))

    # ---- headless browser ----

    async def _fetch_browser(self, url: str, wait_for: str | None) -> Page:
        if not get_settings().browser_enabled:
            raise FetchFailed("Browser rendering is turned off on this server (BROWSER_ENABLED=false).")
        domain = await self.check(url)
        page_host = policy.host_of(url)
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise FetchFailed("Browser rendering needs Playwright: pip install playwright && playwright install chromium") from None
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch()
        context = await self._browser.new_context(user_agent=self.user_agent)
        page = await context.new_page()

        async def guard(route):
            req = route.request
            if req.resource_type in ("image", "media", "font"):
                return await route.abort()  # not needed for the text, and saves the site bandwidth
            host = policy.host_of(req.url)
            allowed = host == page_host or (self.domains.get(host) and self.domains[host].status == DomainStatus.approved)
            await (route.continue_() if allowed else route.abort())

        await page.route("**/*", guard)
        try:
            await _HostThrottle.wait(domain.host, policy.min_interval_seconds(domain))
            start = time.perf_counter()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=get_settings().request_timeout_seconds * 1000)
            try:
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=10_000)
                else:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:  # noqa: BLE001 - a timeout here isn't fatal; extraction reports missing items
                pass
            html = await page.content()
            status = response.status if response else 200
            ms = int((time.perf_counter() - start) * 1000)
            self.stats.record(status, len(html.encode()), ms)
            if status >= 400:
                raise FetchFailed(f"HTTP {status}", status=status)
            return Page(url=page.url, status=status, html=html, elapsed_ms=ms, size=len(html.encode()))
        finally:
            await context.close()
