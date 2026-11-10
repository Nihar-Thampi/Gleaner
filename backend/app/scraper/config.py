"""What a scraper fetches and how it turns pages into rows.

A scraper visits its start URLs (listing pages), follows the "next page" link up to
`max_pages`, and finds one row per `item_selector` match. Each field is a CSS selector
relative to that item. Fields marked `source="detail"` are read from the item's own page
(the link found by `detail_link_selector`), so one row can combine both.

Rows are matched across runs by `key_fields` (for example the product URL), which is how
changes, removals and returning items are detected.
"""
import re
from typing import Literal

from cssselect import GenericTranslator, SelectorError
from pydantic import BaseModel, Field, field_validator, model_validator

FieldType = Literal["string", "number", "integer", "price", "url", "boolean"]

FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_translator = GenericTranslator()


def check_css(selector: str) -> str:
    selector = selector.strip()
    try:
        _translator.css_to_xpath(selector)
    except SelectorError as e:
        raise ValueError(f"Invalid CSS selector {selector!r}: {e}") from None
    return selector


class FieldSpec(BaseModel):
    name: str = Field(description="Column name: lowercase letters, digits and underscores")
    # Empty selector = the item element itself.
    selector: str = ""
    # "text" (all text inside, whitespace collapsed), "html", or an attribute name such as href.
    attr: str = "text"
    type: FieldType = "string"
    source: Literal["list", "detail"] = "list"
    multiple: bool = False  # every match as a list (e.g. tags) instead of the first
    required: bool = False  # rows missing this field are rejected as invalid
    # Optional regular expression; the first group (or the whole match) is kept.
    # For booleans, the field is true when the pattern matches.
    regex: str | None = None
    # Optional value mapping applied after the regex, e.g. {"Three": 3}.
    value_map: dict[str, str | int | float] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not FIELD_NAME.match(v):
            raise ValueError("Field names use lowercase letters, digits and underscores, starting with a letter.")
        return v

    @field_validator("selector")
    @classmethod
    def _selector(cls, v: str) -> str:
        return check_css(v) if v.strip() else ""

    @field_validator("attr")
    @classmethod
    def _attr(cls, v: str) -> str:
        v = v.strip() or "text"
        if not re.match(r"^[a-zA-Z_:][-a-zA-Z0-9_:.]*$", v):
            raise ValueError(f"Invalid attribute name {v!r}.")
        return v

    @field_validator("regex")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regular expression: {e}") from None
        return v


class ScraperConfig(BaseModel):
    # Empty = the whole page is one row (e.g. a single product page).
    item_selector: str = ""
    fields: list[FieldSpec] = Field(min_length=1, max_length=60)
    detail_link_selector: str | None = None
    next_page_selector: str | None = None
    max_pages: int = Field(default=10, ge=1, le=500)
    max_items: int | None = Field(default=None, ge=1, le=50_000)
    # "browser" renders the page in headless Chromium first (for sites built with JavaScript).
    render: Literal["static", "browser"] = "static"
    wait_for_selector: str | None = None  # browser mode: wait until this appears
    key_fields: list[str] = Field(default_factory=list)

    @field_validator("item_selector")
    @classmethod
    def _item(cls, v: str) -> str:
        return check_css(v) if v.strip() else ""

    @field_validator("detail_link_selector", "next_page_selector", "wait_for_selector")
    @classmethod
    def _optional_css(cls, v: str | None) -> str | None:
        return check_css(v) if v and v.strip() else None

    @model_validator(mode="after")
    def _consistent(self) -> "ScraperConfig":
        names = [f.name for f in self.fields]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"Duplicate field names: {', '.join(sorted(dupes))}.")
        unknown = [k for k in self.key_fields if k not in names]
        if unknown:
            raise ValueError(f"Key fields must be fields of this scraper: {', '.join(unknown)}.")
        if any(f.source == "detail" for f in self.fields) and not self.detail_link_selector:
            raise ValueError("Fields read from the detail page need a detail link selector.")
        return self

    @property
    def has_detail(self) -> bool:
        return bool(self.detail_link_selector) and any(f.source == "detail" for f in self.fields)

    def fields_for(self, source: str) -> list[FieldSpec]:
        return [f for f in self.fields if f.source == source]
