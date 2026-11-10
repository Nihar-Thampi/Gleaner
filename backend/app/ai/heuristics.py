"""Rule-based selector suggestions: the offline path for the AI assistant.

Finds the repeating element that looks most like "one item" (the product card, the table
row), then matches each requested field to an element inside it by class names,
microdata and content shape (prices look like prices, links have hrefs). Not as smart as
the model, but often right on conventional pages, and it needs no API key.
"""
import re
from collections import Counter

from lxml import etree, html

UTILITY_CLASS = re.compile(
    r"^(col|row|grid|span|flex|d|w|h|p|m|px|py|mx|my|pt|pb|mt|mb|g|gap|text|bg|border|rounded|shadow|container|clearfix|"
    r"pull|float|hidden|visible|sm|md|lg|xl|offset|btn|fa|icon|is|has|js|active|selected|first|last|odd|even)([-_].*)?$"
)
NUMBER_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
PRICE = re.compile(r"(?:[£$€¥₹]\s?\d|\d[\d,.]*\s?(?:USD|EUR|GBP|ZAR|R)\b|\bR\s?\d)")
SEMANTIC = re.compile(r"product|item|card|result|listing|entry|post|quote|article|record|row|team|country|book|offer|job|tile", re.I)

KINDS = [
    ("price", r"price|cost|amount|fee|rate\b"),
    ("image", r"image|img|photo|picture|thumbnail|thumb"),
    ("rating", r"rating|stars?|score"),
    ("in_stock", r"in[ -]stock|is available|available\?|whether"),
    ("stock", r"stock|availability|available"),
    ("url", r"link|url|href|page"),
    ("tags", r"\btags?\b|categor|keywords|labels"),
    ("author", r"author|writer|\bby\b"),
    ("date", r"\bdate\b|time|posted|published"),
    ("number", r"\b(count|number|population|area|quantity|qty|wins|losses|year|total|percent|pct|goals|points|reviews)\b"),
    ("title", r"title|name|product|heading|headline"),
]


def field_name(description: str) -> str:
    words = re.findall(r"[a-z0-9]+", description.lower())
    words = [w for w in words if w not in {"the", "a", "an", "of", "each", "its", "their", "to", "for", "and", "is", "whether", "if"}]
    name = "_".join(words[:3]) or "field"
    return name if name[0].isalpha() else f"f_{name}"


def parse_field_requests(text: str) -> list[str]:
    parts = re.split(r"[\n,;]+|\band\b", text)
    return [p.strip(" .-*•") for p in parts if p.strip(" .-*•")][:30]


def _classes(el) -> list[str]:
    return [c for c in (el.get("class") or "").split() if c]


def _meaningful(el) -> list[str]:
    return [c for c in _classes(el) if not UTILITY_CLASS.match(c) and not re.search(r"\d{3,}", c)]


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() or "").strip()


def _own_text(el) -> str:
    return re.sub(r"\s+", " ", " ".join(t for t in [el.text or ""] + [c.tail or "" for c in el])).strip()


def _sel(el) -> str:
    cls = _meaningful(el) or _classes(el)
    return el.tag + "".join(f".{c}" for c in cls[:2])


def _count(doc, selector: str) -> int:
    try:
        return len(doc.cssselect(selector))
    except Exception:  # noqa: BLE001
        return 0


# ---- finding the item container ----

def find_items(doc) -> tuple[str, list] | None:
    counts: Counter = Counter()
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag not in ("html", "body", "head", "script", "style", "option", "i", "br", "svg"):
            counts[_sel(el)] += 1
    best, best_score = None, 0.0
    for selector, n in counts.items():
        if n < 3 or n > 2000:
            continue
        members = doc.cssselect(selector)
        texts = [_text(m) for m in members[:30]]
        avg = sum(len(t) for t in texts) / max(1, len(texts))
        if avg < 12 or avg > 4000:
            continue
        rich = sum(len({_sel(d) for d in m.iter() if isinstance(d.tag, str)}) for m in members[:10]) / min(10, len(members))
        if rich < 3:
            continue
        links = sum(1 for m in members[:30] if m.cssselect("a[href]") or m.tag == "a") / max(1, len(texts))
        score = (n ** 0.5) * min(rich, 25) * (1 + links) * min(avg, 400) ** 0.3
        if SEMANTIC.search(selector):
            score *= 1.8
        if not _meaningful(members[0]):
            score *= 0.6
        if score > best_score:
            best, best_score = selector, score
    if best is None:
        return None
    # Of nested containers with the same count (li > article), the inner one is more specific.
    members = doc.cssselect(best)
    return best, members


# ---- matching a field inside an item ----

def _candidates(item) -> list:
    return [el for el in item.iter() if el is not item and isinstance(el.tag, str) and el.tag not in ("br", "script", "style")]


def _token_match(el, words: list[str]) -> bool:
    tokens = set()
    for c in _classes(el) + [el.get("itemprop") or "", el.get("id") or "", el.get("name") or ""]:
        tokens.update(t for t in re.split(r"[-_\s]+", c.lower()) if t)
    return any(w in tokens or any(t.startswith(w) and len(w) > 3 for t in tokens) for w in words)


def _relative_selector(item, el) -> str | None:
    """A selector, relative to `item`, whose first match is `el` in this item."""
    if el is item:
        return ""
    options = []
    for c in _meaningful(el) + _classes(el):
        options += [f"{el.tag}.{c}", f".{c}"]
    if el.get("itemprop"):
        options.append(f'[itemprop="{el.get("itemprop")}"]')
    options.append(el.tag)
    parent = el.getparent()
    if parent is not None and parent is not item:
        for c in _meaningful(parent) + _classes(parent):
            options.append(f"{parent.tag}.{c} {el.tag}")
        options.append(f"{parent.tag} {el.tag}")
    for s in options:
        try:
            found = item.cssselect(s)
        except Exception:  # noqa: BLE001
            continue
        if found and found[0] is el:
            return s
    same = [s for s in parent.iterchildren(el.tag)] if parent is not None else [el]
    if parent is not None and parent is not item:
        base = _relative_selector(item, parent)
        if base is not None:
            idx = same.index(el) + 1
            return f"{base} > {el.tag}:nth-of-type({idx})".strip(" >") if base else f"{el.tag}:nth-of-type({idx})"
    return None


def _kind(description: str) -> str:
    d = description.lower()
    for kind, pattern in KINDS:
        if re.search(pattern, d):
            return kind
    return "text"


def _score(el, kind: str, words: list[str]) -> float:
    text, own = _text(el), _own_text(el)
    s = 0.0
    if _token_match(el, words):
        s += 10
    if kind == "price" and PRICE.search(own or text) and len(text) < 30:
        s += 8
    elif kind == "image" and el.tag == "img":
        s += 8
    elif kind == "url" and el.tag == "a" and el.get("href"):
        s += 4 + (2 if el.getparent() is not None and el.getparent().tag in ("h1", "h2", "h3", "h4") else 0)
        if any(w in el.get("href", "").lower() for w in words):
            s += 3
    elif kind == "rating" and any(re.search("rating|star", c, re.I) for c in _classes(el)):
        s += 8
    elif kind in ("stock", "in_stock") and re.search(r"stock|available|availability|sold out", text, re.I) and len(text) < 60:
        s += 7
    elif kind == "title" and el.tag in ("h1", "h2", "h3", "h4", "h5") and text:
        s += 7
    elif kind == "title" and el.tag == "a" and (el.get("title") or text) and len(text) > 3:
        s += 4
    elif kind == "author" and (el.get("itemprop") == "author" or el.tag == "small"):
        s += 5
    elif kind == "tags" and any("tag" in c.lower() for c in _classes(el)):
        s += 6
    elif kind == "date" and (el.tag == "time" or re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} \w{3,9} \d{4}\b", text)):
        s += 6
    elif kind == "number" and re.fullmatch(r"[-\d.,\s%]+", text or "x"):
        s += 3
    elif kind == "text" and len(own) > 20:
        s += min(5, len(own) / 40)
    if not text and kind not in ("image", "url", "rating"):
        s -= 5
    if s > 0:
        s -= min(1.0, len(text) / 500)  # on a tie, the tighter element wins
    return s


def _column_from_header(items: list, words: list[str]):
    """For table rows: the cell under the header that best matches the description."""
    row = items[0]
    table = next((a for a in row.iterancestors("table")), None)
    if row.tag != "tr" or table is None:
        return None
    headers = table.cssselect("th")
    best, best_overlap = None, 0
    for i, th in enumerate(headers):
        head_words = set(re.findall(r"[a-z]{2,}", _text(th).lower()))
        overlap = len(head_words & set(words))
        if overlap > best_overlap:
            best, best_overlap = i, overlap
    cells = [c for c in row if isinstance(c.tag, str) and c.tag in ("td", "th")]
    return cells[best] if best is not None and best < len(cells) else None


def suggest_field(items: list, description: str) -> dict | None:
    """The best selector for one requested field, or None if nothing on the page fits."""
    kind = _kind(description)
    name = field_name(description)
    words = [w for w in re.findall(r"[a-z]{3,}", description.lower()) if w not in {"the", "each", "and", "link", "url"}] or [name]
    first = items[0]
    ranked = sorted(_candidates(first), key=lambda el: -_score(el, kind, words))
    header_cell = _column_from_header(items, re.findall(r"[a-z]{2,}", description.lower()))
    if header_cell is not None:
        ranked.insert(0, header_cell)
    blank = {"name": name, "selector": "", "attr": "text", "type": "string", "source": "list", "multiple": False,
             "required": False, "regex": None, "value_map": None}

    for el in ranked[:8]:
        if el is not header_cell and _score(el, kind, words) <= 0:
            break
        spec = dict(blank)
        if kind == "tags":
            target = el if el.tag == "a" else (el.cssselect("a") or [el])[0]
            sel = _relative_selector(first, target)
            if sel is None:
                continue
            spec.update(selector=sel, multiple=True)
        else:
            sel = _relative_selector(first, el)
            if sel is None:
                continue
            spec["selector"] = sel
        if kind == "price":
            spec["type"] = "price"
        elif kind == "number":
            spec["type"] = "integer" if _all_integers(items, spec) else "number"
        elif kind == "image":
            img = el if el.tag == "img" else (el.cssselect("img") or [None])[0]
            if img is None:
                continue
            spec.update(selector=_relative_selector(first, img) or spec["selector"], attr="src", type="url")
        elif kind == "url":
            a = el if el.tag == "a" else (el.cssselect("a[href]") or [None])[0]
            if a is None:
                continue
            spec.update(selector=_relative_selector(first, a) or spec["selector"], attr="href", type="url")
        elif kind == "title" and el.tag == "a" and el.get("title") and len(el.get("title")) >= len(_text(el)):
            spec["attr"] = "title"
        elif kind == "title" and el.cssselect("a[title]"):
            a = el.cssselect("a[title]")[0]
            spec.update(selector=_relative_selector(first, a) or spec["selector"], attr="title")
        elif kind == "rating":
            words_in_class = [c for c in _classes(el) if c in NUMBER_WORDS]
            if words_in_class:
                spec.update(attr="class", type="integer", regex=r"\b(One|Two|Three|Four|Five)\b", value_map=dict(NUMBER_WORDS))
            else:
                spec["type"] = "number"
        elif kind == "in_stock":
            spec.update(type="boolean", regex=r"\bin stock\b|\bavailable\b")
        # Must work across items, not just the first one.
        filled = sum(1 for it in items[:10] if _matches(it, spec))
        if filled >= max(1, int(0.6 * min(10, len(items)))):
            return spec
    return None


def _all_integers(items: list, spec: dict) -> bool:
    from app.scraper.extract import parse_number

    values = []
    for it in items[:10]:
        nodes = it.cssselect(spec["selector"]) if spec["selector"] else [it]
        if nodes:
            values.append(parse_number(_text(nodes[0])))
    return bool(values) and all(v is not None and float(v).is_integer() for v in values)


def _matches(item, spec: dict) -> bool:
    try:
        nodes = item.cssselect(spec["selector"]) if spec["selector"] else [item]
    except Exception:  # noqa: BLE001
        return False
    if not nodes:
        return False
    if spec["attr"] in ("text", "html"):
        return bool(_text(nodes[0]))
    return bool(nodes[0].get(spec["attr"]))


def find_next_page(doc) -> str | None:
    for li in doc.cssselect("li.next"):
        if li.cssselect("a[href]"):
            return "li.next a"
    if doc.cssselect("a[rel~=next][href]"):
        return 'a[rel~="next"]'
    for a in doc.cssselect("a[href]"):
        label = (a.get("aria-label") or "").lower()
        text = _text(a).lower()
        if label == "next":
            return f'a[aria-label="{a.get("aria-label")}"]'
        if re.fullmatch(r"(next( page)?|›|»|>|→)\s*(›|»|>|→)?", text):
            cls = _meaningful(a)
            if cls:
                return f"a.{cls[0]}"
            parent = a.getparent()
            if parent is not None and _meaningful(parent):
                return f"{parent.tag}.{_meaningful(parent)[0]} a"
    return None


def suggest_config(page_html: str, descriptions: list[str], page_kind: str = "list") -> tuple[dict, list[str]]:
    """A config dict (ScraperConfig shape) and notes explaining what was guessed."""
    notes: list[str] = []
    doc = html.fromstring(page_html)
    for el in list(doc.iter("script", "style", "noscript", etree.Comment)):
        if el.getparent() is not None:
            el.drop_tree()

    if page_kind == "detail":
        item_selector, items = "", [doc]
    else:
        found = find_items(doc)
        if found is None:
            notes.append("No repeating items found, so the whole page is treated as one item.")
            item_selector, items = "", [doc]
        else:
            item_selector, items = found
            notes.append(f"Found {len(items)} repeating items matching “{item_selector}”.")

    fields = []
    for desc in descriptions:
        spec = suggest_field(items, desc)
        if page_kind == "detail":
            spec["source"] = "detail"
        if not spec["selector"] and item_selector:
            notes.append(f"Couldn't find “{desc}”; check it in the preview and set its selector by hand.")
        fields.append(spec)
    # Keep names unique.
    seen: Counter = Counter()
    for f in fields:
        seen[f["name"]] += 1
        if seen[f["name"]] > 1:
            f["name"] = f"{f['name']}_{seen[f['name']]}"

    next_sel = find_next_page(doc) if page_kind == "list" else None
    if next_sel:
        notes.append(f"Pagination: follows “{next_sel}”.")
    keys = [f["name"] for f in fields if f["type"] == "url" and f["attr"] == "href"][:1] or \
        [f["name"] for f in fields if _kind(f["name"].replace("_", " ")) == "title"][:1]
    for f in fields:
        if f["name"] in keys:
            f["required"] = True
    return {
        "item_selector": item_selector,
        "fields": fields,
        "next_page_selector": next_sel,
        "key_fields": keys,
    }, notes
