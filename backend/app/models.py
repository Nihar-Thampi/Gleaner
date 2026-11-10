"""Data model.

Every row belongs to a workspace (one customer account); no query crosses workspaces.

- Domain: the compliance policy for one website. Scrapers only fetch from domains an
  admin has approved, at that domain's rate limit, and always within its robots.txt.
- Scraper: what to fetch and how to turn pages into rows (see app/scraper/config.py).
- Run: one execution of a scraper, with counters, logs and a data-quality report.
- Item: one row of scraped data, tracked across runs by its key; ItemChange records
  every new, changed, removed and returning item.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always UTC and timezone-aware, including on SQLite (which drops the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Role(str, enum.Enum):
    admin = "admin"  # everything, including domain approval, team, keys and webhooks
    editor = "editor"  # build and run scrapers, manage alerts
    viewer = "viewer"  # read data and export it


class DomainStatus(str, enum.Enum):
    pending = "pending"  # requested; nothing is fetched until an admin approves it
    approved = "approved"
    blocked = "blocked"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"  # finished, but some pages failed or were skipped
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_RUN_STATUSES = (RunStatus.queued, RunStatus.running)


class ChangeKind(str, enum.Enum):
    new = "new"
    changed = "changed"
    removed = "removed"
    returned = "returned"  # seen again after being removed


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    # Sent in the crawler's User-Agent so site owners can reach whoever is crawling.
    contact_email: Mapped[str] = mapped_column(String(320))
    ai_run_summaries: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    workspace: Mapped[Workspace] = relationship(lazy="joined")


class ApiKey(Base):
    """Read access to scraped data for other systems. Only a hash of the key is stored."""

    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in the UI to tell keys apart
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    can_trigger_runs: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("workspace_id", "host"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    host: Mapped[str] = mapped_column(String(255))  # e.g. books.toscrape.com (port included if not default)
    status: Mapped[DomainStatus] = mapped_column(Enum(DomainStatus, native_enum=False, length=20), default=DomainStatus.pending)
    # Why scraping this site is allowed (terms reviewed, public data, own site, written permission...).
    basis: Mapped[str] = mapped_column(Text, default="")
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Cached robots.txt (refreshed daily, or on demand).
    robots_status: Mapped[int | None] = mapped_column(Integer)  # HTTP status of the robots.txt fetch
    robots_txt: Mapped[str | None] = mapped_column(Text)
    robots_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    crawl_delay: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    reviewed_by: Mapped["User | None"] = relationship(lazy="joined")


class Scraper(Base):
    __tablename__ = "scrapers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    start_urls: Mapped[list] = mapped_column(JSON)
    config: Mapped[dict] = mapped_column(JSON)  # validated by app.scraper.config.ScraperConfig
    schedule_minutes: Mapped[int | None] = mapped_column(Integer)  # None = manual only
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    scraper_id: Mapped[str] = mapped_column(ForeignKey("scrapers.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3... per scraper
    trigger: Mapped[str] = mapped_column(String(20))  # manual, schedule, api
    triggered_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, native_enum=False, length=20), default=RunStatus.queued, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    config_snapshot: Mapped[dict] = mapped_column(JSON)  # the config this run used
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Counters, updated while the run progresses.
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    requests_blocked: Mapped[int] = mapped_column(Integer, default=0)  # robots.txt or domain policy
    retries: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    total_response_ms: Mapped[int] = mapped_column(Integer, default=0)
    status_codes: Mapped[dict] = mapped_column(JSON, default=dict)
    items_extracted: Mapped[int] = mapped_column(Integer, default=0)
    items_invalid: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_changed: Mapped[int] = mapped_column(Integer, default=0)
    items_removed: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    # Per-field fill rates and validation failures; anomalies the checks flagged.
    quality: Mapped[dict | None] = mapped_column(JSON)
    anomalies: Mapped[list] = mapped_column(JSON, default=list)
    ai_summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    scraper: Mapped[Scraper] = relationship(lazy="joined")
    triggered_by: Mapped["User | None"] = relationship(lazy="joined")

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() * 1000)
        return None


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String(10))  # info, warning, error
    message: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("scraper_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scraper_id: Mapped[str] = mapped_column(ForeignKey("scrapers.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_changed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ItemChange(Base):
    __tablename__ = "item_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scraper_id: Mapped[str] = mapped_column(ForeignKey("scrapers.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), index=True)
    kind: Mapped[ChangeKind] = mapped_column(Enum(ChangeKind, native_enum=False, length=20))
    # {field: [old, new]} for "changed"; the full row for new/removed/returned.
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    item: Mapped[Item] = relationship(lazy="joined")


class AlertRule(Base):
    """Notify when data changes in a way someone cares about.

    kind:
      field_change  params {field, direction: any|up|down, min_percent}
      new_item      params {field?, contains?}  (optionally only items matching a filter)
      item_removed  params {}
      run_failed    params {}  (also fires on a broken selector)
      anomaly       params {}  (any anomaly the run checks flag)
    """

    __tablename__ = "alert_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    scraper_id: Mapped[str] = mapped_column(ForeignKey("scrapers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    scraper: Mapped[Scraper] = relationship(lazy="joined")


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    scraper_id: Mapped[str] = mapped_column(ForeignKey("scrapers.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)

    rule: Mapped[AlertRule] = relationship(lazy="joined")


class Webhook(Base):
    """POSTs signed JSON to another system when runs finish or alerts fire."""

    __tablename__ = "webhooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256 key for the signature header
    events: Mapped[list] = mapped_column(JSON)  # run.finished, alert.fired
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    status_code: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class AIRequest(Base):
    """Log of every AI call: what was asked, what came back, how long and which model."""

    __tablename__ = "ai_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    feature: Mapped[str] = mapped_column(String(40))  # suggest, repair, run_summary
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    input_text: Mapped[str] = mapped_column(Text)
    output_text: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    user: Mapped["User | None"] = relationship(lazy="joined")
