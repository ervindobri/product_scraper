from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import PriceHistory, Product, SearchQuery, Store
from .services import refresh_search_query


def make_store(name="Alza.hu", **kwargs):
    defaults = {"url": name.lower(), "country": "Hungary", "pub_date": timezone.now()}
    defaults.update(kwargs)
    return Store.objects.create(name=name, **defaults)


def fake_result(site="Alza.hu", name="Mac mini M4", url="https://x/1",
                amount=200000, currency="HUF", amount_huf=None, score=100):
    """A result dict in the shape run_search/enrich_result produce."""
    return {
        "site": site, "name": name, "url": url,
        "price": f"{amount} Ft",
        "amount": amount, "currency": currency,
        "amount_huf": amount_huf if amount_huf is not None else amount,
        "score": score,
    }


OK_SUMMARY = {"ok": True, "count": 1, "new": 1, "stores_ok": 30, "stores_failed": {}}


class SearchEndpointTests(TestCase):
    """The /api/queries/search/ action — staleness, normalization, limit."""

    def search(self, **params):
        return self.client.get("/api/queries/search/", params)

    def test_missing_query_param_returns_400(self):
        self.assertEqual(self.search().status_code, 400)

    def test_invalid_limit_returns_400(self):
        self.assertEqual(self.search(query="x", limit="nope").status_code, 400)
        self.assertEqual(self.search(query="x", limit="-2").status_code, 400)

    @patch("products.views.refresh_search_query", return_value=OK_SUMMARY)
    def test_new_query_triggers_refresh(self, mock_refresh):
        response = self.search(query="mac mini m4")
        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_called_once()
        self.assertTrue(response.json()["refreshed"])
        self.assertTrue(SearchQuery.objects.filter(query="mac mini m4").exists())

    @patch("products.views.refresh_search_query", return_value=OK_SUMMARY)
    def test_query_text_is_normalized(self, mock_refresh):
        self.search(query="  Mac  Mini M4 ")
        self.assertEqual(SearchQuery.objects.count(), 1)
        self.assertEqual(SearchQuery.objects.get().query, "mac mini m4")

    @patch("products.views.refresh_search_query", return_value=OK_SUMMARY)
    def test_fresh_query_served_from_db_without_refresh(self, mock_refresh):
        now = timezone.now()
        query = SearchQuery.objects.create(
            query="mac mini m4", results_count=1, last_searched_date=now)
        store = make_store()
        Product.objects.create(
            store=store, query=query, name="Mac mini", url="https://x/1",
            price=200000, price_huf=200000, last_seen=now)

        response = self.search(query="mac mini m4")
        mock_refresh.assert_not_called()
        data = response.json()
        self.assertFalse(data["refreshed"])
        self.assertEqual(len(data["products"]), 1)
        # the store is serialized by name, not primary key
        self.assertEqual(data["products"][0]["store"], "Alza.hu")

    @patch("products.views.refresh_search_query", return_value=OK_SUMMARY)
    def test_stale_query_triggers_refresh(self, mock_refresh):
        SearchQuery.objects.create(
            query="mac mini m4",
            last_searched_date=timezone.now() - timedelta(hours=2))
        self.search(query="mac mini m4")
        mock_refresh.assert_called_once()

    @patch("products.views.refresh_search_query", return_value=OK_SUMMARY)
    def test_never_scraped_query_counts_as_stale(self, mock_refresh):
        SearchQuery.objects.create(query="mac mini m4", last_searched_date=None)
        self.search(query="mac mini m4")
        mock_refresh.assert_called_once()

    def _query_with_products(self):
        now = timezone.now()
        query = SearchQuery.objects.create(
            query="mac mini m4", last_searched_date=now)
        store = make_store()
        for i, (huf, score) in enumerate([(300000, 100), (0, 100), (200000, 100)]):
            Product.objects.create(
                store=store, query=query, name=f"p{i}", url=f"https://x/{i}",
                price=huf, price_huf=huf, score=score, last_seen=now)
        return query, store, now

    def test_limit_caps_products(self):
        self._query_with_products()
        data = self.search(query="mac mini m4", limit="2").json()
        self.assertEqual(len(data["products"]), 2)

    def test_unpriced_products_sort_last(self):
        self._query_with_products()
        data = self.search(query="mac mini m4").json()
        prices = [p["price_huf"] for p in data["products"]]
        self.assertEqual(prices, [200000, 300000, 0])

    def test_delisted_products_are_hidden(self):
        query, store, now = self._query_with_products()
        Product.objects.create(
            store=store, query=query, name="gone", url="https://x/gone",
            price=1, price_huf=1, score=100,
            last_seen=now - timedelta(days=2))
        data = self.search(query="mac mini m4").json()
        self.assertEqual(len(data["products"]), 3)
        self.assertNotIn("gone", [p["name"] for p in data["products"]])

    @patch("products.views.refresh_search_query",
           return_value={"ok": False, "count": 0, "new": 0,
                         "stores_ok": 0, "stores_failed": {"Alza.hu": "boom"}})
    def test_total_scrape_failure_is_reported(self, mock_refresh):
        data = self.search(query="mac mini m4").json()
        self.assertFalse(data["refreshed"])
        self.assertIn("refresh_error", data)


class RefreshServiceTests(TestCase):
    """services.refresh_search_query — upsert, price history, store health."""

    def setUp(self):
        self.store = make_store("Alza.hu")
        self.query = SearchQuery.objects.create(query="mac mini m4")

    def refresh(self, results, ok=("Alza.hu",), failed=None):
        with patch("products.services.run_search",
                   return_value=(results, list(ok), failed or {})):
            return refresh_search_query(self.query)

    def test_first_refresh_creates_products_and_history(self):
        summary = self.refresh([fake_result(url="https://x/1"),
                                fake_result(name="Other", url="https://x/2")])
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["count"], 2)
        self.assertEqual(self.query.products.count(), 2)
        self.assertEqual(PriceHistory.objects.count(), 2)
        self.query.refresh_from_db()
        self.assertEqual(self.query.results_count, 2)
        self.assertIsNotNone(self.query.last_searched_date)
        self.store.refresh_from_db()
        self.assertIsNotNone(self.store.last_success)
        self.assertEqual(self.store.failure_count, 0)

    def test_second_refresh_upserts_and_records_price_change(self):
        self.refresh([fake_result(amount=200000)])
        product = self.query.products.get()
        first_seen = product.first_seen

        self.refresh([fake_result(amount=180000)])
        self.assertEqual(self.query.products.count(), 1)  # upsert, not duplicate
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal(180000))
        self.assertEqual(product.first_seen, first_seen)
        self.assertEqual(product.price_history.count(), 2)

    def test_unchanged_price_adds_no_history(self):
        self.refresh([fake_result()])
        self.refresh([fake_result()])
        self.assertEqual(PriceHistory.objects.count(), 1)

    def test_delisted_product_keeps_old_last_seen(self):
        self.refresh([fake_result(url="https://x/1"),
                      fake_result(name="Other", url="https://x/2")])
        old_seen = self.query.products.get(url="https://x/2").last_seen

        self.refresh([fake_result(url="https://x/1")])
        self.query.refresh_from_db()
        gone = self.query.products.get(url="https://x/2")
        self.assertEqual(gone.last_seen, old_seen)
        self.assertLess(gone.last_seen, self.query.last_searched_date)

    def test_duplicate_results_in_one_scrape_are_deduped(self):
        summary = self.refresh([fake_result(), fake_result()])
        self.assertEqual(summary["count"], 1)
        self.assertEqual(self.query.products.count(), 1)

    def test_absurd_price_is_zeroed(self):
        self.refresh([fake_result(amount=829990774990, amount_huf=829990774990)])
        product = self.query.products.get()
        self.assertEqual(product.price, 0)

    def test_unknown_store_results_are_skipped(self):
        summary = self.refresh([fake_result(site="NotSeeded.hu")])
        self.assertEqual(summary["count"], 0)
        self.assertEqual(self.query.products.count(), 0)

    def test_total_failure_writes_nothing_and_counts_failures(self):
        summary = self.refresh([], ok=(), failed={"Alza.hu": "boom"})
        self.assertFalse(summary["ok"])
        self.query.refresh_from_db()
        self.assertIsNone(self.query.last_searched_date)  # stays never-scraped
        self.store.refresh_from_db()
        self.assertEqual(self.store.failure_count, 1)


class ScraperHelperTests(SimpleTestCase):
    """Pure helpers from the scraper package (no network, no DB)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import products.services  # noqa: F401  (puts <repo> on sys.path)
        from scraper import scrapers
        cls.scrapers = scrapers

    def test_extract_numeric_price(self):
        cases = {
            "21 790 Ft": 21790,
            "829 990 Ft 774 990 Ft": 829990,   # original + discounted price
            "1 390.50 kr": 1390,
            "1069,00": 1069,
            "242 339 Ft (7 490 €)": 242339,
            "1.399": 1399,
            "N/A": 0,
            "": 0,
        }
        for raw, expected in cases.items():
            self.assertEqual(self.scrapers.extract_numeric_price(raw), expected, raw)

    def test_enrich_result_huf(self):
        r = {"site": "Alza.hu", "name": "Apple Mac mini M4", "price": "21 790 Ft", "url": "u"}
        self.scrapers.enrich_result("Alza.hu", r, "mac mini m4")
        self.assertEqual(r["amount"], 21790)
        self.assertEqual(r["currency"], "HUF")
        self.assertEqual(r["amount_huf"], 21790)
        self.assertEqual(r["score"], 100)

    def test_enrich_result_foreign_currency(self):
        r = {"site": "Webhallen.se", "name": "Mac mini M4", "price": "7 490 kr", "url": "u"}
        with patch.object(self.scrapers, "get_huf_rate", return_value=36.0):
            self.scrapers.enrich_result("Webhallen.se", r, "mac mini m4")
        self.assertEqual(r["currency"], "SEK")
        self.assertEqual(r["amount_huf"], 7490 * 36)

    def test_run_search_isolates_store_failures(self):
        def good(query, session):
            return [{"site": "Good.hu", "name": "hit", "price": "1 000 Ft", "url": "u"}]

        def bad(query, session):
            raise RuntimeError("boom")

        fake_registry = [("Good.hu", "hu", good), ("Bad.hu", "hu", bad)]
        seen = []
        results, ok, failed = self.scrapers.run_search(
            "hit", scrapers=fake_registry,
            on_store=lambda site, res, err: seen.append((site, err)),
        )
        self.assertEqual(ok, ["Good.hu"])
        self.assertEqual(list(failed), ["Bad.hu"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["amount"], 1000)  # enriched
        self.assertEqual(len(seen), 2)
