"""AI run summary: what changed in a run, in plain English, and what deserves a look."""
import json

from sqlalchemy.orm import Session

from app.ai.client import STR_LIST, AIResult, obj, run_json
from app.models import ChangeKind, ItemChange, Run
from app.scraper.config import ScraperConfig
from app.services.ingest import numeric_fields, percent_change

SCHEMA = obj({"headline": {"type": "string"}, "highlights": STR_LIST, "watch": STR_LIST})

SYSTEM = """You summarise what a web-scraping run found, for a busy analyst. Be specific: name \
items and give numbers. Use the currency or units present in the data.

- headline: one sentence, the most important thing about this run.
- highlights: up to 5 short bullets on notable changes (biggest moves, new or removed items, patterns \
across items such as a whole category going on sale).
- watch: up to 3 short bullets on anything that looks wrong or needs attention (data-quality flags, \
implausible values, failed pages). Empty if nothing does.

Only state what the data shows. Don't speculate about causes."""

MAX_CHANGES_IN_PROMPT = 60


def _label(change: ItemChange, config: ScraperConfig) -> str:
    data = change.item.data or {}
    return str(data.get(config.fields[0].name) or change.item.key)[:80]


def _demo(run: Run, changes: list[ItemChange], config: ScraperConfig) -> dict:
    counts = {k: sum(1 for c in changes if c.kind == k) for k in ChangeKind}
    parts = []
    if counts[ChangeKind.changed]:
        parts.append(f"{counts[ChangeKind.changed]} changed")
    if counts[ChangeKind.new]:
        parts.append(f"{counts[ChangeKind.new]} new")
    if counts[ChangeKind.removed]:
        parts.append(f"{counts[ChangeKind.removed]} removed")
    if counts[ChangeKind.returned]:
        parts.append(f"{counts[ChangeKind.returned]} back in the listing")
    headline = (
        f"{run.items_extracted} items checked: {', '.join(parts)}." if parts
        else f"{run.items_extracted} items checked; nothing changed since the last run."
    )

    highlights = []
    numeric = numeric_fields(config)
    moves = []
    for c in changes:
        if c.kind == ChangeKind.changed:
            for name in numeric:
                if name in c.changes:
                    pct = percent_change(*c.changes[name])
                    if pct is not None:
                        moves.append((pct, name, c))
    moves.sort(key=lambda m: m[0])
    for pct, name, c in moves[:2]:
        if pct < 0:
            old, new = c.changes[name]
            highlights.append(f"Biggest drop: {_label(c, config)}, {name} {old} → {new} ({pct:.0f}%).")
    for pct, name, c in reversed(moves[-2:]):
        if pct > 0:
            old, new = c.changes[name]
            highlights.append(f"Biggest rise: {_label(c, config)}, {name} {old} → {new} (+{pct:.0f}%).")
    if moves:
        down = sum(1 for m in moves if m[0] < 0)
        highlights.append(f"{down} of {len(moves)} numeric changes were decreases.")
    new_items = [_label(c, config) for c in changes if c.kind == ChangeKind.new][:3]
    if new_items:
        highlights.append("New: " + ", ".join(new_items) + ("…" if counts[ChangeKind.new] > 3 else "."))
    removed = [_label(c, config) for c in changes if c.kind == ChangeKind.removed][:3]
    if removed:
        highlights.append("Removed: " + ", ".join(removed) + ("…" if counts[ChangeKind.removed] > 3 else "."))

    watch = [a["message"] for a in (run.anomalies or [])][:3]
    if run.pages_failed:
        watch.append(f"{run.pages_failed} page(s) failed to load; see the run log.")
    return {"headline": headline, "highlights": highlights[:5], "watch": watch[:3]}


def summarize(db: Session, run: Run, changes: list[ItemChange]) -> AIResult:
    config = ScraperConfig.model_validate(run.config_snapshot)
    sample = []
    for c in changes[:MAX_CHANGES_IN_PROMPT]:
        entry = {"item": _label(c, config), "kind": c.kind.value}
        if c.kind == ChangeKind.changed:
            entry["changes"] = c.changes
        sample.append(entry)
    facts = {
        "scraper": run.scraper.name,
        "items_found": run.items_extracted,
        "new": run.items_new,
        "changed": run.items_changed,
        "removed": run.items_removed,
        "unchanged": run.items_unchanged,
        "pages_fetched": run.pages_fetched,
        "pages_failed": run.pages_failed,
        "blocked_by_policy": run.requests_blocked,
        "data_quality_flags": [a["message"] for a in run.anomalies or []],
        "changes": sample,
        "changes_not_shown": max(0, len(changes) - MAX_CHANGES_IN_PROMPT),
    }
    return run_json(
        db=db, workspace_id=run.workspace_id, user_id=None, feature="run_summary", system=SYSTEM,
        prompt=json.dumps(facts, ensure_ascii=False, default=str), schema=SCHEMA,
        demo=lambda: _demo(run, changes, config), max_tokens=4000,
    )
