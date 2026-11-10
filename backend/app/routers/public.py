"""Pages served outside the API: robots.txt, the crawler's info page and the practice store."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from app import practice
from app.scraper.policy import BOT_NAME

router = APIRouter(include_in_schema=False)


def _today() -> date:
    return datetime.now(timezone.utc).date()


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return practice.ROBOTS_TXT


@router.get("/bot", response_class=HTMLResponse)
def bot_info():
    """Linked from the crawler's User-Agent, so site owners can see who is visiting and how to opt out."""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{BOT_NAME}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.55;color:#222}}</style></head>
<body><h1>About {BOT_NAME}</h1>
<p>{BOT_NAME} is the crawler of Gleaner, a data-collection platform. Each request's User-Agent includes a contact
email for the team running it.</p>
<h2>How it behaves</h2><ul>
<li>It reads and obeys <code>robots.txt</code>, including <code>Crawl-delay</code>, for the token <code>{BOT_NAME}</code> and for <code>*</code>.</li>
<li>It only visits sites a workspace admin has reviewed and approved, at a limited request rate per site.</li>
<li>It backs off on HTTP 429 and 5xx responses and honours <code>Retry-After</code>.</li>
<li>It does not log in, solve CAPTCHAs, or rotate identities to avoid blocks.</li></ul>
<h2>Opting out</h2><p>Add this to your <code>robots.txt</code>:</p>
<pre>User-agent: {BOT_NAME}
Disallow: /</pre>
<p>Or email the contact address in the User-Agent string you saw in your logs.</p></body></html>"""


@router.get(practice.BASE, response_class=HTMLResponse)
def store_listing(page: int = 1, category: str | None = None):
    body = practice.render_listing(_today(), page, category if category in practice.CATEGORIES else None)
    if body is None:
        raise HTTPException(404, "No such page")
    return body


@router.get(practice.BASE + "/p/{slug}", response_class=HTMLResponse)
def store_product(slug: str):
    body = practice.render_product(_today(), slug)
    if body is None:
        raise HTTPException(404, "This product isn't available")
    return body


@router.get(practice.BASE + "/{path:path}", response_class=HTMLResponse)
def store_private(path: str):
    # Basket and account pages: disallowed in robots.txt, and not something a crawler should touch.
    return HTMLResponse("<h1>Sign in required</h1>", status_code=401)
