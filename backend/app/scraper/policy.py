"""Compliance rules every request goes through before it is sent.

1. The host must be a domain an admin approved for this workspace.
2. robots.txt must allow the URL for our user agent (RFC 9309): a missing robots.txt
   (4xx) allows everything; one that can't be fetched (5xx, network error) blocks
   everything until it can be read.
3. Requests are spaced by the domain's rate limit or its Crawl-delay, whichever is slower.
4. No private, loopback or link-local addresses (SSRF protection), except hosts listed in
   ALLOWED_PRIVATE_HOSTS.
"""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.core.config import get_settings
from app.models import Domain, DomainStatus, Workspace, utcnow

BOT_NAME = "GleanerBot"
ROBOTS_MAX_AGE = timedelta(hours=24)


def user_agent(workspace: Workspace) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"Mozilla/5.0 (compatible; {BOT_NAME}/1.0; +{base}/bot; contact: {workspace.contact_email})"


def host_of(url: str) -> str:
    """Host as stored on Domain: lowercase, with the port only when it isn't the default."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (parts.scheme == "http" and port == 80 or parts.scheme == "https" and port == 443):
        return f"{host}:{port}"
    return host


def check_url_shape(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "Only http and https URLs can be fetched."
    if not parts.hostname:
        return "That URL has no host."
    if parts.username or parts.password:
        return "URLs with embedded credentials aren't allowed."
    return None


def _is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


async def check_network_target(url: str) -> str | None:
    """Refuse URLs that resolve to internal addresses. Returns a reason, or None if fine."""
    hostname = urlsplit(url).hostname or ""
    if hostname in get_settings().allowed_private_hosts:
        return None
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Couldn't resolve {hostname}."
    if any(_is_private(info[4][0]) for info in infos):
        return f"{hostname} resolves to a private network address, which the crawler never fetches."
    return None


@dataclass
class Robots:
    status: int | None  # HTTP status of robots.txt, or None if it couldn't be fetched
    text: str | None
    fetched_at: datetime | None

    @property
    def parser(self) -> RobotFileParser:
        rp = RobotFileParser()
        if self.status is None or self.status >= 500:
            rp.disallow_all = True
        elif self.status >= 400:
            rp.allow_all = True
        else:
            rp.parse((self.text or "").splitlines())
        return rp

    def allows(self, url: str) -> bool:
        return self.parser.can_fetch(BOT_NAME, url)

    @property
    def crawl_delay(self) -> float | None:
        if self.status is None or self.status >= 400:
            return None
        delay = self.parser.crawl_delay(BOT_NAME)
        return float(delay) if delay is not None else None

    @property
    def summary(self) -> str:
        if self.status is None:
            return "robots.txt couldn't be fetched, so nothing is crawled until it can be."
        if self.status >= 500:
            return f"robots.txt returned {self.status}; everything is treated as disallowed until it recovers."
        if self.status >= 400:
            return f"No robots.txt (HTTP {self.status}); all paths are allowed."
        return "robots.txt found and applied."


def robots_from_domain(domain: Domain) -> Robots:
    return Robots(domain.robots_status, domain.robots_txt, domain.robots_fetched_at)


def robots_is_stale(domain: Domain) -> bool:
    return domain.robots_fetched_at is None or utcnow() - domain.robots_fetched_at > ROBOTS_MAX_AGE


def domain_block_reason(domain: Domain | None, host: str) -> str | None:
    if domain is None:
        return f"{host} isn't an approved domain. Ask an admin to review it under Domains."
    if domain.status == DomainStatus.pending:
        return f"{host} is waiting for an admin to approve it."
    if domain.status == DomainStatus.blocked:
        return f"{host} is blocked for this workspace."
    return None


def min_interval_seconds(domain: Domain) -> float:
    """Seconds between two requests to this domain."""
    rate = 60.0 / max(1, domain.requests_per_minute)
    return max(rate, domain.crawl_delay or 0.0)
