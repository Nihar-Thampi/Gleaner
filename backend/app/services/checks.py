"""Health checks after each run, compared with the previous successful run.

They catch the usual ways scraped data goes wrong without anyone noticing: a site
redesign breaks a selector, a field stops filling, the item count collapses, or a value
jumps implausibly (a £389 tent listed at £38.90).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChangeKind, Run, RunStatus
from app.scraper.config import ScraperConfig
from app.services.ingest import IngestResult, numeric_fields, percent_change

COUNT_DROP = 0.3  # 30% fewer items than last time
FILL_DROP = 0.25  # a field filled 25 percentage points less often
BIG_MOVE = 50.0  # a numeric value moved by more than 50%
MASS_REMOVAL = 0.2  # more than 20% of tracked items removed at once


def previous_good_run(db: Session, run: Run) -> Run | None:
    return db.scalar(
        select(Run)
        .where(
            Run.scraper_id == run.scraper_id,
            Run.id != run.id,
            Run.status.in_([RunStatus.succeeded, RunStatus.partial]),
            Run.created_at < run.created_at,
        )
        .order_by(Run.created_at.desc())
        .limit(1)
    )


def anomaly(kind: str, severity: str, message: str, **details) -> dict:
    return {"kind": kind, "severity": severity, "message": message, **details}


def run_checks(db: Session, run: Run, result: IngestResult, tracked_before: int) -> list[dict]:
    config = ScraperConfig.model_validate(run.config_snapshot)
    found: list[dict] = []
    prev = previous_good_run(db, run)

    if prev and prev.items_extracted >= 10 and run.items_extracted < prev.items_extracted * (1 - COUNT_DROP):
        found.append(anomaly(
            "count_drop", "warning",
            f"Found {run.items_extracted} items, down from {prev.items_extracted} last run.",
            previous=prev.items_extracted, current=run.items_extracted,
        ))

    if prev and prev.quality and result.valid:
        before = prev.quality.get("fill_rates", {})
        for name, rate in result.quality["fill_rates"].items():
            if name in before and before[name] - rate >= FILL_DROP:
                found.append(anomaly(
                    "fill_drop", "warning",
                    f"“{name}” was filled for {rate:.0%} of items, down from {before[name]:.0%}. Its selector may have stopped matching.",
                    field=name, previous=before[name], current=rate,
                ))

    numeric = numeric_fields(config)
    moves = []
    for c in result.changes:
        if c.kind != ChangeKind.changed:
            continue
        for name in numeric:
            if name in c.changes:
                old, new = c.changes[name]
                pct = percent_change(old, new)
                if pct is not None and abs(pct) > BIG_MOVE:
                    moves.append((abs(pct), c, name, old, new, pct))
    for _, c, name, old, new, pct in sorted(moves, key=lambda m: -m[0])[:5]:
        label = c.item.data.get(config.fields[0].name) or c.item.key
        found.append(anomaly(
            "outlier_change", "warning",
            f"{name} for “{label}” moved {pct:+.0f}% ({old} → {new}). Worth checking it's real.",
            field=name, item_id=c.item.id, previous=old, current=new, percent=round(pct, 1),
        ))

    if tracked_before >= 10 and result.removed > tracked_before * MASS_REMOVAL:
        found.append(anomaly(
            "mass_removal", "warning",
            f"{result.removed} of {tracked_before} tracked items disappeared in one run.",
            removed=result.removed, tracked=tracked_before,
        ))

    if result.invalid and result.invalid >= max(3, 0.1 * (result.invalid + result.valid)):
        found.append(anomaly(
            "invalid_rows", "warning",
            f"{result.invalid} rows were rejected for missing required fields.",
            invalid=result.invalid,
        ))
    return found
