"""AI selector assistant and scraper repair.

Both follow the same loop: the model proposes a config from the simplified HTML, the
real extractor runs it on the real page, and if fields come back mostly empty the model
gets one more attempt with those results. What the user sees is always a verified
preview, never an unchecked guess.
"""
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.client import STR, AIResult, nullable, obj, run_json
from app.ai.heuristics import field_name, suggest_config
from app.ai.pagehtml import simplify
from app.scraper.config import ScraperConfig
from app.scraper.extract import extract_detail_page, extract_list_page, fill_rates, Row

FIELD_SCHEMA = obj({
    "name": STR,
    "selector": STR,
    "attr": STR,
    "type": {"type": "string", "enum": ["string", "number", "integer", "price", "url", "boolean"]},
    "multiple": {"type": "boolean"},
    "required": {"type": "boolean"},
    "regex": nullable(STR),
    "value_map": nullable({"type": "array", "items": obj({"from": STR, "to": STR})}),
})

SUGGEST_SCHEMA = obj({
    "item_selector": STR,
    "fields": {"type": "array", "items": FIELD_SCHEMA},
    "next_page_selector": nullable(STR),
    "key_fields": {"type": "array", "items": STR},
    "notes": {"type": "array", "items": STR},
})

SYSTEM = """You configure a web scraper. Given a page's simplified HTML and the fields a user wants, \
return CSS selectors that extract them.

Rules:
- item_selector matches one element per item (product card, table row, search result). Use "" only \
when the page is a single item (a detail page).
- Field selectors are relative to the item element. Use "" for the item element itself.
- attr is "text" (all text inside, whitespace collapsed), "html", or an attribute name such as \
"href", "src", "title", "datetime" or "class".
- type: string, number, integer, price (a currency amount; symbols and thousands separators are \
handled), url (relative links are resolved), or boolean.
- regex (optional) keeps the first capture group. For booleans it means "true when this matches"; \
for example "in stock" on an availability label.
- value_map (optional) maps exact extracted strings to values, e.g. rating words to numbers: \
[{"from": "Three", "to": "3"}] with type integer.
- multiple=true returns every match as a list (tags, categories).
- Prefer stable selectors: semantic class names, itemprop and data-* attributes. Avoid layout \
classes (col-md-4, mt-2), generated class names (css-1x2y3z) and positional selectors unless \
nothing else works.
- next_page_selector matches the link to the next page of results, or null if there is none.
- key_fields names the field(s) that identify an item across runs: its URL if there is one, \
otherwise a stable name or ID. Mark key fields required.
- Use snake_case field names (lowercase letters, digits, underscores).
- notes: short, plain-English remarks for the user (assumptions, fields you couldn't find). \
Don't repeat the config back."""


def _to_config_dict(data: dict, page_kind: str) -> dict:
    fields = []
    for f in data.get("fields", []):
        f = dict(f)
        vm = f.get("value_map")
        if isinstance(vm, list):
            f["value_map"] = {p["from"]: _maybe_number(p["to"]) for p in vm} or None
        f["source"] = "detail" if page_kind == "detail" else "list"
        fields.append(f)
    return {
        "item_selector": "" if page_kind == "detail" else data.get("item_selector", ""),
        "fields": fields,
        "next_page_selector": None if page_kind == "detail" else data.get("next_page_selector"),
        "key_fields": data.get("key_fields") or [],
    }


def _maybe_number(v: str):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v


def _from_heuristics(page_html: str, descriptions: list[str], page_kind: str) -> dict:
    config, notes = suggest_config(page_html, descriptions, page_kind)
    vm_fields = []
    for f in config["fields"]:
        f = dict(f)
        if f.get("value_map"):
            f["value_map"] = [{"from": k, "to": str(v)} for k, v in f["value_map"].items()]
        f.pop("source", None)
        vm_fields.append(f)
    return {**config, "fields": vm_fields, "notes": notes}


def evaluate(page_html: str, url: str, config_dict: dict, page_kind: str) -> dict:
    """Run a proposed config on the page. Returns preview rows, fill rates and problems."""
    try:
        config = ScraperConfig.model_validate(config_dict)
    except ValidationError as e:
        return {"valid": False, "error": "; ".join(err["msg"] for err in e.errors()[:3]), "rows": [], "fill_rates": {}, "item_count": 0}
    if page_kind == "detail":
        row = Row(data={}, source_url=url)
        extract_detail_page(page_html, url, config, row)
        rows, count, next_url = [row], 1, None
    else:
        page = extract_list_page(page_html, url, config)
        rows, count, next_url = page.rows, page.item_count, page.next_url
    data = [r.data for r in rows]
    on_page = {f.name for f in config.fields_for("detail" if page_kind == "detail" else "list")}
    return {
        "valid": True,
        "config": config.model_dump(),
        "item_count": count,
        "rows": data[:10],
        "fill_rates": {k: v for k, v in fill_rates(data, config).items() if k in on_page},
        "errors": sorted({e for r in rows for e in r.errors})[:10],
        "next_url": next_url,
    }


def _weak(check: dict) -> list[str]:
    if not check["valid"]:
        return ["config invalid: " + check["error"]]
    if check["item_count"] == 0:
        return ["item_selector matched nothing"]
    return [f"{name} filled for {rate:.0%} of items" for name, rate in check["fill_rates"].items() if rate < 0.5]


def _prompt(url: str, page_html: str, request: str, extra: str = "") -> str:
    return f"Page URL: {url}\n\n{request}\n{extra}\nSimplified HTML:\n```html\n{simplify(page_html)}\n```"


def suggest(
    *, db: Session, workspace_id: str, user_id: str, url: str, page_html: str, descriptions: list[str], page_kind: str = "list",
) -> tuple[dict, AIResult]:
    request = (
        ("This is a detail page for a single item." if page_kind == "detail" else "This is a listing page with many items.")
        + "\nFields wanted:\n" + "\n".join(f"- {d}" for d in descriptions)
    )
    result = run_json(
        db=db, workspace_id=workspace_id, user_id=user_id, feature="suggest", system=SYSTEM,
        prompt=_prompt(url, page_html, request), schema=SUGGEST_SCHEMA,
        demo=lambda: _from_heuristics(page_html, descriptions, page_kind),
    )
    check = evaluate(page_html, url, _to_config_dict(result.data, page_kind), page_kind)
    problems = _weak(check)
    attempts = 1
    if problems and result.provider == "local":
        # One correction round, with what actually happened on the page.
        feedback = (
            f"\nYour previous answer:\n{json.dumps(result.data)}\n\nWhen run on the page: "
            + "; ".join(problems)
            + f"\nSample rows extracted: {json.dumps(check.get('rows', [])[:3], default=str)[:2000]}\nFix the selectors."
        )
        retry = run_json(
            db=db, workspace_id=workspace_id, user_id=user_id, feature="suggest", system=SYSTEM,
            prompt=_prompt(url, page_html, request, feedback), schema=SUGGEST_SCHEMA,
            demo=lambda: result.data,
        )
        retry_check = evaluate(page_html, url, _to_config_dict(retry.data, page_kind), page_kind)
        attempts = 2
        if len(_weak(retry_check)) <= len(problems):
            result, check, problems = retry, retry_check, _weak(retry_check)
    check["notes"] = result.data.get("notes", [])
    check["problems"] = problems
    check["attempts"] = attempts
    return check, result


REPAIR_SYSTEM = SYSTEM + """

You are repairing an existing scraper that stopped working (the site probably changed its \
layout). Keep the same field names and types so stored data stays comparable; change only the \
selectors (and attr/regex if needed). Explain what changed in notes."""


def repair(
    *, db: Session, workspace_id: str, user_id: str, url: str, page_html: str, current: ScraperConfig, symptoms: list[str],
) -> tuple[dict, AIResult]:
    list_fields = [f for f in current.fields if f.source == "list"]
    request = (
        "Current configuration (no longer working):\n"
        + json.dumps(current.model_dump(include={"item_selector", "fields", "next_page_selector", "key_fields"}), indent=1)
        + "\nWhat went wrong in the latest run:\n" + "\n".join(f"- {s}" for s in symptoms)
        + "\nOnly fields with source \"list\" are on this page; return just those."
    )

    def demo() -> dict:
        descs = [f.name.replace("_", " ") for f in list_fields]
        suggestion = _from_heuristics(page_html, descs, "list")
        # Keep the stored names and types; take only the new selectors. Fields the rules
        # couldn't find keep their old selector, so the preview shows them as empty.
        found = {field_name(d): f for d, f in zip(descs, suggestion["fields"])} if len(suggestion["fields"]) == len(descs) else \
            {f["name"]: f for f in suggestion["fields"]}
        fields = []
        for old in list_fields:
            new = found.get(field_name(old.name.replace("_", " ")))
            if new is None:
                fields.append({**old.model_dump(exclude={"source"}), "value_map": None})
                continue
            new.update(name=old.name, type=old.type, multiple=old.multiple, required=old.required)
            if old.regex and new.get("attr") == old.attr:
                new["regex"] = old.regex
            fields.append(new)
        suggestion["fields"] = fields
        suggestion["key_fields"] = current.key_fields
        suggestion["notes"] = ["Rebuilt the selectors from the page as it looks now."] + suggestion["notes"]
        return suggestion

    result = run_json(
        db=db, workspace_id=workspace_id, user_id=user_id, feature="repair", system=REPAIR_SYSTEM,
        prompt=_prompt(url, page_html, request), schema=SUGGEST_SCHEMA, demo=demo,
    )
    proposed = _to_config_dict(result.data, "list")
    # Carry over everything the repair doesn't touch: detail fields, limits, render mode.
    merged = current.model_dump()
    merged["item_selector"] = proposed["item_selector"]
    merged["next_page_selector"] = proposed["next_page_selector"] or current.next_page_selector
    by_name = {f["name"]: f for f in proposed["fields"]}
    merged["fields"] = [
        {**f.model_dump(), **{k: by_name[f.name][k] for k in ("selector", "attr", "regex", "value_map") if k in by_name[f.name]}}
        if f.name in by_name else f.model_dump()
        for f in current.fields
    ]
    check = evaluate(page_html, url, merged, "list")
    check["notes"] = result.data.get("notes", [])
    check["problems"] = _weak(check)
    return check, result
