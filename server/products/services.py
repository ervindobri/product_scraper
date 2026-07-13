"""
Bridge between the Django app and the scraper package (<repo>/scraper).

refresh_search_query() scrapes all stores for a query and UPSERTS the
results: products are matched by (query, url), price changes append
PriceHistory rows, delisted products simply stop getting their last_seen
bumped, and per-store scrape health (last_success / failure_count) is
maintained on Store.
"""

import logging
import sys
from decimal import Decimal
from pathlib import Path

from django.db import transaction
from django.db.models import F
from django.utils import timezone

# make <repo> importable so the scraper package can be reached from the server
REPO_DIR = Path(__file__).resolve().parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scraper.scrapers import run_search  # noqa: E402

from .models import PriceHistory, Product, Store

logger = logging.getLogger(__name__)

# give slow stores a chance, but never hang the request forever
SCRAPE_TIMEOUT_SECONDS = 90

# anything above this is a parse error, not a price
MAX_PRICE = Decimal(10) ** 10

PRODUCT_UPDATE_FIELDS = ["name", "price", "currency", "price_huf", "score", "last_seen"]


def refresh_search_query(search_query) -> dict:
    """
    Scrape all stores for search_query.query and upsert its products.

    Returns a summary dict:
      {"ok": bool, "count": int, "new": int, "stores_ok": int,
       "stores_failed": {site: error}}

    ok=False means EVERY store failed — in that case nothing is written, so
    last_searched_date stays put and the next request retries instead of
    caching emptiness. Individual store failures are logged and ignored.
    """
    query = search_query.query
    stores = {s.name: s for s in Store.objects.all()}

    results, ok_sites, failed_sites = run_search(query, timeout=SCRAPE_TIMEOUT_SECONDS)
    now = timezone.now()

    # per-store scrape health
    if ok_sites:
        Store.objects.filter(name__in=ok_sites).update(last_success=now, failure_count=0)
    if failed_sites:
        Store.objects.filter(name__in=failed_sites).update(
            failure_count=F("failure_count") + 1
        )
        for site, err in failed_sites.items():
            logger.warning("scrape failed for %s: %s", site, err)

    if not ok_sites:
        logger.error("all %d stores failed for query %r", len(failed_sites), query)
        return {"ok": False, "count": 0, "new": 0, "stores_ok": 0,
                "stores_failed": failed_sites}

    # existing products keyed the same way as incoming results
    existing = {}
    for product in search_query.products.select_related("store"):
        key = product.url or f"{product.store.name}::{product.name}"
        existing[key] = product

    new_products: list[Product] = []
    updated: list[Product] = []
    history: list[PriceHistory] = []
    seen_keys: set[str] = set()
    unknown_sites: set[str] = set()

    for r in results:
        site = r.get("site", "")
        store = stores.get(site)
        if store is None:
            unknown_sites.add(site)
            continue

        name = (r.get("name") or "")[:500]
        url = r.get("url") or ""
        key = url or f"{site}::{name}"
        if key in seen_keys:
            continue  # duplicate listing within one scrape
        seen_keys.add(key)

        price = Decimal(r.get("amount") or 0)
        price_huf = Decimal(r.get("amount_huf") or 0)
        if price >= MAX_PRICE or price_huf >= MAX_PRICE:
            logger.warning("discarding absurd price %s for %r on %s", price, name, site)
            price = price_huf = Decimal(0)
        currency = r.get("currency", "HUF")
        score = r.get("score", 0)

        product = existing.get(key)
        if product is None:
            new_products.append(Product(
                store=store, query=search_query, name=name, url=url,
                price=price, currency=currency, price_huf=price_huf,
                score=score, first_seen=now, last_seen=now,
            ))
        else:
            price_changed = product.price != price or product.currency != currency
            product.name = name
            product.price = price
            product.currency = currency
            product.price_huf = price_huf
            product.score = score
            product.last_seen = now
            updated.append(product)
            if price_changed:
                history.append(PriceHistory(
                    product=product, price=price, currency=currency,
                    price_huf=price_huf, recorded_date=now,
                ))

    if unknown_sites:
        logger.warning(
            "results from unseeded stores skipped: %s (run manage.py sync_stores)",
            ", ".join(sorted(unknown_sites)),
        )

    price_changes = len(history)
    with transaction.atomic():
        Product.objects.bulk_create(new_products)
        Product.objects.bulk_update(updated, PRODUCT_UPDATE_FIELDS)
        # every new product opens its price history
        history.extend(
            PriceHistory(product=p, price=p.price, currency=p.currency,
                         price_huf=p.price_huf, recorded_date=now)
            for p in new_products
        )
        PriceHistory.objects.bulk_create(history)
        search_query.results_count = len(seen_keys)
        search_query.last_searched_date = now
        search_query.save(update_fields=["results_count", "last_searched_date"])

    logger.info(
        "refreshed %r: %d products (%d new, %d price changes), %d/%d stores ok",
        query, len(seen_keys), len(new_products), price_changes,
        len(ok_sites), len(ok_sites) + len(failed_sites),
    )
    return {
        "ok": True,
        "count": len(seen_keys),
        "new": len(new_products),
        "stores_ok": len(ok_sites),
        "stores_failed": failed_sites,
    }
