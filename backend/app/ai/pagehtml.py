"""Shrink a page's HTML to what matters for choosing selectors.

Scripts, styles, SVG and most attributes go; long text is shortened; long runs of
same-shaped siblings (the 20th product card) are cut to the first few. A typical
listing page drops from ~50 KB to a few KB, which keeps AI calls cheap and focused.
"""
import re

from lxml import etree, html

KEEP_ATTRS = {"class", "id", "href", "src", "alt", "title", "rel", "itemprop", "itemtype", "aria-label", "datetime", "content", "name", "type", "value"}
DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "link", "meta", "template", "canvas", "path"]
MAX_TEXT = 100
MAX_SAME_SIBLINGS = 4
DEFAULT_LIMIT = 40_000


def _signature(el) -> tuple:
    return (el.tag, el.get("class", ""))


def simplify(page_html: str, limit: int = DEFAULT_LIMIT) -> str:
    try:
        doc = html.fromstring(page_html)
    except (etree.ParserError, ValueError):
        return page_html[:limit]
    for el in list(doc.iter(*DROP_TAGS)):
        if el.getparent() is not None:
            el.drop_tree()
    for el in list(doc.iter(etree.Comment)):
        if el.getparent() is not None:
            el.drop_tree()
    head = doc.find("head")
    if head is not None:
        title = head.findtext("title")
        head.clear()
        if title:
            etree.SubElement(head, "title").text = title.strip()

    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            if attr not in KEEP_ATTRS and not attr.startswith("data-"):
                del el.attrib[attr]
            elif attr in ("href", "src") and len(el.attrib[attr]) > 120:
                el.attrib[attr] = el.attrib[attr][:120] + "..."
        if el.text and len(el.text.strip()) > MAX_TEXT:
            el.text = el.text.strip()[:MAX_TEXT] + "..."
        if el.tail and len(el.tail.strip()) > MAX_TEXT:
            el.tail = el.tail.strip()[:MAX_TEXT] + "..."

    # Keep a few examples of each repeated sibling shape, and note how many there were.
    for parent in list(doc.iter()):
        if not isinstance(parent.tag, str):
            continue
        groups: dict[tuple, list] = {}
        for child in parent:
            if isinstance(child.tag, str):
                groups.setdefault(_signature(child), []).append(child)
        for sig, members in groups.items():
            if len(members) > MAX_SAME_SIBLINGS + 1:
                for extra in members[MAX_SAME_SIBLINGS:]:
                    parent.remove(extra)
                note = etree.Comment(f" {len(members) - MAX_SAME_SIBLINGS} more <{sig[0]}> like the above ")
                members[MAX_SAME_SIBLINGS - 1].addnext(note)

    out = etree.tostring(doc, encoding="unicode", method="html")
    out = re.sub(r"\n\s*\n+", "\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    if len(out) > limit:
        out = out[:limit] + "\n<!-- page truncated -->"
    return out
