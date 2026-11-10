"""Signed webhook delivery.

Each POST carries `X-Gleaner-Timestamp` and `X-Gleaner-Signature: sha256=<hex>`, the
HMAC-SHA256 of "<timestamp>.<body>" with the webhook's secret. Receivers recompute it
to confirm the call came from this workspace and wasn't replayed later.
"""
import hashlib
import hmac
import json
import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Webhook, WebhookDelivery
from app.scraper.policy import check_network_target, check_url_shape

logger = logging.getLogger(__name__)

EVENTS = {"run.finished": "A run finishes (any outcome)", "alert.fired": "An alert rule fires"}
TIMEOUT = 10.0


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def _request(hook: Webhook, event: str, data: dict) -> tuple[bytes, dict]:
    body = json.dumps({"event": event, "sent_at": int(time.time()), "data": data}, default=str).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Gleaner-Webhooks/1.0",
        "X-Gleaner-Event": event,
        "X-Gleaner-Timestamp": ts,
        "X-Gleaner-Signature": sign(hook.secret, ts, body),
    }
    return body, headers


async def deliver(hook: Webhook, event: str, data: dict, transport: httpx.AsyncBaseTransport | None = None) -> WebhookDelivery:
    start = time.perf_counter()
    status, error = None, None
    try:
        if transport is None and (reason := check_url_shape(hook.url) or await check_network_target(hook.url)):
            raise ValueError(reason)
        body, headers = _request(hook, event, data)
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            r = await client.post(hook.url, content=body, headers=headers)
        status = r.status_code
        if r.status_code >= 300:
            error = f"Receiver answered HTTP {r.status_code}"
    except (httpx.HTTPError, ValueError) as e:
        error = str(e) or type(e).__name__
        logger.info("Webhook %s delivery failed: %s", hook.id, error)
    return WebhookDelivery(
        webhook_id=hook.id, event=event, status_code=status, ok=error is None, error=error,
        duration_ms=int((time.perf_counter() - start) * 1000),
    )


async def dispatch(db: Session, workspace_id: str, event: str, data: dict, transport=None) -> list[WebhookDelivery]:
    hooks = db.scalars(select(Webhook).where(Webhook.workspace_id == workspace_id, Webhook.enabled.is_(True))).all()
    deliveries = [await deliver(h, event, data, transport) for h in hooks if event in h.events]
    db.add_all(deliveries)
    return deliveries
