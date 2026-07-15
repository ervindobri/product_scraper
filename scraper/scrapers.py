"""
Per-site scraping logic.

Approach per site:
  Alza.hu/.cz/.de/.at/.sk - cloudscraper (Cloudflare bypass) + parse data-initialdata JSON
  eMAG.hu/.ro    - cloudscraper + HTML (.card-v2 structure)
  MediaMarkt.hu  - cloudscraper + JSON-LD ItemList
  iStyle.hu      - requests + individual JSON-LD Product scripts
  Jófogás.hu     - requests + .reListItem (classifieds)
  Hardverapró    - requests + li.media/.uad-col-title (classifieds)
  Vatera.hu      - JavaScript-rendered; raises informative error
  Kleinanzeigen.de - requests + article.aditem (classifieds)
  Alternate.de/.fr/.es/.nl/.at - requests + a.productBox HTML cards (.de via cloudscraper)
  Coolblue.nl/.de - cloudscraper + HTML product cards, JSON-LD ItemList fallback
  Morele.net     - requests + .cat-product HTML cards (Poland)
  Compumsa.eu    - requests + ASP.NET GridView search results (Belgium)
  Notebooksbilliger.de - Akamai Bot Manager blocks all pages; raises informative error
  LDLC.com       - requests + server-rendered li.pdt-item search cards
  Azerty.nl      - Cloudflare managed challenge blocks all pages; raises informative error
  Megekko.nl     - custom JS bot-challenge blocks all pages; raises informative error
  Webhallen.se   - requests + JSON API (productdiscovery/search endpoint), prices in SEK
  Coolmod.com    - requests + Doofinder JSON search API
  BPM-Power.com  - requests to Doofinder JSON search API (site itself blocked by Cloudflare)
"""

import io
import re
import json
import html
import time
import threading
import contextlib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed

import requests
import cloudscraper
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _check_response(r: requests.Response, site: str) -> None:
    """Raise with a readable message for bot-detection responses."""
    if r.status_code == 511 or "captcha" in r.text[:500].lower():
        raise RuntimeError(f"{site}: CAPTCHA / WAF block — try again in a few minutes")
    if r.status_code == 403:
        raise RuntimeError(f"{site}: 403 Forbidden — bot detection active")
    if r.status_code == 503:
        raise RuntimeError(f"{site}: 503 — bot detection / temporary block")
    r.raise_for_status()


def extract_numeric_price(price_str: str) -> int:
    """
    Return an integer for numeric sort — uses only the part before any
    '(' bracket, and only the FIRST number in it (some listings show
    "829 990 Ft 774 990 Ft" — original + discounted price in one string).
    A trailing 1-2 digit decimal fraction (",00" / ".50") is dropped.
    """
    huf_part = price_str.split("(")[0]
    m = re.search(r"\d[\d\s.,\xa0]*", huf_part)
    if not m:
        return 0
    s = m.group(0).strip()
    s = re.sub(r"[.,]\d{1,2}$", "", s)   # decimal fraction, not thousands
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


# ---------------------------------------------------------------------------
# FX → HUF conversion  (rates cached per currency with a TTL, so long-running
# processes — like the Django server — don't serve stale rates forever)
# ---------------------------------------------------------------------------
RATE_TTL_SECONDS = 24 * 3600
_RATE_RETRY_SECONDS = 300   # how soon to retry after a failed fetch

# used when the rate API is unreachable
_FALLBACK_HUF_RATES = {"EUR": 400.0, "PLN": 95.0, "SEK": 36.0, "CZK": 16.0, "RON": 80.0}

_huf_rates: dict[str, tuple[float, float]] = {}   # currency -> (rate, fetched_at)
_huf_rates_lock = threading.Lock()


def get_huf_rate(currency: str) -> float:
    """Return the <currency>→HUF rate, cached for RATE_TTL_SECONDS."""
    currency = (currency or "HUF").upper()
    if currency == "HUF":
        return 1.0
    now = time.monotonic()
    with _huf_rates_lock:
        cached = _huf_rates.get(currency)
        if cached and now - cached[1] < RATE_TTL_SECONDS:
            return cached[0]
        try:
            r = requests.get(
                f"https://api.frankfurter.app/latest?from={currency}&to=HUF",
                timeout=5,
            )
            rate = float(r.json()["rates"]["HUF"])
            _huf_rates[currency] = (rate, now)
        except Exception:
            rate = _FALLBACK_HUF_RATES.get(currency, 1.0)
            # cache the fallback only briefly so a live rate is retried soon
            _huf_rates[currency] = (rate, now - RATE_TTL_SECONDS + _RATE_RETRY_SECONDS)
        return rate


def _get_eur_huf_rate() -> float:
    return get_huf_rate("EUR")


# one shared Cloudflare-solving session — creating it is expensive, so reuse
_cloudscraper_cache: list = []   # holds at most one instance
_cloudscraper_lock = threading.Lock()


def get_cloudscraper():
    with _cloudscraper_lock:
        if not _cloudscraper_cache:
            _cloudscraper_cache.append(cloudscraper.create_scraper())
        return _cloudscraper_cache[0]


def convert_eur_price(price_str: str) -> str:
    """
    Parse a price string in EUR and return "X XXX Ft (Y €)".

    Handles all formats seen across EU stores:
      "€ 2.049,00"   (German/Austrian: period=thousands, comma=decimal)
      "1 299.00 EUR"  (ISO)
      "1.399,-"      (Dutch: period=thousands, dash=.00)
      "€ 1069,00"    (Austrian: comma=decimal only)

    If the string already contains "Ft" or "HUF" it is returned unchanged
    (e.g. Amazon showing HUF prices to Hungarian visitors).
    """
    if not price_str or price_str == "N/A":
        return price_str
    if "Ft" in price_str or "HUF" in price_str.upper():
        return price_str

    s = price_str.upper().replace("EUR", "").replace("€", "").strip()
    s = s.replace(",-", "")   # Dutch "1.399,-" → "1.399"
    s = re.sub(r"\s+", "", s) # remove all whitespace

    if "." in s and "," in s:
        # Both separators: European (. = thousands, , = decimal) → "2049.00"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Comma only: decimal separator "1069,00" → "1069.00"
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            # Period with 3-digit fraction → thousands separator "1399"
            s = s.replace(".", "")

    s = re.sub(r"[^\d.]", "", s)
    try:
        eur = float(s)
    except (ValueError, TypeError):
        return price_str   # unparseable: show as-is

    huf = round(eur * _get_eur_huf_rate() / 10) * 10   # round to nearest 10 Ft
    huf_str = f"{int(huf):,}".replace(",", " ") + " Ft"
    eur_str = f"{int(round(eur)):,}".replace(",", " ") + " €"
    return f"{huf_str} ({eur_str})"


_DIACRITICS = str.maketrans(
    "áéíóöőúüűÁÉÍÓÖŐÚÜŰ",
    "aeiooouuuAEIOOOUUU",
)


def _normalize(text: str) -> str:
    text = text.lower().translate(_DIACRITICS)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_relevance(query: str, name: str) -> int:
    """Return 0-100: share of query words found (as exact words) in product name."""
    q_tokens = _normalize(query).split()
    if not q_tokens:
        return 0
    n_words = set(_normalize(name).split())
    matched = sum(1 for t in q_tokens if t in n_words)
    return round(matched / len(q_tokens) * 100)


# ---------------------------------------------------------------------------
# Alza.hu / .cz / .de / .at / .sk — one platform, per-country domains
# ---------------------------------------------------------------------------
def _scrape_alza_domain(site: str, domain: str, query: str) -> list[dict]:
    """
    Alza is a React SPA protected by Cloudflare. The product list is server-side
    rendered inside a data-initialdata attribute as HTML-encoded JSON. Every
    country domain uses the same template; item "currency" is native (HUF/CZK/EUR).
    """
    cs = get_cloudscraper()
    url = f"https://www.{domain}/search.htm?exps={urllib.parse.quote(query)}"
    r = cs.get(url, timeout=20)
    _check_response(r, site)

    # Find all data-initialdata attributes that contain an "items" array
    matches = re.findall(r'data-initialdata="([^"]*&quot;items&quot;[^"]*)"', r.text)
    if not matches:
        return []

    results = []
    seen = set()
    for raw in matches:
        try:
            data = json.loads(html.unescape(raw))
        except (json.JSONDecodeError, ValueError):
            continue

        for item in data.get("items", [])[:20]:
            name = item.get("name", "").strip()
            price_val = item.get("price")
            currency = item.get("currency", "HUF")
            url_product = item.get("url", "")

            if not name or name in seen:
                continue
            seen.add(name)

            price = f"{price_val:,} {currency}".replace(",", " ") if price_val else "N/A"
            results.append({"site": site, "name": name, "price": price, "url": url_product})

    return results


def scrape_alza(query: str, _session) -> list[dict]:
    return _scrape_alza_domain("Alza.hu", "alza.hu", query)


def scrape_alza_cz(query: str, _session) -> list[dict]:
    return _scrape_alza_domain("Alza.cz", "alza.cz", query)


def scrape_alza_de(query: str, _session) -> list[dict]:
    return _scrape_alza_domain("Alza.de", "alza.de", query)


def scrape_alza_at(query: str, _session) -> list[dict]:
    return _scrape_alza_domain("Alza.at", "alza.at", query)


def scrape_alza_sk(query: str, _session) -> list[dict]:
    return _scrape_alza_domain("Alza.sk", "alza.sk", query)


# ---------------------------------------------------------------------------
# eMAG.hu / .ro — one platform, per-country domains
# ---------------------------------------------------------------------------
def _scrape_emag_domain(site: str, domain: str, query: str) -> list[dict]:
    """eMAG uses server-side rendered .card-v2 product cards on every domain."""
    cs = get_cloudscraper()
    url = f"https://www.{domain}/search/{urllib.parse.quote(query)}/c"
    r = cs.get(url, timeout=20)
    _check_response(r, site)
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for card in soup.select(".card-v2"):
        # .card-v2-title is itself the <a> tag
        name_el = card.select_one(".card-v2-title")
        price_el = card.select_one(".product-new-price")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        href = name_el.get("href", "")
        price = _clean(price_el.get_text()) if price_el else "N/A"
        if name:
            results.append({"site": site, "name": name, "price": price, "url": href})

    return results[:20]


def scrape_emag(query: str, _session) -> list[dict]:
    return _scrape_emag_domain("eMAG.hu", "emag.hu", query)


def scrape_emag_ro(query: str, _session) -> list[dict]:
    return _scrape_emag_domain("eMAG.ro", "emag.ro", query)


# ---------------------------------------------------------------------------
# MediaMarkt.hu
# ---------------------------------------------------------------------------
def scrape_mediamarkt(query: str, _session) -> list[dict]:
    """
    MediaMarkt is Cloudflare-protected and Next.js-based. Product data is
    embedded in application/ld+json scripts as an ItemList.
    """
    cs = get_cloudscraper()
    url = f"https://www.mediamarkt.hu/hu/search.html?query={urllib.parse.quote(query)}"
    r = cs.get(url, timeout=20)
    _check_response(r, "MediaMarkt.hu")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except (json.JSONDecodeError, ValueError):
            continue

        if data.get("@type") != "ItemList":
            continue

        for entry in data.get("itemListElement", []):
            product = entry.get("item", {})
            name = product.get("name", "").strip()
            if not name:
                continue

            offers = product.get("offers", {})
            price_val = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "HUF")
            price = f"{int(price_val):,} {currency}".replace(",", " ") if price_val else "N/A"

            product_url = product.get("url", "")
            results.append({"site": "MediaMarkt.hu", "name": name, "price": price, "url": product_url})

        if results:
            break  # only need the first ItemList

    return results[:20]


# ---------------------------------------------------------------------------
# iStyle.hu
# ---------------------------------------------------------------------------
def scrape_istyle(query: str, session: requests.Session) -> list[dict]:
    """
    iStyle (Apple Premium Reseller) embeds one application/ld+json Product script
    per search result — no JS needed.
    """
    url = f"https://istyle.hu/search?q={urllib.parse.quote(query)}"
    r = session.get(url, timeout=15)
    _check_response(r, "iStyle.hu")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen = set()
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except (json.JSONDecodeError, ValueError):
            continue

        if data.get("@type") != "Product":
            continue

        name = data.get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        product_url = data.get("url") or data.get("@id", "")
        if product_url and not product_url.startswith("http"):
            product_url = f"https://istyle.hu{product_url}"

        offers = data.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_val = offers.get("price") or offers.get("lowPrice")
        currency = offers.get("priceCurrency", "HUF")
        price = f"{int(float(price_val)):,} {currency}".replace(",", " ") if price_val else "N/A"

        results.append({"site": "iStyle.hu", "name": name, "price": price, "url": product_url})

    return results[:20]


# ---------------------------------------------------------------------------
# Jófogás.hu
# ---------------------------------------------------------------------------
def scrape_jofogas(query: str, session: requests.Session) -> list[dict]:
    """
    Jófogás is Hungary's main classifieds site. Results are server-side rendered
    in .reListItem elements at jofogas.hu/search (no www — the www subdomain
    uses a React SPA without product HTML).
    """
    url = f"https://jofogas.hu/search?q={urllib.parse.quote_plus(query)}"
    r = session.get(url, timeout=15)
    _check_response(r, "Jófogás.hu")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for item in soup.select(".reListItem"):
        name_el = item.select_one("a.subject")
        link_el = item.select_one('a[href*="jofogas.hu"]')
        price_el = item.select_one(".price-value")

        if not name_el or not price_el:
            continue

        name = _clean(name_el.get_text())
        href = link_el.get("href", "") if link_el else ""
        price = _clean(price_el.get_text()) + " Ft"

        if name:
            results.append({"site": "Jófogás.hu", "name": name, "price": price, "url": href})

    return results[:20]


# ---------------------------------------------------------------------------
# Hardverapró
# ---------------------------------------------------------------------------
def scrape_hardverapro(query: str, session: requests.Session) -> list[dict]:
    """
    Hardverapró is Hungary's tech classifieds/marketplace. Results include both
    individual sellers and commercial bazaar shops.
    Note: use hardverapro.hu without www — www redirects to prohardver.hu.
    """
    url = f"https://hardverapro.hu/aprok/keres.php?stext={urllib.parse.quote_plus(query)}"
    r = session.get(url, timeout=15)
    _check_response(r, "Hardverapró")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen = set()
    for item in soup.select("li.media"):
        title_el = item.select_one(".uad-col-title a")
        price_el = item.select_one(".uad-price")

        if not title_el:
            continue

        name = _clean(title_el.get_text())
        if name in seen:
            continue
        seen.add(name)

        href = title_el.get("href", "")
        price = _clean(price_el.get_text()) if price_el else "N/A"

        if name:
            results.append({"site": "Hardverapró", "name": name, "price": price, "url": href})

    return results[:20]


# ---------------------------------------------------------------------------
# Vatera.hu
# ---------------------------------------------------------------------------
def scrape_vatera(query: str, _session) -> list[dict]:
    """
    Vatera loads listings via JavaScript AJAX (ajax_result_display container).
    The internal REST API at api.vatera.hu requires authentication.
    This scraper raises an informative error so the badge clearly explains why.
    """
    raise RuntimeError(
        "Vatera.hu: listings are JavaScript-rendered — "
        "visit vatera.hu/listings/index.php directly"
    )


# ---------------------------------------------------------------------------
# Shared helper — WooCommerce product loop
# ---------------------------------------------------------------------------
def _scrape_woocommerce(soup: BeautifulSoup, site: str) -> list[dict]:
    results = []
    seen: set[str] = set()
    for card in soup.select("li.product"):
        title_el = (card.select_one(".woocommerce-loop-product__title")
                    or card.select_one("h3") or card.select_one("h2"))
        link_el  = (card.select_one("a.woocommerce-LoopProduct-link")
                    or card.select_one("a[href]"))
        if not title_el or not link_el:
            continue
        name = _clean(title_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        href = link_el.get("href", "")
        # Prefer sale price (ins .amount); fall back to regular .amount
        price_el = (card.select_one(".price ins .amount")
                    or card.select_one(".price .amount"))
        price = _clean(price_el.get_text()) if price_el else "N/A"
        results.append({"site": site, "name": name, "price": price, "url": href})
    return results[:20]


# ---------------------------------------------------------------------------
# hasznaltalma.hu
# ---------------------------------------------------------------------------
def scrape_hasznaltalma(query: str, session: requests.Session) -> list[dict]:
    """
    hasznaltalma.hu is a Hungarian Apple classifieds marketplace.
    No keyword search — scrapes the /macbook/ category page.
    Products: <h4><a href="/mac/...">name</a></h4> then <strong>price</strong>.
    """
    r = session.get("https://hasznaltalma.hu/macbook/", timeout=15)
    _check_response(r, "hasznaltalma.hu")
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    seen: set[str] = set()
    for a in soup.select("h4 a[href]"):
        href = a.get("href", "")
        if "/mac/" not in href:
            continue
        name = _clean(a.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        url_p = f"https://hasznaltalma.hu{href}" if href.startswith("/") else href
        # The <strong> siblings immediately following <h4> hold the prices;
        # two strongs = (original, sale) — take the last one.
        h4 = a.parent
        strongs = h4.find_next_siblings("strong", limit=2)
        if strongs:
            price = _clean(strongs[-1].get_text())
            if "Ft" not in price:
                price += " Ft"
        else:
            price = "N/A"
        results.append({"site": "hasznaltalma.hu", "name": name, "price": price, "url": url_p})
    return results[:20]


# ---------------------------------------------------------------------------
# iSamurai.hu
# ---------------------------------------------------------------------------
def scrape_isamurai(query: str, session: requests.Session) -> list[dict]:
    """WooCommerce MacBook category; query used for relevance scoring only."""
    r = session.get("https://isamurai.hu/webshop/termekek/mac/macbook/", timeout=15)
    _check_response(r, "iSamurai.hu")
    return _scrape_woocommerce(BeautifulSoup(r.text, "lxml"), "iSamurai.hu")


# ---------------------------------------------------------------------------
# macszerez.com
# ---------------------------------------------------------------------------
def scrape_macszerez(query: str, session: requests.Session) -> list[dict]:
    """WooCommerce MacBook category; query used for relevance scoring only."""
    r = session.get("https://macszerez.com/termekek/macbook/", timeout=15)
    _check_response(r, "macszerez.com")
    return _scrape_woocommerce(BeautifulSoup(r.text, "lxml"), "macszerez.com")


# ---------------------------------------------------------------------------
# Rejoy.hu  (Flip.ro / Recommerce platform)
# ---------------------------------------------------------------------------
def scrape_rejoy(query: str, session: requests.Session) -> list[dict]:
    """
    Rejoy.hu uses the Flip.ro/Recommerce platform. Products are server-side
    rendered. The Apple laptop category lists all conditions; we deduplicate
    by product ID so each model appears once.
    """
    r = session.get("https://rejoy.hu/laptop/apple/", timeout=15)
    _check_response(r, "Rejoy.hu")
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if "/hu/shop/apple/" not in href:
            continue
        # Each product ID appears multiple times (one per condition variant).
        m_id = re.search(r"/(\d+)/", href)
        key = m_id.group(1) if m_id else href
        if key in seen:
            continue
        seen.add(key)
        url_p = f"https://rejoy.hu{href}" if href.startswith("/") else href
        heading = a.select_one("h2, h3, h4, h5")
        if heading:
            name = _clean(heading.get_text())
        else:
            lines = [ln.strip() for ln in a.get_text("\n").splitlines() if ln.strip()]
            name = lines[0] if lines else ""
        if not name:
            continue
        m_price = re.search(r"([\d][0-9\s.]+\s*Ft)", a.get_text(" "))
        price = _clean(m_price.group(1)) if m_price else "N/A"
        results.append({"site": "Rejoy.hu", "name": name, "price": price, "url": url_p})
    return results[:20]


# ---------------------------------------------------------------------------
# iCrew.hu  (OpenCart)
# ---------------------------------------------------------------------------
def scrape_icrew(query: str, session: requests.Session) -> list[dict]:
    """
    iCrew.hu runs OpenCart. MacBook Air and MacBook Pro have separate category
    pages; both are scraped and merged.
    """
    results = []
    seen: set[str] = set()
    for cat_url in (
        "https://icrew.hu/hasznalt-408/macbook-air-410",
        "https://icrew.hu/hasznalt-408/macbook-pro-411",
    ):
        try:
            r = session.get(cat_url, timeout=15)
            _check_response(r, "iCrew.hu")
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("h4 a[href], h5 a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            url_p = href if href.startswith("http") else f"https://icrew.hu{href}"
            name = _clean(a.get_text())
            if not name or name in seen:
                continue
            seen.add(name)
            # OpenCart caption div sits two levels up from the <a>
            cap = a.find_parent("div")
            price_el = (cap.select_one(".price-new") or cap.select_one(".price")) if cap else None
            price = _clean(price_el.get_text()) if price_el else "N/A"
            results.append({"site": "iCrew.hu", "name": name, "price": price, "url": url_p})
    return results[:20]


# ---------------------------------------------------------------------------
# almapiac.com  (Joomla classifieds)
# ---------------------------------------------------------------------------
def scrape_almapiac(query: str, session: requests.Session) -> list[dict]:
    """
    almapiac.com is a Joomla-based Apple classifieds site.
    Products: <h4><a href="/macbook/...">name</a></h4>, price as nearby text.
    """
    r = session.get("https://almapiac.com/macbook", timeout=15)
    _check_response(r, "almapiac.com")
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    seen: set[str] = set()
    for h4 in soup.select("h4"):
        a = h4.select_one("a[href]")
        if not a:
            continue
        href = a.get("href", "")
        if not href.startswith("/macbook"):
            continue
        name = _clean(a.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        url_p = f"https://almapiac.com{href}"
        container = h4.parent
        price = "N/A"
        for text in container.find_all(string=re.compile(r"\d[\d\s]*\s*Ft")):
            price = _clean(str(text))
            if "Ft" not in price:
                price += " Ft"
            break
        results.append({"site": "almapiac.com", "name": name, "price": price, "url": url_p})
    return results[:20]


# ---------------------------------------------------------------------------
# Furbify.hu
# ---------------------------------------------------------------------------
def scrape_furbify(query: str, session: requests.Session) -> list[dict]:
    """
    Furbify.hu sells refurbished Apple laptops. Product links follow the
    pattern /laptop-[brand]-[model]-[id]. Name extracted from heading or
    img alt; price from first Ft text in the link element.
    """
    r = session.get("https://www.furbify.hu/hasznalt-apple-laptop", timeout=15)
    _check_response(r, "Furbify.hu")
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href or "/laptop-" not in href:
            continue
        url_p = href if href.startswith("http") else f"https://www.furbify.hu{href}"
        if url_p in seen:
            continue
        seen.add(url_p)
        name_el = a.select_one("h3, h4, h5")
        if name_el:
            name = _clean(name_el.get_text())
        else:
            img = a.select_one("img[alt]")
            name = _clean(img.get("alt", "")) if img else ""
        if not name or len(name) < 5:
            continue
        price = "N/A"
        for text in a.find_all(string=re.compile(r"\d[\d\s]*\s*Ft")):
            price = _clean(str(text))
            if "Ft" not in price:
                price += " Ft"
            break
        if price == "N/A":
            for text in a.parent.find_all(string=re.compile(r"\d[\d\s]*\s*Ft")):
                price = _clean(str(text))
                break
        results.append({"site": "Furbify.hu", "name": name, "price": price, "url": url_p})
    return results[:20]


# ---------------------------------------------------------------------------
# iKing.hu  (ShopRenter)
# ---------------------------------------------------------------------------
def scrape_iking(query: str, session: requests.Session) -> list[dict]:
    """
    iKing.hu runs on ShopRenter. Products: <h3><a href="...">name</a></h3>
    inside <li> elements. Price format: "Ár: 89.990 Ft" or "Akciós ár: 99.990 Ft".
    """
    r = session.get("https://www.iking.hu/hasznalt-apple-macbook", timeout=15)
    _check_response(r, "iKing.hu")
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    seen: set[str] = set()
    for h3 in soup.select("h3"):
        a = h3.select_one("a[href]") or h3.find_parent("a")
        if not a:
            continue
        href = a.get("href", "")
        if not href or "iking.hu" not in href:
            continue
        name = _clean(h3.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        container = h3.find_parent("li") or h3.parent
        raw = container.get_text(" ")
        m = re.search(r"Akciós ár[:\s]+([\d.]+\s*Ft)", raw)
        if not m:
            m = re.search(r"Ár[:\s]+([\d.]+\s*Ft)", raw)
        price = _clean(m.group(1)) if m else "N/A"
        results.append({"site": "iKing.hu", "name": name, "price": price, "url": href})
    return results[:20]


# ---------------------------------------------------------------------------
# Alternate.de / .fr / .es / .nl / .at — one platform, per-country domains
# ---------------------------------------------------------------------------
def _scrape_alternate_domain(site: str, domain: str, query: str, client) -> list[dict]:
    """
    Alternate — correct search URL is /listing.xhtml?q= on every country domain.
    Each product card is an <a class='productBox'> that is also the link.
    Name in div.product-name (already includes brand); price in span.price (EUR).
    No JSON-LD on listing pages — pure HTML parsing.
    """
    url = f"https://www.{domain}/listing.xhtml?q={urllib.parse.quote_plus(query)}"
    r = client.get(url, timeout=20)
    _check_response(r, site)
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen: set[str] = set()
    for card in soup.select("a.productBox"):
        href = card.get("href", "")
        name_el = card.select_one("div.product-name")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        price_el = card.select_one("span.price")
        price = _clean(price_el.get_text()) if price_el else "N/A"
        results.append({"site": site, "name": name, "price": price, "url": href})

    return results[:20]


def scrape_alternate_de(query: str, _session) -> list[dict]:
    # .de is Cloudflare-protected — needs cloudscraper; the others don't
    return _scrape_alternate_domain("Alternate.de", "alternate.de", query, get_cloudscraper())


# ---------------------------------------------------------------------------
# Notebooksbilliger.de (NBB)
# ---------------------------------------------------------------------------
def scrape_notebooksbilliger(query: str, _session) -> list[dict]:
    """
    Notebooksbilliger.de fronts every page — search results and product pages
    alike — with an Akamai Bot Manager behavioral/sensor-data challenge
    (ak_bmsc/_abck/bm_sz cookies); confirmed blocked identically via plain
    requests, cloudscraper, and curl_cffi Chrome/Safari/Edge impersonation, so
    this raises an informative error instead of silently returning nothing.
    """
    raise RuntimeError(
        "Notebooksbilliger.de: every page is gated by an Akamai Bot Manager "
        "JS/behavioral challenge that no HTTP client can solve — "
        "visit notebooksbilliger.de directly"
    )


# ---------------------------------------------------------------------------
# Alternate.fr / .es / .nl / .at — same platform/template as Alternate.de.
# Plain requests works fine on these (no Cloudflare block encountered).
# ---------------------------------------------------------------------------
def scrape_alternate_fr(query: str, session: requests.Session) -> list[dict]:
    return _scrape_alternate_domain("Alternate.fr", "alternate.fr", query, session)


def scrape_alternate_nl(query: str, session: requests.Session) -> list[dict]:
    return _scrape_alternate_domain("Alternate.nl", "alternate.nl", query, session)


def scrape_alternate_at(query: str, session: requests.Session) -> list[dict]:
    return _scrape_alternate_domain("Alternate.at", "alternate.at", query, session)


# ---------------------------------------------------------------------------
# LDLC.com
# ---------------------------------------------------------------------------
def scrape_ldlc(query: str, session: requests.Session) -> list[dict]:
    """LDLC.com — requests + server-rendered li.pdt-item search cards."""
    url = f"https://www.ldlc.com/recherche/{urllib.parse.quote(query)}/"
    r = session.get(url, timeout=20)
    _check_response(r, "LDLC.com")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen: set[str] = set()
    for item in soup.select("li.pdt-item"):
        name_el = item.select_one("h3.title-3 a") or item.select_one(".pdt-desc a")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)

        href = name_el.get("href", "")
        url_p = f"https://www.ldlc.com{href}" if href.startswith("/") else href

        # Regular items: <div class="price"><div class="price">199€<sup>95</sup></div></div>
        # Discounted items: <div class="price"><div class="old-price">..</div><div class="new-price">9€<sup>95</sup></div></div>
        price_el = item.select_one(".price .new-price, .price .price")
        price = "N/A"
        if price_el:
            sup = price_el.select_one("sup")
            euros = _clean(price_el.get_text("|", strip=True).split("|")[0]).replace("€", "").strip()
            cents = _clean(sup.get_text()) if sup else "00"
            if euros:
                price = f"{euros},{cents} €"

        results.append({"site": "LDLC.com", "name": name, "price": price, "url": url_p})

    return results[:20]


def scrape_alternate_es(query: str, session: requests.Session) -> list[dict]:
    return _scrape_alternate_domain("Alternate.es", "alternate.es", query, session)


# ---------------------------------------------------------------------------
# Coolmod.com  (Spanish PC-hardware/gaming e-commerce retailer)
# ---------------------------------------------------------------------------
def scrape_coolmod(query: str, session: requests.Session) -> list[dict]:
    """Coolmod.com — requests + Doofinder JSON search API (Origin/Referer headers required)."""
    hashid = "a5271756a99534c5e04f33f3f35edf93"
    url = (
        f"https://eu1-search.doofinder.com/6/{hashid}/_search"
        f"?query={urllib.parse.quote(query)}&rpp=20"
    )
    r = session.get(
        url,
        headers={
            "Origin": "https://www.coolmod.com",
            "Referer": "https://www.coolmod.com/",
            "Accept": "application/json",
        },
        timeout=15,
    )
    _check_response(r, "Coolmod.com")

    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("Coolmod.com: unexpected non-JSON response from search API")

    # Doofinder falls back to fuzzy/typo-correction matches with low relevance
    # instead of an empty result set for gibberish queries — treat those as "no results".
    if data.get("query_name") == "fuzzy":
        return []

    results = []
    for item in data.get("results", [])[:20]:
        name = _clean(item.get("title", ""))
        if not name:
            continue
        price_val = item.get("best_price") or item.get("sale_price") or item.get("price")
        price = f"{float(price_val):.2f} EUR" if price_val is not None else "N/A"
        url_p = item.get("link", "")
        results.append({"site": "Coolmod.com", "name": name, "price": price, "url": url_p})

    return results[:20]


# ---------------------------------------------------------------------------
# Amazon  (uses amzpy — curl_cffi browser impersonation, much better bypass)
# ---------------------------------------------------------------------------
def _scrape_amzpy(query: str, country_code: str, site_name: str) -> list[dict]:
    """
    Uses the amzpy library (curl_cffi-based browser impersonation) which handles
    Amazon's bot detection far better than plain requests/cloudscraper.

    Amazon may show prices in HUF to Hungarian visitors — those are passed through
    as-is; EUR prices are left in raw form for convert_eur_price() in main.py.
    """
    from amzpy import AmazonScraper

    # amzpy prints verbose progress lines — suppress them
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        scraper = AmazonScraper(country_code=country_code)
        raw = scraper.search_products(query=query, max_pages=1)

    results = []
    seen: set[str] = set()
    for r in raw:
        title = (r.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)

        price_val = r.get("price")
        currency = str(r.get("currency") or "").strip().upper()

        if price_val is not None and price_val != "?":
            try:
                val = float(price_val)
                if currency in ("HUF", "FT"):
                    # Amazon returning HUF prices (Hungarian visitor IP)
                    price = f"{int(round(val)):,} Ft".replace(",", " ")
                else:
                    # EUR (or unknown) — convert_eur_price() in main.py will handle it
                    price = f"{val:.2f} {currency or 'EUR'}"
            except (ValueError, TypeError):
                price = "N/A"
        else:
            price = "N/A"

        url = r.get("url", "")
        results.append({"site": site_name, "name": title, "price": price, "url": url})

    return results[:20]


def scrape_amazon_de(query: str, _session) -> list[dict]:
    return _scrape_amzpy(query, "de", "Amazon.de")


def scrape_amazon_it(query: str, _session) -> list[dict]:
    return _scrape_amzpy(query, "it", "Amazon.it")


# ---------------------------------------------------------------------------
# BPM-Power.com  (Italian PC-hardware/electronics retailer, Torino)
# ---------------------------------------------------------------------------
def scrape_bpm_power(query: str, session: requests.Session) -> list[dict]:
    """
    BPM-Power.com's own pages are behind a Cloudflare Turnstile challenge that
    blocks plain requests/cloudscraper entirely (even robots.txt). Its search
    widget instead calls Doofinder's public search API directly from the
    browser (eu1-search.doofinder.com) with a fixed hashid — that endpoint is
    not Cloudflare-protected and returns full product JSON. Needs a Referer/
    Origin header for Doofinder's site-authentication check. Doofinder falls
    back to irrelevant "fuzzy" results for queries with no real match, so we
    filter with score_relevance() to drop those.
    """
    headers = {
        "Referer": "https://www.bpm-power.com/",
        "Origin": "https://www.bpm-power.com",
    }
    params = {
        "hashid": "80ac5cdda86276c9ec2ebd582de29aae",
        "query": query,
        "rpp": 20,
    }
    r = session.get(
        "https://eu1-search.doofinder.com/5/search",
        params=params, headers=headers, timeout=15,
    )
    _check_response(r, "BPM-Power.com")
    try:
        data = r.json()
    except ValueError:
        return []

    results = []
    for item in data.get("results", []):
        name = _clean(item.get("title", "") or "")
        if not name or score_relevance(query, name) == 0:
            continue
        price_val = item.get("price")
        try:
            price = f"{float(price_val):.2f} EUR" if price_val is not None else "N/A"
        except (TypeError, ValueError):
            price = "N/A"
        url = item.get("link", "") or ""
        results.append({"site": "BPM-Power.com", "name": name, "price": price, "url": url})

    return results[:20]


# ---------------------------------------------------------------------------
# MediaMarkt.de  (same Next.js / JSON-LD platform as MediaMarkt.hu)
# ---------------------------------------------------------------------------
def scrape_mediamarkt_de(query: str, _session) -> list[dict]:
    """MediaMarkt Germany — same platform as .hu, prices in EUR."""
    cs = get_cloudscraper()
    url = f"https://www.mediamarkt.de/de/search.html?query={urllib.parse.quote(query)}"
    r = cs.get(url, timeout=20)
    _check_response(r, "MediaMarkt.de")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except (json.JSONDecodeError, ValueError):
            continue
        if data.get("@type") != "ItemList":
            continue
        for entry in data.get("itemListElement", []):
            product = entry.get("item", {})
            name = product.get("name", "").strip()
            if not name:
                continue
            offers = product.get("offers", {})
            price_val = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "EUR")
            price = f"{float(price_val):.2f} {currency}" if price_val else "N/A"
            product_url = product.get("url", "")
            results.append({"site": "MediaMarkt.de", "name": name, "price": price, "url": product_url})
        if results:
            break

    return results[:20]


# ---------------------------------------------------------------------------
# Geizhals.at  (DACH price comparison — .de blocks server IPs, .at works)
# ---------------------------------------------------------------------------
def scrape_geizhals(query: str, _session) -> list[dict]:
    """
    Geizhals is the leading DACH price comparison site.
    Uses the .at domain because geizhals.de returns 403 from non-residential IPs.
    Default gallery view; selectors: .galleryview__item / .galleryview__name-link /
    .galleryview__price-link.
    """
    cs = get_cloudscraper()
    url = f"https://geizhals.at/?fs={urllib.parse.quote_plus(query)}"
    r = cs.get(url, timeout=20)
    _check_response(r, "Geizhals.at")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen: set[str] = set()
    for item in soup.select(".galleryview__item"):
        name_el = item.select_one(".galleryview__name-link")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        href = name_el.get("href", "")
        url_p = f"https://geizhals.at{href}" if href.startswith("/") else href
        price_el = item.select_one(".galleryview__price-link, .galleryview__price, .price")
        raw_price = _clean(price_el.get_text()) if price_el else "N/A"
        # Remove "ab " (German "from") prefix shown on comparison prices
        price = re.sub(r"^ab\s+", "", raw_price)
        results.append({"site": "Geizhals.at", "name": name, "price": price, "url": url_p})

    return results[:20]


# ---------------------------------------------------------------------------
# Mindfactory.de
# ---------------------------------------------------------------------------
def scrape_mindfactory(query: str, _session) -> list[dict]:
    """
    Mindfactory.de uses a category-hierarchy URL structure (no keyword search
    endpoint) and active Cloudflare IUAM — visit mindfactory.de directly.
    """
    raise RuntimeError(
        "Mindfactory.de: no keyword search endpoint and Cloudflare blocks "
        "automated access — visit mindfactory.de directly"
    )


# ---------------------------------------------------------------------------
# Coolblue  (NL/DE/BE electronics retailer)
# ---------------------------------------------------------------------------
def _coolblue_from_itemlist(soup: BeautifulSoup, site: str = "Coolblue") -> list[dict]:
    """Extract products from a JSON-LD ItemList (category/model pages)."""
    results = []
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except (json.JSONDecodeError, ValueError):
            continue
        if data.get("@type") != "ItemList":
            continue
        for entry in data.get("itemListElement", []):
            product = entry.get("item", entry)
            name = product.get("name", "").strip()
            if not name:
                continue
            offers = product.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price_val = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "EUR")
            price = f"{float(price_val):.2f} {currency}" if price_val else "N/A"
            url_p = product.get("url", "")
            results.append({"site": site, "name": name, "price": price, "url": url_p})
        if results:
            break
    return results


def _coolblue_from_cards(soup: BeautifulSoup, site: str = "Coolblue", base: str = "https://www.coolblue.nl") -> list[dict]:
    """Extract products from HTML product cards on a search-results page."""
    results = []
    seen: set[str] = set()
    for card in soup.select("div.product-card__details"):
        link_el = card.select_one("a.link[href], a[href*='/product/'], a[href*='/produkt/']")
        if not link_el:
            continue
        name = _clean(link_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        href = link_el.get("href", "")
        url_p = f"{base}{href}" if href.startswith("/") else href
        price_el = card.select_one("strong.sales-price__current")
        price = _clean(price_el.get_text()) if price_el else "N/A"
        results.append({"site": site, "name": name, "price": price, "url": url_p})
    return results


def scrape_coolblue(query: str, _session) -> list[dict]:
    """
    Coolblue.nl (Dutch storefront). Uses coolblue.nl/zoeken which may redirect to
    either a search-results page (HTML cards) or a category/model page (JSON-LD
    ItemList). If the landing page is a category hub with no products, follows
    model-specific subcategory links to find listings.
    """
    cs = get_cloudscraper()
    r = cs.get(
        f"https://www.coolblue.nl/zoeken?query={urllib.parse.quote_plus(query)}",
        timeout=20, allow_redirects=True,
    )
    _check_response(r, "Coolblue.nl")
    soup = BeautifulSoup(r.text, "lxml")

    # 1. JSON-LD ItemList (model-specific category pages)
    results = _coolblue_from_itemlist(soup, "Coolblue.nl")
    if results:
        return results[:20]

    # 2. HTML product cards (generic search-results page)
    results = _coolblue_from_cards(soup, "Coolblue.nl", "https://www.coolblue.nl")
    if results:
        return results[:20]

    # 3. Category landing page — find sibling model pages that have listings.
    # Model pages share the parent path and extend the base category name:
    # e.g., base = ".../apple-macbook-air" → siblings = ".../apple-macbook-air-m4"
    # Strip query string (e.g., ?redirect=...) before path analysis.
    parsed_url = urllib.parse.urlparse(r.url)
    clean_path = parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path.rstrip("/")
    base_name = clean_path.split("/")[-1]
    parent = "/".join(clean_path.split("/")[:-1])
    seen_sub: set[str] = {clean_path}
    sub_urls: list[str] = []
    for a in soup.find_all("a", href=re.compile(r"coolblue\.nl/")):
        href = a["href"].rstrip("/")
        href_name = href.split("/")[-1]
        if (href.startswith(parent + "/")
                and href_name.startswith(base_name)
                and len(href_name) > len(base_name)
                and href not in seen_sub):
            seen_sub.add(href)
            sub_urls.append(href)

    seen_names: set[str] = set()
    for sub_url in sub_urls[:4]:
        r2 = cs.get(sub_url, timeout=20)
        if r2.status_code != 200:
            continue
        soup2 = BeautifulSoup(r2.text, "lxml")
        items = (_coolblue_from_itemlist(soup2, "Coolblue.nl")
                 or _coolblue_from_cards(soup2, "Coolblue.nl", "https://www.coolblue.nl"))
        for item in items:
            if item["name"] not in seen_names:
                seen_names.add(item["name"])
                results.append(item)
        if len(results) >= 20:
            break

    return results[:20]


def scrape_coolblue_de(query: str, _session) -> list[dict]:
    """
    Coolblue.de (German storefront — same platform/template as coolblue.nl, just
    localized). Search path is /suchen (not /zoeken). Product URLs use /produkt/
    instead of /product/; same div.product-card__details / strong.sales-price__current
    selectors. JSON-LD ItemList kept as a fallback for category/model pages.
    """
    cs = get_cloudscraper()
    r = cs.get(
        f"https://www.coolblue.de/suchen?query={urllib.parse.quote_plus(query)}",
        timeout=20, allow_redirects=True,
    )
    _check_response(r, "Coolblue.de")
    soup = BeautifulSoup(r.text, "lxml")

    results = _coolblue_from_itemlist(soup, "Coolblue.de")
    if results:
        return results[:20]

    results = _coolblue_from_cards(soup, "Coolblue.de", "https://www.coolblue.de")
    return results[:20]


# ---------------------------------------------------------------------------
# Compumsa.eu  (Belgian computer-hardware e-shop, French, ASP.NET WebForms)
# ---------------------------------------------------------------------------
def scrape_compumsa(query: str, session: requests.Session) -> list[dict]:
    """Compumsa.eu — requests + server-rendered ASP.NET GridView search results."""
    url = f"https://www.compumsa.eu/search/{urllib.parse.quote(query)}"
    r = session.get(url, timeout=15)
    _check_response(r, "Compumsa.eu")
    soup = BeautifulSoup(r.text, "lxml")

    table = soup.find("table", id="ContentPlaceHolderMain_GridViewSearch")
    if not table:
        return []

    results = []
    seen: set[str] = set()
    for row in table.select("tr"):
        name_el = row.select_one("td.text-left.text-grid a")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        href = name_el.get("href", "")
        url_p = f"https://www.compumsa.eu{href}" if href.startswith("/") else href

        price = "N/A"
        for td in row.select("td.text-right"):
            txt = _clean(td.get_text())
            if "€" in txt:
                price = txt
                break

        results.append({"site": "Compumsa.eu", "name": name, "price": price, "url": url_p})

    return results[:20]


# ---------------------------------------------------------------------------
# Marktplaats.nl  (Dutch classifieds — Adevinta/eBay Classifieds Group)
# ---------------------------------------------------------------------------
_MARKTPLAATS_PRICE_LABELS = {
    "FREE": "Gratis",
    "SEE_DESCRIPTION": "Zie omschrijving",
    "ON_REQUEST": "Op aanvraag",
    "NOTAPPLICABLE": "Bieden",
    "FAST_BID": "Bieden",
}


def _marktplaats_price(price_info: dict) -> str:
    cents = price_info.get("priceCents") or 0
    if not cents:
        label = _MARKTPLAATS_PRICE_LABELS.get(price_info.get("priceType", ""))
        return label or "N/A"
    return f"{cents / 100:.2f} EUR"


def scrape_marktplaats(query: str, session: requests.Session) -> list[dict]:
    """
    Marktplaats.nl is a Next.js app. No login/CAPTCHA is required to search —
    listings ship server-side rendered inside the __NEXT_DATA__ JSON blob at
    pageProps.searchRequestAndResponse.listings (confirmed userDetails.isLoggedIn
    is false on an anonymous request).
    """
    url = f"https://www.marktplaats.nl/q/{urllib.parse.quote_plus(query)}/"
    r = session.get(url, timeout=15)
    _check_response(r, "Marktplaats.nl")

    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    listings = (
        data.get("props", {})
        .get("pageProps", {})
        .get("searchRequestAndResponse", {})
        .get("listings", [])
    )

    results = []
    for item in listings[:20]:
        name = _clean(item.get("title", ""))
        if not name:
            continue
        vip_url = item.get("vipUrl", "")
        url_p = f"https://www.marktplaats.nl{vip_url}" if vip_url else ""
        price = _marktplaats_price(item.get("priceInfo", {}))
        results.append({"site": "Marktplaats.nl", "name": name, "price": price, "url": url_p})

    return results


# ---------------------------------------------------------------------------
# Azerty.nl
# ---------------------------------------------------------------------------
def scrape_azerty(query: str, _session) -> list[dict]:
    """
    Azerty.nl sits entirely behind a Cloudflare "managed" (interactive/Turnstile)
    challenge — every path, including /robots.txt, returns a "Just a moment..."
    interstitial. Plain requests, cloudscraper, curl_cffi browser impersonation,
    and even headless Chromium all get stuck on the challenge, so no keyword-
    search response is ever reachable. Raises an informative error.
    """
    raise RuntimeError(
        "Azerty.nl: entire site is behind an interactive Cloudflare challenge "
        "(cType: 'managed') that blocks automated requests, cloudscraper, and "
        "even headless-browser access — visit azerty.nl directly"
    )


# ---------------------------------------------------------------------------
# Megekko.nl
# ---------------------------------------------------------------------------
def scrape_megekko(query: str, _session) -> list[dict]:
    """
    Megekko.nl serves a custom JavaScript "checking your browser" puzzle
    challenge (not Cloudflare IUAM) on every route, including the homepage —
    confirmed with both plain requests and cloudscraper. No JSON-LD, __NEXT_DATA__,
    or server-rendered HTML is reachable without passing it. Raises an
    informative error so the badge clearly explains why.
    """
    raise RuntimeError(
        "Megekko.nl: served behind a custom JS bot-challenge page — "
        "visit megekko.nl directly in a browser"
    )


# ---------------------------------------------------------------------------
# Morele.net  (Poland)
# ---------------------------------------------------------------------------
def scrape_morele(query: str, session: requests.Session) -> list[dict]:
    """Morele.net (Poland) — requests + server-rendered .cat-product cards."""
    url = f"https://www.morele.net/wyszukiwarka/?q={urllib.parse.quote_plus(query)}"
    r = session.get(url, timeout=15)
    _check_response(r, "Morele.net")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    seen: set[str] = set()
    for card in soup.select("div.cat-product"):
        name = _clean(card.get("data-product-name", ""))
        if not name or name in seen:
            continue
        seen.add(name)

        link_el = card.select_one("[data-link-href-param]")
        href = link_el.get("data-link-href-param", "") if link_el else ""
        url_p = f"https://www.morele.net{href}" if href.startswith("/") else href

        price_el = card.select_one(".price-new")
        price = _clean(price_el.get_text()) if price_el else "N/A"

        results.append({"site": "Morele.net", "name": name, "price": price, "url": url_p})

    return results[:20]


# ---------------------------------------------------------------------------
# Webhallen.se  (Swedish PC-hardware/electronics/gaming retailer)
# ---------------------------------------------------------------------------
def scrape_webhallen(query: str, session: requests.Session) -> list[dict]:
    """Webhallen.se — requests + JSON API (productdiscovery/search endpoint)."""
    url = f"https://www.webhallen.com/api/productdiscovery/search/{urllib.parse.quote(query)}"
    r = session.get(url, timeout=15, headers={"Accept": "application/json"})
    _check_response(r, "Webhallen.se")

    try:
        data = r.json()
    except ValueError:
        return []

    results = []
    for item in data.get("products", []):
        pid = item.get("id")
        name = _clean(item.get("name") or item.get("mainTitle") or "")
        if not name or pid is None:
            continue

        # Prefer the current selling price; fall back to regular/lowest price.
        price_info = item.get("price") or item.get("regularPrice") or item.get("lowestPrice") or {}
        price_val = price_info.get("price")
        currency = price_info.get("currency", "SEK")
        if price_val:
            try:
                amount = int(round(float(price_val)))
                price = f"{amount:,} {currency}".replace(",", " ")
            except (TypeError, ValueError):
                price = "N/A"
        else:
            price = "N/A"

        product_url = f"https://www.webhallen.com/se/product/{pid}"
        results.append({"site": "Webhallen.se", "name": name, "price": price, "url": product_url})

    return results[:20]


# ---------------------------------------------------------------------------
# Kleinanzeigen.de  (German classifieds, formerly eBay Kleinanzeigen)
# ---------------------------------------------------------------------------
def scrape_kleinanzeigen(query: str, session: requests.Session) -> list[dict]:
    """
    Kleinanzeigen.de is Germany's main classifieds site. Results are server-side
    rendered in article.aditem elements — no JSON blob needed. Many listings show
    "VB" (Verhandlungsbasis / negotiable) appended to a price or in place of one.
    """
    url = f"https://www.kleinanzeigen.de/s-{urllib.parse.quote(query)}/k0"
    r = session.get(url, timeout=15)
    _check_response(r, "Kleinanzeigen.de")
    soup = BeautifulSoup(r.text, "lxml")

    results = []
    for item in soup.select("article.aditem"):
        name_el = item.select_one("h2.text-module-begin a") or item.select_one("a.ellipsis")
        price_el = item.select_one(".aditem-main--middle--price-shipping--price")

        if not name_el:
            continue

        name = _clean(name_el.get_text())
        href = item.get("data-href") or name_el.get("href", "")
        url_p = f"https://www.kleinanzeigen.de{href}" if href.startswith("/") else href
        price = _clean(price_el.get_text()) if price_el else "N/A"

        if name:
            results.append({"site": "Kleinanzeigen.de", "name": name, "price": price, "url": url_p})

    return results[:20]


# ---------------------------------------------------------------------------
# Registry  — (site_name, region, scrape_fn)
# ---------------------------------------------------------------------------
SCRAPERS: list[tuple[str, str, callable]] = [
    # ── Hungary ──────────────────────────────────────────────────────────────
    ("Alza.hu",          "hu", scrape_alza),
    ("eMAG.hu",          "hu", scrape_emag),
    ("MediaMarkt.hu",    "hu", scrape_mediamarkt),
    ("iStyle.hu",        "hu", scrape_istyle),
    ("Jófogás.hu",       "hu", scrape_jofogas),
    ("Hardverapró",      "hu", scrape_hardverapro),
    ("Vatera.hu",        "hu", scrape_vatera),
    ("hasznaltalma.hu",  "hu", scrape_hasznaltalma),
    ("iSamurai.hu",      "hu", scrape_isamurai),
    ("macszerez.com",    "hu", scrape_macszerez),
    ("Rejoy.hu",         "hu", scrape_rejoy),
    ("iCrew.hu",         "hu", scrape_icrew),
    ("almapiac.com",     "hu", scrape_almapiac),
    ("Furbify.hu",       "hu", scrape_furbify),
    ("iKing.hu",         "hu", scrape_iking),
    # ── Germany / DACH ───────────────────────────────────────────────────────
    ("Alza.de",          "de", scrape_alza_de),
    ("Alternate.de",     "de", scrape_alternate_de),
    ("Amazon.de",        "de", scrape_amazon_de),
    ("MediaMarkt.de",    "de", scrape_mediamarkt_de),
    ("Geizhals.at",      "de", scrape_geizhals),
    ("Coolblue.de",      "de", scrape_coolblue_de),
    ("Notebooksbilliger.de", "de", scrape_notebooksbilliger),
    # ("Kleinanzeigen.de", "de", scrape_kleinanzeigen),
    # ── Austria ──────────────────────────────────────────────────────────────
    ("Alza.at",          "at", scrape_alza_at),
    ("Alternate.at",     "at", scrape_alternate_at),
    # ── Czechia ──────────────────────────────────────────────────────────────
    ("Alza.cz",          "cz", scrape_alza_cz),
    # ── Slovakia ─────────────────────────────────────────────────────────────
    ("Alza.sk",          "sk", scrape_alza_sk),
    # ── Romania ──────────────────────────────────────────────────────────────
    ("eMAG.ro",          "ro", scrape_emag_ro),
    # ── France ───────────────────────────────────────────────────────────────
    ("Alternate.fr",     "fr", scrape_alternate_fr),
    ("LDLC.com",         "fr", scrape_ldlc),
    # ── Spain ────────────────────────────────────────────────────────────────
    ("Alternate.es",     "es", scrape_alternate_es),
    ("Coolmod.com",      "es", scrape_coolmod),
    # ── Belgium ──────────────────────────────────────────────────────────────
    ("Compumsa.eu",      "be", scrape_compumsa),
    # ── Italy ────────────────────────────────────────────────────────────────
    ("Amazon.it",        "it", scrape_amazon_it),
    ("BPM-Power.com",    "it", scrape_bpm_power),
    # ── Netherlands ──────────────────────────────────────────────────────────
    ("Alternate.nl",     "nl", scrape_alternate_nl),
    ("Marktplaats.nl",   "nl", scrape_marktplaats),
    ("Coolblue.nl",      "nl", scrape_coolblue),
    ("Azerty.nl",        "nl", scrape_azerty),
    ("Megekko.nl",       "nl", scrape_megekko),
    # ── Poland ───────────────────────────────────────────────────────────────
    ("Morele.net",       "pl", scrape_morele),
    # ── Sweden ───────────────────────────────────────────────────────────────
    ("Webhallen.se",     "se", scrape_webhallen),
]

# Lookup: site_name → region code  (used by main.py for EUR→HUF conversion)
SCRAPER_REGIONS: dict[str, str] = {name: region for name, region, _ in SCRAPERS}

# Region codes whose scrapers return prices in EUR — only these should go through
# convert_eur_price(). "pl" (Morele.net, PLN), "se" (Webhallen.se, SEK) and
# "cz" (Alza.cz, CZK) are non-hu but NOT EUR, so main.py must not run them
# through the EUR converter.
EUR_REGIONS: frozenset[str] = frozenset({"de", "at", "sk", "fr", "es", "it", "nl", "be"})

# What currency a region's prices end up in AFTER enrich_result ran
# (EUR prices are converted to HUF; PLN/SEK/CZK/RON stay in their local currency).
REGION_CURRENCIES: dict[str, str] = {"pl": "PLN", "se": "SEK", "cz": "CZK", "ro": "RON"}


# ---------------------------------------------------------------------------
# Shared search pipeline (used by both the GUI and the Django server)
# ---------------------------------------------------------------------------
def enrich_result(site: str, result: dict, query: str) -> dict:
    """
    Post-process one raw scraper result IN PLACE:
      - "price" of EUR stores converted to the "X XXX Ft (Y €)" display form
      - "amount"     numeric price in "currency"
      - "currency"   HUF / PLN / SEK (EUR is already converted to HUF)
      - "amount_huf" price normalized to HUF for cross-currency comparison
      - "score"      0-100 relevance against the query
    """
    region = SCRAPER_REGIONS.get(site, "hu")
    price_str = result.get("price", "")
    if region in EUR_REGIONS:
        price_str = convert_eur_price(price_str)
        result["price"] = price_str
    amount = extract_numeric_price(price_str)
    currency = REGION_CURRENCIES.get(region, "HUF")
    result.setdefault("site", site)
    result["amount"] = amount
    result["currency"] = currency
    result["amount_huf"] = round(amount * get_huf_rate(currency)) if amount else 0
    result["score"] = score_relevance(query, result.get("name", ""))
    return result


def run_search(
    query: str,
    scrapers: list | None = None,
    session: requests.Session | None = None,
    timeout: float = 90,
    on_store=None,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """
    Run scrapers concurrently for a query and enrich every result.

    Returns (results, ok_sites, failed_sites) where failed_sites maps
    site name → error string. A failing site never kills the search.
    on_store(site_name, results, error) — if given — is called from the
    calling thread as each store finishes.
    """
    scrapers = list(SCRAPERS if scrapers is None else scrapers)
    session = session or create_session()

    results: list[dict] = []
    ok_sites: list[str] = []
    failed_sites: dict[str, str] = {}

    executor = ThreadPoolExecutor(max_workers=max(1, len(scrapers)))
    futures = {executor.submit(fn, query, session): site for site, _, fn in scrapers}
    try:
        for future in as_completed(futures, timeout=timeout):
            site = futures[future]
            try:
                site_results = future.result()
            except Exception as exc:
                failed_sites[site] = str(exc)
                if on_store:
                    on_store(site, [], str(exc))
                continue
            for r in site_results:
                enrich_result(site, r, query)
            ok_sites.append(site)
            results.extend(site_results)
            if on_store:
                on_store(site, site_results, None)
    except FuturesTimeout:
        for future, site in futures.items():
            if not future.done():
                failed_sites[site] = f"timed out after {timeout}s"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return results, ok_sites, failed_sites
