"""Turn HTML into rows, following a ScraperConfig. Pure functions: no network, no database.

The same code runs for live runs, previews in the editor, the AI suggestion check and
the seeded history, so what you preview is exactly what a run stores.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from parsel import Selector

from app.scraper.config import FieldSpec, ScraperConfig

_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"-?\d[\d.,\s]*")


@dataclass
class Row:
    data: dict
    source_url: str
    detail_url: str | None = None
    errors: list[str] = field(default_factory=list)  # e.g. "price: couldn't read '£--' as a price"


@dataclass
class PageResult:
    rows: list[Row]
    next_url: str | None
    item_count: int  # elements matched by item_selector (even if every row is invalid)


def clean_text(value: str | None) -> str:
    return _WS.sub(" ", value or "").strip()


def parse_number(text: str) -> float | None:
    """Read a number from text like "£1,299.00", "1.299,00 €", "12 left" or "-3.5%"."""
    m = _NUMBER.search(text.replace(" ", " "))
    if not m:
        return None
    raw = m.group(0).replace(" ", "").rstrip(".,")
    if "," in raw and "." in raw:
        # Whichever separator comes last is the decimal point.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        # "12,50" is a decimal comma; "1,299" is a thousands separator.
        raw = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _raw_values(node: Selector, spec: FieldSpec) -> list[str]:
    nodes = node.css(spec.selector) if spec.selector else [node]
    values: list[str] = []
    for n in nodes:
        if spec.attr == "text":
            v = clean_text(n.xpath("string()").get())
        elif spec.attr == "html":
            v = (n.get() or "").strip()
        else:
            v = clean_text(n.attrib.get(spec.attr))
        if v:
            values.append(v)
        if not spec.multiple and values:
            break
    return values


def _convert(raw: str, spec: FieldSpec, base_url: str):
    """One raw string -> a typed value. Raises ValueError with a readable reason."""
    value: str | None = raw
    if spec.regex and spec.type != "boolean":
        m = re.search(spec.regex, raw)
        value = (m.group(1) if m and m.groups() else m.group(0) if m else None)
        if value is None:
            raise ValueError(f"pattern didn't match {raw[:60]!r}")
    if spec.value_map and value in spec.value_map:
        mapped = spec.value_map[value]
        if not isinstance(mapped, str):
            return mapped
        value = mapped

    match spec.type:
        case "string":
            return value
        case "url":
            return urljoin(base_url, value)
        case "boolean":
            return bool(re.search(spec.regex, raw, re.I)) if spec.regex else bool(value)
        case "number" | "price" | "integer":
            n = parse_number(value)
            if n is None:
                raise ValueError(f"couldn't read {value[:60]!r} as a {spec.type}")
            if spec.type == "integer":
                return int(round(n))
            return round(n, 2) if spec.type == "price" else n
    return value


def extract_fields(node: Selector, specs: list[FieldSpec], base_url: str, row: Row) -> None:
    for spec in specs:
        raws = _raw_values(node, spec)
        if spec.type == "boolean" and spec.regex and not spec.multiple:
            # A boolean with a pattern is false (not missing) when nothing matches.
            row.data[spec.name] = bool(raws) and bool(re.search(spec.regex, raws[0], re.I))
            continue
        values = []
        for raw in raws:
            try:
                values.append(_convert(raw, spec, base_url))
            except ValueError as e:
                row.errors.append(f"{spec.name}: {e}")
        if spec.multiple:
            row.data[spec.name] = values
        else:
            row.data[spec.name] = values[0] if values else None


def _link(node: Selector, selector: str, base_url: str) -> str | None:
    """The href of the first match, or of the first link inside it."""
    for n in node.css(selector):
        href = n.attrib.get("href") or n.css("a::attr(href)").get()
        if href and not href.startswith(("javascript:", "mailto:", "#")):
            return urljoin(base_url, href.strip())
    return None


def extract_list_page(html: str, url: str, config: ScraperConfig) -> PageResult:
    sel = Selector(text=html, base_url=url)
    items = sel.css(config.item_selector) if config.item_selector else [sel]
    rows = []
    for node in items:
        row = Row(data={}, source_url=url)
        extract_fields(node, config.fields_for("list"), url, row)
        if config.has_detail:
            row.detail_url = _link(node, config.detail_link_selector, url)
        rows.append(row)
    next_url = _link(sel, config.next_page_selector, url) if config.next_page_selector else None
    return PageResult(rows=rows, next_url=next_url, item_count=len(items))


def extract_detail_page(html: str, url: str, config: ScraperConfig, row: Row) -> None:
    extract_fields(Selector(text=html, base_url=url), config.fields_for("detail"), url, row)
    row.source_url = url


def missing_required(row: Row, config: ScraperConfig) -> list[str]:
    return [f.name for f in config.fields if f.required and row.data.get(f.name) in (None, "", [])]


def is_filled(value) -> bool:
    return value not in (None, "", [])


def fill_rates(rows: list[dict], config: ScraperConfig) -> dict[str, float]:
    if not rows:
        return {f.name: 0.0 for f in config.fields}
    return {f.name: round(sum(is_filled(r.get(f.name)) for r in rows) / len(rows), 4) for f in config.fields}


def looks_javascript_rendered(html: str) -> bool:
    """Heuristic for "this page builds its content with JavaScript": little visible text, scripts present."""
    sel = Selector(text=html)
    body_text = clean_text(" ".join(sel.css("body *:not(script):not(style)::text").getall()))
    scripts = sel.css("script").getall()
    inline_js = sum(len(s) for s in scripts)
    return bool(scripts) and (len(body_text) < 400 or inline_js > len(body_text))
