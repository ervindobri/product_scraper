---
name: add-scraper
description: Add a new site/store scraper to product_scraper (scrapers.py + SCRAPERS registry). Trigger whenever the user asks to add a new site, store, or shop to the scraper, e.g. "add support for X.hu", "scrape Y.de too", "add a new scraper for Z".
disable-model-invocation: false
---

# Add a new site scraper to product_scraper

This project (`f:\Projects\product_scraper`) is a Tkinter price-comparison tool that
fans a search query out to many per-site scraper functions in `scrapers.py`, registered
in the `SCRAPERS` list at the bottom of that file. `main.py` never needs to change when
adding a site — it drives everything off `SCRAPERS` and `SCRAPER_REGIONS`.

Follow these steps in order. Don't skip the investigation step — guessing the HTML
structure wastes more time than checking it once.

## 1. Gather inputs

Determine, from the user's request or by asking:
- Site name and base URL (e.g. `https://www.example.hu`)
- Region code: `hu` (Hungary), `de` (Germany/DACH), `it` (Italy), `nl` (Netherlands),
  or a new code if it's a genuinely new country. Any region `!= "hu"` automatically
  shows up under the "International (EU)" filter in the GUI — no `main.py` changes
  needed regardless of which region code you pick.

## 2. Investigate the site before writing code

Fetch a real search-results page for a test query and inspect it — don't assume a
technique. Order of attempts:

1. **Plain `requests`** with `create_session()` (from `scrapers.py`). Many sites
   (classifieds, some Next.js shops) work fine with no special handling — don't
   reach for `cloudscraper` unless plain requests actually gets blocked.
2. If you get HTTP 403/503/511 or a CAPTCHA page, switch to
   `cloudscraper.create_scraper()` (Cloudflare bypass) — used for Alza, eMAG,
   MediaMarkt, Alternate.de, etc.
3. Check the URL: try both `www.` and bare domain if one redirects unexpectedly
   or serves a client-only SPA shell (`hardverapro.hu` and `jofogas.hu` both
   redirect/break under `www.`).

Then find where the product data actually lives in the response — check in this order,
as they cover essentially every site seen so far:
- `<script type="application/ld+json">` with `@type: Product` or `@type: ItemList`
  (iStyle, MediaMarkt)
- `<script id="__NEXT_DATA__">` JSON blob (Next.js apps — Marktplaats)
- A `data-*` HTML attribute holding HTML-encoded JSON, e.g. `data-initialdata`
  (Alza — needs `html.unescape()` before `json.loads()`)
- Plain server-rendered HTML with CSS classes/selectors via BeautifulSoup
  (eMAG `.card-v2`, Jófogás `.reListItem`, Hardverapró `li.media`)

If none of these yield data, the site is probably a pure client-rendered SPA
(Vatera, Euronics, Árukereső were all rejected for this reason) — confirm with the
user before spending more time, and consider a `scrape_x` that just raises a clear
`RuntimeError` explaining why, matching the `scrape_vatera` pattern.

## 3. Write the scraper function

Add a new function in `scrapers.py`, grouped near scrapers for the same region,
following this contract exactly:

```python
def scrape_example(query: str, session: requests.Session) -> list[dict]:
    """
    One-line note on the technique used (mirrors the module docstring style),
    e.g.: "Example.hu — requests + JSON-LD Product scripts."
    """
    url = f"https://www.example.hu/search?q={urllib.parse.quote(query)}"
    r = session.get(url, timeout=15)          # or cs.get(...) if using cloudscraper
    _check_response(r, "Example.hu")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for card in soup.select(".product-card"):
        name_el = card.select_one(".product-name")
        price_el = card.select_one(".product-price")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        price = _clean(price_el.get_text()) if price_el else "N/A"
        href = name_el.get("href", "")
        results.append({"site": "Example.hu", "name": name, "price": price, "url": href})

    return results[:20]
```

Rules:
- Signature is always `(query: str, session_or_underscore) -> list[dict]`. Name the
  second param `_session` if you create your own `cloudscraper` instance inside the
  function instead of using the shared one (see `scrape_alza`, `scrape_emag`).
- Every result dict has exactly `site`, `name`, `price`, `url` keys.
- **Price currency**: for `region == "hu"`, return HUF strings (e.g. `"149 900 Ft"`).
  For any other region, return the price in the site's **native currency as shown**
  (e.g. `"€ 1.299,00"`) — do **not** convert to HUF yourself. `main.py` calls
  `convert_eur_price()` automatically for every non-`hu` result after your function
  returns. Converting manually would double-convert.
- Use `_clean()` on all extracted text to collapse whitespace/`\xa0`.
- Use `_check_response(r, "Site.hu")` right after the request — it raises readable
  `RuntimeError`s for CAPTCHA/403/503 so the GUI shows "Site.hu: error" instead of a
  raw traceback.
- Cap results at a sane limit (existing scrapers use `[:20]`).
- Never raise on "just no results" — return `[]`. Only raise for actual
  fetch/parse failures (network error, blocked, unexpected page structure).
- Accept-Encoding must not include `br` (brotli) if you build custom headers instead
  of reusing `HEADERS`/`create_session()` — `requests` can't decode brotli without
  the optional `brotli` package installed.

## 4. Register it

Add a tuple to the `SCRAPERS` list near the bottom of `scrapers.py`, in the section
comment for its region (add a new `# ── Region ──` comment block if it's a new region):

```python
SCRAPERS: list[tuple[str, str, callable]] = [
    ...
    ("Example.hu", "hu", scrape_example),
]
```

`SCRAPER_REGIONS` is derived automatically from this list — nothing else to touch.

## 5. Test standalone before wiring into the GUI

Run the new function directly, e.g.:

```bash
python -c "from scrapers import scrape_example, create_session; import json; print(json.dumps(scrape_example('iphone', create_session()), indent=2, ensure_ascii=False))"
```

(swap `create_session()` for `cloudscraper.create_scraper()` if that's what the
function uses). Confirm: non-empty results for a common query, `name`/`price`/`url`
all populated and sane, and no exception on an empty-result query.

Only after that works should you launch `main.py` to confirm it shows up correctly in
the GUI (badge shows a result count, region filters include/exclude it correctly).

## 6. Update the module docstring (optional but keep it short)

The top-of-file docstring in `scrapers.py` lists site → technique. Add a one-line
entry there too if you're touching that area anyway; don't do a big sweep to
backfill unrelated missing entries.
