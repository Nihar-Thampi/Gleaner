"""Request bodies. (Responses are built in app/services/serializers.py.)"""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import DomainStatus, Role
from app.scraper.config import ScraperConfig
from app.scraper.policy import check_url_shape


def _check_url(v: str) -> str:
    v = v.strip()
    if reason := check_url_shape(v):
        raise ValueError(reason)
    return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    ai_run_summaries: bool | None = None


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str = Field(min_length=8, max_length=200)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=200)


class DomainIn(BaseModel):
    url: str = Field(description="Any URL on the site, or just its host")
    basis: str = Field("", max_length=2000)
    requests_per_minute: int = Field(30, ge=1, le=600)
    approve: bool = False  # admins only: approve straight away (needs a basis)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if "://" not in v:
            v = "https://" + v
        return _check_url(v)


class DomainUpdate(BaseModel):
    status: DomainStatus | None = None
    basis: str | None = Field(None, max_length=2000)
    requests_per_minute: int | None = Field(None, ge=1, le=600)


class UrlCheckIn(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


class ScraperIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    start_urls: list[str] = Field(min_length=1, max_length=50)
    config: ScraperConfig
    schedule_minutes: int | None = Field(None, ge=15, le=60 * 24 * 30)
    enabled: bool = True

    @field_validator("start_urls")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        return [_check_url(u) for u in v if u.strip()]


class ScraperUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    start_urls: list[str] | None = Field(None, min_length=1, max_length=50)
    config: ScraperConfig | None = None
    schedule_minutes: int | None = Field(None, ge=15, le=60 * 24 * 30)
    enabled: bool | None = None

    @field_validator("start_urls")
    @classmethod
    def _urls(cls, v: list[str] | None) -> list[str] | None:
        return [_check_url(u) for u in v if u.strip()] if v is not None else None


class PreviewIn(BaseModel):
    url: str
    config: ScraperConfig
    page_kind: Literal["list", "detail"] = "list"

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


class SuggestIn(BaseModel):
    url: str
    fields: str = Field(min_length=2, max_length=2000, description="The fields you want, in plain English")
    page_kind: Literal["list", "detail"] = "list"

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


AlertKind = Literal["field_change", "new_item", "item_removed", "run_failed", "anomaly"]


class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: AlertKind
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    params: dict | None = None
    enabled: bool | None = None


class WebhookIn(BaseModel):
    url: str
    events: list[Literal["run.finished", "alert.fired"]] = Field(min_length=1)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


class WebhookUpdate(BaseModel):
    url: str | None = None
    events: list[Literal["run.finished", "alert.fired"]] | None = None
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _check_url(v) if v else None


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    can_trigger_runs: bool = False
