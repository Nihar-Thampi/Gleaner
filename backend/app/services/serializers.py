"""Response shapes."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AIRequest, AlertEvent, AlertRule, ApiKey, Domain, Item, ItemChange, Run, RunStatus, Scraper, User, Webhook,
    WebhookDelivery, Workspace,
)
from app.scraper.config import ScraperConfig
from app.scraper.policy import host_of, robots_from_domain


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role.value, "is_active": u.is_active, "created_at": u.created_at}


def workspace_out(w: Workspace) -> dict:
    return {"id": w.id, "name": w.name, "contact_email": w.contact_email, "ai_run_summaries": w.ai_run_summaries}


def domain_out(d: Domain, scraper_count: int = 0, *, with_robots: bool = False) -> dict:
    out = {
        "id": d.id, "host": d.host, "status": d.status.value, "basis": d.basis, "requests_per_minute": d.requests_per_minute,
        "reviewed_by": d.reviewed_by.full_name if d.reviewed_by else None, "reviewed_at": d.reviewed_at,
        "robots_status": d.robots_status, "robots_fetched_at": d.robots_fetched_at, "crawl_delay": d.crawl_delay,
        "robots_summary": robots_from_domain(d).summary if d.robots_fetched_at else "Not fetched yet.",
        "scraper_count": scraper_count, "created_at": d.created_at,
    }
    if with_robots:
        out["robots_txt"] = d.robots_txt
    return out


def run_brief(r: Run) -> dict:
    return {
        "id": r.id, "number": r.number, "scraper_id": r.scraper_id, "scraper_name": r.scraper.name, "status": r.status.value,
        "trigger": r.trigger, "triggered_by": r.triggered_by.full_name if r.triggered_by else None,
        "created_at": r.created_at, "started_at": r.started_at, "finished_at": r.finished_at, "duration_ms": r.duration_ms,
        "items_extracted": r.items_extracted, "items_new": r.items_new, "items_changed": r.items_changed,
        "items_removed": r.items_removed, "items_invalid": r.items_invalid,
        "pages_fetched": r.pages_fetched, "pages_failed": r.pages_failed, "requests_blocked": r.requests_blocked,
        "anomaly_count": len(r.anomalies or []), "error": r.error, "cancel_requested": r.cancel_requested,
        "headline": (r.ai_summary or {}).get("headline"),
    }


def run_out(r: Run) -> dict:
    fetched = sum((r.status_codes or {}).values())
    return {
        **run_brief(r),
        "items_unchanged": r.items_unchanged, "retries": r.retries, "bytes_downloaded": r.bytes_downloaded,
        "avg_response_ms": int(r.total_response_ms / fetched) if fetched else None,
        "status_codes": r.status_codes or {}, "quality": r.quality, "anomalies": r.anomalies or [],
        "ai_summary": r.ai_summary, "config": r.config_snapshot,
    }


def health(last: Run | None) -> str:
    if last is None:
        return "never_run"
    if last.status in (RunStatus.queued, RunStatus.running):
        return "running"
    if last.status == RunStatus.failed:
        return "failing"
    if last.status == RunStatus.partial or last.anomalies:
        return "warning"
    return "healthy"


def scraper_out(db: Session, s: Scraper, *, detail: bool = False) -> dict:
    last = db.scalar(select(Run).where(Run.scraper_id == s.id).order_by(Run.created_at.desc()).limit(1))
    last_done = last if last is None or last.status not in (RunStatus.queued, RunStatus.running) else db.scalar(
        select(Run).where(Run.scraper_id == s.id, Run.status.not_in([RunStatus.queued, RunStatus.running]))
        .order_by(Run.created_at.desc()).limit(1)
    )
    items = db.scalar(select(func.count()).select_from(Item).where(Item.scraper_id == s.id, Item.removed_at.is_(None))) or 0
    hosts = sorted({host_of(u) for u in s.start_urls})
    domains = {d.host: d.status.value for d in db.scalars(select(Domain).where(Domain.workspace_id == s.workspace_id, Domain.host.in_(hosts)))}
    out = {
        "id": s.id, "name": s.name, "description": s.description, "start_urls": s.start_urls, "hosts": hosts,
        "domain_status": {h: domains.get(h, "unknown") for h in hosts},
        "schedule_minutes": s.schedule_minutes, "enabled": s.enabled, "next_run_at": s.next_run_at,
        "created_at": s.created_at, "updated_at": s.updated_at, "item_count": items,
        "field_count": len(s.config.get("fields", [])), "render": s.config.get("render", "static"),
        "last_run": run_brief(last) if last else None,
        "health": "running" if last and last.status in (RunStatus.queued, RunStatus.running) else health(last_done),
    }
    if detail:
        out["config"] = s.config
    return out


def item_label(data: dict, config: ScraperConfig | dict | None) -> str:
    fields = config.fields if isinstance(config, ScraperConfig) else (config or {}).get("fields", [])
    for f in fields:
        name = f.name if hasattr(f, "name") else f["name"]
        v = data.get(name)
        if isinstance(v, str) and v and not v.startswith("http"):
            return v[:120]
    return next((str(v)[:120] for v in data.values() if v not in (None, "", [])), "(empty)")


def item_out(i: Item) -> dict:
    return {
        "id": i.id, "key": i.key, "data": i.data, "source_url": i.source_url, "version": i.version,
        "first_seen_at": i.first_seen_at, "last_seen_at": i.last_seen_at, "last_changed_at": i.last_changed_at,
        "removed_at": i.removed_at,
    }


def change_out(c: ItemChange, scraper: Scraper | None = None) -> dict:
    out = {
        "id": c.id, "kind": c.kind.value, "changes": c.changes, "at": c.at, "run_id": c.run_id, "scraper_id": c.scraper_id,
        "item": {"id": c.item.id, "key": c.item.key, "label": item_label(c.item.data, scraper.config if scraper else None),
                 "removed": c.item.removed_at is not None, "source_url": c.item.source_url},
    }
    if scraper:
        out["scraper_name"] = scraper.name
    return out


def rule_out(r: AlertRule, fired_7d: int = 0) -> dict:
    return {"id": r.id, "scraper_id": r.scraper_id, "scraper_name": r.scraper.name, "name": r.name, "kind": r.kind,
            "params": r.params, "enabled": r.enabled, "created_at": r.created_at, "fired_7d": fired_7d}


def event_out(e: AlertEvent) -> dict:
    return {"id": e.id, "rule_id": e.rule_id, "rule_name": e.rule.name, "kind": e.rule.kind, "scraper_id": e.scraper_id,
            "scraper_name": e.rule.scraper.name, "run_id": e.run_id, "item_id": e.item_id, "message": e.message,
            "at": e.at, "read": e.read}


def webhook_out(w: Webhook, last: WebhookDelivery | None = None) -> dict:
    return {"id": w.id, "url": w.url, "events": w.events, "enabled": w.enabled, "created_at": w.created_at,
            "secret_hint": w.secret[:6] + "…",
            "last_delivery": delivery_out(last) if last else None}


def delivery_out(d: WebhookDelivery) -> dict:
    return {"id": d.id, "event": d.event, "status_code": d.status_code, "ok": d.ok, "error": d.error,
            "duration_ms": d.duration_ms, "at": d.at}


def api_key_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "can_trigger_runs": k.can_trigger_runs,
            "created_at": k.created_at, "last_used_at": k.last_used_at, "revoked_at": k.revoked_at}


def ai_request_out(r: AIRequest, full: bool = False) -> dict:
    out = {"id": r.id, "feature": r.feature, "provider": r.provider, "model": r.model, "success": r.success, "error": r.error,
           "latency_ms": r.latency_ms, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
           "created_at": r.created_at, "user_name": r.user.full_name if r.user else None,
           "input_preview": r.input_text[:200]}
    if full:
        out.update(input_text=r.input_text, output_text=r.output_text)
    return out
