"""Store a run's rows: validate, de-duplicate, match to known items and record changes.

Removal detection only happens on complete runs (every listing page fetched, nothing
cut short). Otherwise a single failed page would make its items look deleted.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChangeKind, Item, ItemChange, Run, Scraper
from app.scraper.config import ScraperConfig
from app.scraper.extract import Row, fill_rates, is_filled, missing_required

MAX_ERROR_SAMPLES = 15


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def item_key(data: dict, config: ScraperConfig) -> str:
    if config.key_fields:
        return " | ".join(str(data.get(k)) for k in config.key_fields)[:500]
    return _hash(data)[:32]  # no key: identical rows are the same item


def diff(old: dict, new: dict) -> dict:
    return {k: [old.get(k), new.get(k)] for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)}


@dataclass
class IngestResult:
    valid: int = 0
    invalid: int = 0
    duplicates: int = 0
    new: int = 0
    changed: int = 0
    removed: int = 0
    returned: int = 0
    unchanged: int = 0
    changes: list[ItemChange] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    baseline: bool = False


def ingest(db: Session, scraper: Scraper, run: Run, rows: list[Row], *, complete: bool, now: datetime) -> IngestResult:
    config = ScraperConfig.model_validate(run.config_snapshot)
    result = IngestResult()
    errors: list[dict] = []
    type_errors: dict[str, int] = {}

    valid_rows: dict[str, Row] = {}
    for row in rows:
        for e in row.errors:
            type_errors[e.split(":", 1)[0]] = type_errors.get(e.split(":", 1)[0], 0) + 1
        missing = missing_required(row, config)
        if missing:
            result.invalid += 1
            if len(errors) < MAX_ERROR_SAMPLES:
                errors.append({"url": row.detail_url or row.source_url, "problem": f"Missing required: {', '.join(missing)}"})
            continue
        if row.errors and len(errors) < MAX_ERROR_SAMPLES:
            errors.append({"url": row.detail_url or row.source_url, "problem": "; ".join(row.errors[:3])})
        key = item_key(row.data, config)
        if key in valid_rows:
            result.duplicates += 1
            continue
        valid_rows[key] = row
    result.valid = len(valid_rows)

    existing = {i.key: i for i in db.scalars(select(Item).where(Item.scraper_id == scraper.id))}
    # The first run records a baseline: its items aren't "new" changes (no feed entries, no alerts).
    result.baseline = not existing

    def change(item: Item, kind: ChangeKind, changes: dict) -> None:
        c = ItemChange(scraper_id=scraper.id, item=item, run_id=run.id, kind=kind, changes=changes, at=now)
        db.add(c)
        result.changes.append(c)

    for key, row in valid_rows.items():
        h = _hash(row.data)
        item = existing.get(key)
        if item is None:
            item = Item(
                scraper_id=scraper.id, key=key, data=row.data, content_hash=h, source_url=row.detail_url or row.source_url,
                first_seen_at=now, last_seen_at=now, last_changed_at=now, last_run_id=run.id,
            )
            db.add(item)
            result.new += 1
            if not result.baseline:
                change(item, ChangeKind.new, row.data)
            continue

        item.last_seen_at, item.last_run_id = now, run.id
        item.source_url = row.detail_url or row.source_url
        if item.removed_at is not None:
            item.removed_at = None
            result.returned += 1
            change(item, ChangeKind.returned, diff(item.data, row.data) or {})
            if item.content_hash != h:
                item.data, item.content_hash, item.version, item.last_changed_at = row.data, h, item.version + 1, now
        elif item.content_hash != h:
            result.changed += 1
            change(item, ChangeKind.changed, diff(item.data, row.data))
            item.data, item.content_hash, item.version, item.last_changed_at = row.data, h, item.version + 1, now
        else:
            result.unchanged += 1

    if complete:
        for key, item in existing.items():
            if key not in valid_rows and item.removed_at is None:
                item.removed_at = now
                result.removed += 1
                change(item, ChangeKind.removed, item.data)

    data_rows = [r.data for r in valid_rows.values()]
    result.quality = {
        "fill_rates": fill_rates(data_rows, config),
        "type_errors": type_errors,
        "rows_total": len(rows),
        "rows_valid": result.valid,
        "rows_invalid": result.invalid,
        "duplicates": result.duplicates,
        "error_samples": errors,
        "removal_check": complete,
        "baseline": result.baseline,
    }
    return result


def numeric_fields(config: ScraperConfig) -> list[str]:
    return [f.name for f in config.fields if f.type in ("number", "integer", "price") and not f.multiple]


def percent_change(old, new) -> float | None:
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or isinstance(old, bool) or old == 0:
        return None
    return (new - old) / abs(old) * 100


__all__ = ["ingest", "IngestResult", "diff", "item_key", "numeric_fields", "percent_change", "is_filled"]
