"""
Per-site scraping logic.

Approach per site:
  Alza.hu        - cloudscraper (Cloudflare bypass) + parse data-initialdata JSON
  eMAG.hu        - cloudscraper + HTML (.card-v2 structure)
  MediaMarkt.hu  - cloudscraper + JSON-LD ItemList
  iStyle.hu      - requests + individual JSON-LD Product scripts
  Jófogás.hu     - requests + .reListItem (classifieds)
  Hardverapró    - requests + li.media/.uad-col-title (classifieds)
  Vatera.hu      - JavaScript-rendered; raises informative error
"""

import re
import json
import html
import urllib.parse

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
        raise RuntimeError(f"{site}: 403 Forbidden")
    r.raise_for_status()


def extract_numeric_price(price_str: str) -> int:
    """Return an integer suitable for numeric sort (strips all non-digits)."""
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else 0


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
# Alza.hu
# ---------------------------------------------------------------------------
def scrape_alza(query: str, _session) -> list[dict]:
    """
    Alza is a React SPA protected by Cloudflare. The product list is server-side
    rendered inside a data-initialdata attribute as HTML-encoded JSON.
    """
    cs = cloudscraper.create_scraper()
    url = f"https://www.alza.hu/search.htm?exps={urllib.parse.quote(query)}"
    r = cs.get(url, timeout=20)
    _check_response(r, "Alza.hu")

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
            results.append({"site": "Alza.hu", "name": name, "price": price, "url": url_product})

    return results


# ---------------------------------------------------------------------------
# eMAG.hu
# ---------------------------------------------------------------------------
def scrape_emag(query: str, _session) -> list[dict]:
    """eMAG uses server-side rendered .card-v2 product cards."""
    cs = cloudscraper.create_scraper()
    url = f"https://www.emag.hu/search/{urllib.parse.quote(query)}/c"
    r = cs.get(url, timeout=20)
    _check_response(r, "eMAG.hu")
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
            results.append({"site": "eMAG.hu", "name": name, "price": price, "url": href})

    return results[:20]


# ---------------------------------------------------------------------------
# MediaMarkt.hu
# ---------------------------------------------------------------------------
def scrape_mediamarkt(query: str, _session) -> list[dict]:
    """
    MediaMarkt is Cloudflare-protected and Next.js-based. Product data is
    embedded in application/ld+json scripts as an ItemList.
    """
    cs = cloudscraper.create_scraper()
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
# Registry
# ---------------------------------------------------------------------------
SCRAPERS: list[tuple[str, callable]] = [
    ("Alza.hu",          scrape_alza),
    ("eMAG.hu",          scrape_emag),
    ("MediaMarkt.hu",    scrape_mediamarkt),
    ("iStyle.hu",        scrape_istyle),
    ("Jófogás.hu",       scrape_jofogas),
    ("Hardverapró",      scrape_hardverapro),
    ("Vatera.hu",        scrape_vatera),
    ("hasznaltalma.hu",  scrape_hasznaltalma),
    ("iSamurai.hu",      scrape_isamurai),
    ("macszerez.com",    scrape_macszerez),
    ("Rejoy.hu",         scrape_rejoy),
    ("iCrew.hu",         scrape_icrew),
    ("almapiac.com",     scrape_almapiac),
    ("Furbify.hu",       scrape_furbify),
    ("iKing.hu",         scrape_iking),
]
