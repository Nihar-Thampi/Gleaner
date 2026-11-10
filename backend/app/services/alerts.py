"""Evaluate a scraper's alert rules against what a run found."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertEvent, AlertRule, ChangeKind, ItemChange, Run, RunStatus
from app.services.ingest import percent_change

ALERT_KINDS = {
    "field_change": "A field changes",
    "new_item": "A new item appears",
    "item_removed": "An item is removed",
    "run_failed": "A run fails",
    "anomaly": "A data-quality check flags something",
}
MAX_EVENTS_PER_RULE = 25  # per run; the rest are summarised in one event


def _label(change: ItemChange) -> str:
    data = change.item.data or {}
    for key in ("name", "title", "product", "text"):
        if data.get(key):
            return str(data[key])[:80]
    first = next((v for v in data.values() if isinstance(v, str) and v), None)
    return (first or change.item.key)[:80]


def _field_change_matches(rule: AlertRule, change: ItemChange) -> str | None:
    if change.kind != ChangeKind.changed:
        return None
    name = rule.params.get("field")
    if not name or name not in change.changes:
        return None
    old, new = change.changes[name]
    direction = rule.params.get("direction", "any")
    min_pct = float(rule.params.get("min_percent") or 0)
    pct = percent_change(old, new)
    if pct is None:
        return f"{name} changed for “{_label(change)}”: {old} → {new}" if direction == "any" and not min_pct else None
    if direction == "down" and pct >= 0 or direction == "up" and pct <= 0 or abs(pct) < min_pct:
        return None
    return f"{name} {'dropped' if pct < 0 else 'rose'} {abs(pct):.0f}% for “{_label(change)}”: {old} → {new}"


def _new_item_matches(rule: AlertRule, change: ItemChange) -> str | None:
    if change.kind not in (ChangeKind.new, ChangeKind.returned):
        return None
    name, needle = rule.params.get("field"), (rule.params.get("contains") or "").strip().lower()
    if name and needle and needle not in str(change.item.data.get(name, "")).lower():
        return None
    verb = "New" if change.kind == ChangeKind.new else "Back"
    return f"{verb}: “{_label(change)}”"


def evaluate(db: Session, run: Run, changes: list[ItemChange]) -> list[AlertEvent]:
    rules = db.scalars(select(AlertRule).where(AlertRule.scraper_id == run.scraper_id, AlertRule.enabled.is_(True))).all()
    events: list[AlertEvent] = []

    def fire(rule: AlertRule, message: str, item_id: str | None = None) -> None:
        events.append(AlertEvent(
            workspace_id=run.workspace_id, rule=rule, scraper_id=run.scraper_id, run_id=run.id, item_id=item_id, message=message,
        ))

    for rule in rules:
        if rule.kind == "run_failed":
            if run.status == RunStatus.failed:
                fire(rule, f"Run #{run.number} of {run.scraper.name} failed: {run.error or 'see the run log'}")
            continue
        if rule.kind == "anomaly":
            for a in run.anomalies or []:
                fire(rule, a["message"], a.get("item_id"))
            continue

        matches = []
        for c in changes:
            if rule.kind == "field_change":
                msg = _field_change_matches(rule, c)
            elif rule.kind == "new_item":
                msg = _new_item_matches(rule, c)
            elif rule.kind == "item_removed":
                msg = f"Removed: “{_label(c)}”" if c.kind == ChangeKind.removed else None
            else:
                msg = None
            if msg:
                matches.append((msg, c.item.id))
        for msg, item_id in matches[:MAX_EVENTS_PER_RULE]:
            fire(rule, msg, item_id)
        if len(matches) > MAX_EVENTS_PER_RULE:
            fire(rule, f"…and {len(matches) - MAX_EVENTS_PER_RULE} more matching “{rule.name}” in run #{run.number}.")

    db.add_all(events)
    return events
