"""Ridgeline Outfitters: a fictional outdoor-gear store served by this backend.

It exists so the crawler has a site that is (a) ours to scrape, and (b) actually changes:
prices move weekly, sales come and go, stock levels shift, products launch and are
discontinued, and now and then a pricing glitch appears for a day. Everything is a pure
function of the date, so any day can be rendered again exactly (the demo history is
built this way).
"""
import hashlib
import html
import math
from dataclasses import dataclass
from datetime import date

PAGE_SIZE = 12
EPOCH = date(2026, 1, 1).toordinal()
BASE = "/practice/store"

CATEGORIES = ["Tents", "Backpacks", "Sleeping bags", "Footwear", "Jackets", "Camp kitchen"]
BRANDS = ["Summit & Pine", "Northbound", "Cairn Works", "Alder", "Fellwalker", "Bluewater"]
CATALOG_SPEC = {
    "Tents": [("Summit 4 Expedition Tent", 389), ("Ridge 2 Backpacking Tent", 249), ("Trailhead 1 Solo Shelter", 159),
              ("Basecamp 6 Family Tent", 429), ("Ultralight Tarp 3x3", 79), ("Storm Dome 3", 319), ("Canopy Day Shelter", 119),
              ("Alpine Bivy", 189), ("Meadow 4 Cabin Tent", 299)],
    "Backpacks": [("Traverse 65L Pack", 219), ("Daybreak 22L Daypack", 89), ("Scramble 35L", 139), ("Hydro 12L Vest", 99),
                  ("Expedition 80L", 289), ("Commuter 28L", 109), ("Kids' Trail 15L", 49), ("Fastpack 40L", 179), ("Summit Bag 18L", 69)],
    "Sleeping bags": [("Polar -15 Down Bag", 459), ("Three Season 0°C Bag", 189), ("Summer Liner", 39), ("Synthetic -5 Bag", 149),
                      ("Double Camper Bag", 219), ("Quilt 750", 279), ("Kids' Explorer Bag", 59), ("Mummy 900 Down", 529), ("Travel Bag 10°C", 79)],
    "Footwear": [("Ridgeline Mid GTX Boot", 179), ("Trail Runner 3", 129), ("Approach Shoe", 139), ("Winter Hike Boot", 219),
                 ("Camp Slide", 35), ("Mountaineering Boot", 389), ("Wading Shoe", 89), ("Women's Trek Low", 149), ("Kids' Hiker", 69)],
    "Jackets": [("Stormshell Rain Jacket", 249), ("Down Puffer 800", 289), ("Fleece Midlayer", 89), ("Softshell Hoodie", 149),
                ("Insulated Parka", 349), ("Wind Shell", 99), ("Hybrid Vest", 119), ("Alpine Hardshell Pro", 449), ("Packable Rain Poncho", 39)],
    "Camp kitchen": [("Titanium Stove", 69), ("Two-Burner Camp Stove", 149), ("Cookset 4-Person", 89), ("Water Filter Pump", 99),
                     ("Insulated Mug", 25), ("Collapsible Sink", 29), ("Cold Brew Press", 45), ("Camp Table", 119), ("Cooler 45L", 229)],
}
# Product index -> (launch day offset, discontinued day offset) from EPOCH, for a few products.
LIFECYCLE = {
    "Fastpack 40L": (290, None),  # launches late October 2026
    "Quilt 750": (285, None),
    "Cold Brew Press": (280, None),
    "Kids' Hiker": (None, 286),  # discontinued
    "Packable Rain Poncho": (None, 291),
}


def _h(*parts) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name.replace("'", "").replace("°", "")).strip("-").replace("--", "-")


@dataclass
class Product:
    sku: str
    slug: str
    name: str
    brand: str
    category: str
    base_price: int
    rating: float
    base_reviews: int
    weight_g: int


def _catalog() -> list[Product]:
    out, n = [], 1001
    for category, items in CATALOG_SPEC.items():
        for name, price in items:
            h = _h(name)
            out.append(Product(
                sku=f"RL-{n}", slug=_slug(name), name=name, brand=BRANDS[h % len(BRANDS)], category=category,
                base_price=price, rating=round(3.4 + (h % 16) / 10, 1), base_reviews=20 + h % 400, weight_g=150 + h % 4200,
            ))
            n += 1
    return out


CATALOG = _catalog()
BY_SLUG = {p.slug: p for p in CATALOG}


def available(p: Product, day: date) -> bool:
    launch, end = LIFECYCLE.get(p.name, (None, None))
    offset = day.toordinal() - EPOCH
    return (launch is None or offset >= launch) and (end is None or offset < end)


@dataclass
class Offer:
    price: float
    was: float | None
    stock: int
    reviews: int

    @property
    def stock_label(self) -> str:
        if self.stock <= 0:
            return "Out of stock"
        if self.stock <= 5:
            return f"Only {self.stock} left"
        return "In stock"


def offer(p: Product, day: date) -> Offer:
    d = day.toordinal()
    h = _h(p.sku)
    # Repricing roughly every two weeks per product (staggered), within ±8%; often unchanged.
    block = (d + h % 14) // 14
    step = _h(p.sku, "price", block) % 17 - 8
    factor = 1 + (step if _h(p.sku, "reprice", block) % 3 else 0) / 100
    regular = max(9.99, math.floor(p.base_price * factor) + 0.99)
    sale_pct = 0
    if _h(p.sku, "sale", (d + h % 10) // 10) % 100 < 12:  # ~12% of products on a 10-day sale at a time
        sale_pct = (15, 20, 25, 30)[_h(p.sku, "pct", (d + h % 10) // 10) % 4]
    price = round(regular * (1 - sale_pct / 100), 2) if sale_pct else regular
    if _h(p.sku, "glitch", d) % 450 == 0:  # a one-day pricing error (decimal slip)
        price = round(price / 10, 2)
    # Stock is restocked/sold down weekly per product.
    stock = _h(p.sku, "stock", (d + h % 7) // 7) % 40 - 8
    reviews = p.base_reviews + max(0, d - EPOCH) // (12 + h % 10)
    return Offer(price=price, was=regular if sale_pct else None, stock=stock, reviews=reviews)


def products_on(day: date, category: str | None = None) -> list[Product]:
    return [p for p in CATALOG if available(p, day) and (category is None or p.category == category)]


# ---- HTML ----

STYLE = """
body{font-family:system-ui,sans-serif;margin:0;color:#1f2a24;background:#f6f5f0}
header{background:#24382c;color:#fff;padding:14px 24px;display:flex;gap:24px;align-items:center}
header a{color:#d8e6dc;text-decoration:none;font-size:14px} .logo{font-weight:700;font-size:18px;color:#fff}
main{max-width:1100px;margin:0 auto;padding:24px} .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.product-card{background:#fff;border:1px solid #e3e1d8;border-radius:10px;padding:14px}
.thumb{height:120px;border-radius:6px;margin-bottom:10px} .product-name{font-size:15px;margin:0 0 4px}
.product-name a{color:inherit;text-decoration:none} .brand{color:#6b746e;font-size:13px;margin:0 0 8px}
.price-now{font-weight:700;font-size:17px} .price-was{color:#8a8f8a;margin-left:6px;font-size:13px}
.stock{font-size:13px;margin:6px 0} .out-of-stock{color:#b3261e} .low-stock{color:#a15c00} .in-stock{color:#2e7d32}
.rating{font-size:13px;color:#6b746e} .pagination{display:flex;gap:12px;margin-top:24px;align-items:center}
.pagination a{color:#24382c} .notice{background:#fff8e1;border:1px solid #f0dca0;padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:16px}
dl.specs{display:grid;grid-template-columns:140px 1fr;gap:6px 12px} dt{color:#6b746e}
.cats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px} .cats a{font-size:13px;color:#24382c}
"""

COLORS = ["#c9d8c5", "#d8cfc0", "#c5d3dc", "#dccbc5", "#d4d9c3", "#cfc8dc"]


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)} | Ridgeline Outfitters</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{STYLE}</style></head><body>
<header><a class="logo" href="{BASE}">Ridgeline Outfitters</a><a href="{BASE}">Shop</a><a href="{BASE}/cart">Basket</a><a href="{BASE}/account">Account</a></header>
<main><p class="notice">Practice store for the Gleaner demo. Products and prices are fictional and change daily.</p>{body}</main></body></html>"""


def _money(v: float) -> str:
    return f"£{v:,.2f}"


def _card(p: Product, o: Offer) -> str:
    stock_cls = "out-of-stock" if o.stock <= 0 else "low-stock" if o.stock <= 5 else "in-stock"
    was = f'<s class="price-was">{_money(o.was)}</s>' if o.was else ""
    url = f"{BASE}/p/{p.slug}"
    return f"""<article class="product-card" data-sku="{p.sku}">
<a href="{url}" class="thumb-link"><div class="thumb" style="background:{COLORS[CATEGORIES.index(p.category)]}"></div></a>
<h2 class="product-name"><a href="{url}">{html.escape(p.name)}</a></h2>
<p class="brand">{html.escape(p.brand)}</p>
<div class="price"><span class="price-now">{_money(o.price)}</span>{was}</div>
<p class="stock {stock_cls}">{o.stock_label}</p>
<div class="rating" data-rating="{p.rating}">{"★" * round(p.rating)}{"☆" * (5 - round(p.rating))} {p.rating} <span class="reviews">({o.reviews} reviews)</span></div>
</article>"""


def render_listing(day: date, page: int = 1, category: str | None = None) -> str | None:
    products = products_on(day, category)
    pages = max(1, math.ceil(len(products) / PAGE_SIZE))
    if page < 1 or page > pages:
        return None
    chunk = products[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    cats = "".join(f'<a href="{BASE}?category={html.escape(c)}">{html.escape(c)}</a>' for c in CATEGORIES)
    q = f"&category={html.escape(category)}" if category else ""
    prev_link = f'<a class="prev" rel="prev" href="{BASE}?page={page - 1}{q}">‹ Previous</a>' if page > 1 else ""
    next_link = f'<a class="next" rel="next" href="{BASE}?page={page + 1}{q}">Next ›</a>' if page < pages else ""
    body = f"""<h1>{html.escape(category or "All gear")}</h1><nav class="cats">{cats}</nav>
<p class="result-count">{len(products)} products</p>
<section class="grid">{"".join(_card(p, offer(p, day)) for p in chunk)}</section>
<nav class="pagination">{prev_link}<span class="page-status">Page {page} of {pages}</span>{next_link}</nav>"""
    return _page(category or "All gear", body)


def render_product(day: date, slug: str) -> str | None:
    p = BY_SLUG.get(slug)
    if p is None or not available(p, day):
        return None
    o = offer(p, day)
    was = f'<s class="price-was">{_money(o.was)}</s>' if o.was else ""
    stock_cls = "out-of-stock" if o.stock <= 0 else "low-stock" if o.stock <= 5 else "in-stock"
    desc = (f"The {p.name} from {p.brand} is built for {p.category.lower()} use in all conditions, "
            f"tested on long days in the hills and priced for people who actually go outside.")
    body = f"""<nav class="breadcrumbs"><a href="{BASE}">Shop</a> › <a href="{BASE}?category={html.escape(p.category)}" class="category">{html.escape(p.category)}</a></nav>
<div class="product-detail" itemscope itemtype="https://schema.org/Product">
<h1 class="product-title" itemprop="name">{html.escape(p.name)}</h1>
<p class="brand" itemprop="brand">{html.escape(p.brand)}</p>
<div class="price"><span class="price-now" itemprop="price">{_money(o.price)}</span>{was}</div>
<p class="stock {stock_cls}">{o.stock_label}</p>
<div class="description" itemprop="description"><p>{html.escape(desc)}</p></div>
<dl class="specs"><dt>SKU</dt><dd class="sku" itemprop="sku">{p.sku}</dd><dt>Weight</dt><dd class="weight">{p.weight_g:,} g</dd>
<dt>Category</dt><dd>{html.escape(p.category)}</dd><dt>Rating</dt><dd class="rating" data-rating="{p.rating}">{p.rating} / 5 ({o.reviews} reviews)</dd></dl>
</div>"""
    return _page(p.name, body)


ROBOTS_TXT = """# Gleaner demo server
User-agent: *
Disallow: /api/
Disallow: /practice/store/cart
Disallow: /practice/store/account
Allow: /practice/
"""
