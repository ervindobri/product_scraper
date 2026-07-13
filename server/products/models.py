from django.db import models
from django.utils import timezone

class Store(models.Model):
    # unique: the API and sync_stores identify stores by name
    name = models.CharField(max_length=100, unique=True)
    url = models.CharField(max_length=200)
    country = models.CharField(max_length=30)
    pub_date = models.DateTimeField("date published")
    # scrape health, maintained by services.refresh_search_query
    last_success = models.DateTimeField(null=True, blank=True)
    failure_count = models.IntegerField(default=0)


    def __str__(self):
        return self.name + ' (' + self.url + ')'


class SearchQuery(models.Model):
    # unique so re-running a search updates the existing row
    # (e.g. SearchQuery.objects.get_or_create(query=...))
    query = models.CharField(max_length=200, unique=True)
    results_count = models.IntegerField(default=0)
    # when the scrapers last ran SUCCESSFULLY for this query;
    # null = never scraped (so a brand-new query always counts as stale)
    last_searched_date = models.DateTimeField("date last searched", null=True, blank=True)

    class Meta:
        verbose_name_plural = "search queries"

    def __str__(self):
        return self.query


class Product(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    # the search that produced this result; deleting the query deletes its results
    query = models.ForeignKey(
        SearchQuery,
        on_delete=models.CASCADE,
        related_name="products",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=500)
    url = models.TextField(default="", blank=True)
    # price in `currency`; price_huf is normalized for cross-currency sorting
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default='HUF')
    price_huf = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Match against self.query: 0-100%
    score = models.IntegerField(default=0)
    # listing lifetime: first_seen set once, last_seen bumped every refresh
    # that still finds the product (older last_seen = delisted)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            # a refresh upserts by (query, url); empty urls are exempt
            models.UniqueConstraint(
                fields=["query", "url"],
                condition=~models.Q(url=""),
                name="unique_product_per_query_url",
            ),
        ]

    def __str__(self):
        return self.name

    def score_passes(self):
        return self.score > 50;


class PriceHistory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_history")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default='HUF')
    price_huf = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recorded_date = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "price histories"
        ordering = ["-recorded_date"]

    def __str__(self):
        return f"{self.product.name}: {self.price} {self.currency} @ {self.recorded_date:%Y-%m-%d}"





# By running makemigrations, you’re telling Django that 
# you’ve made some changes to your models (in this case, you’ve made new ones)
# and that you’d like the changes to be stored as a migration.


# Creating a new object:

# s = Store(name="Alza", url="alza.hu", country="HU", pub_date=timezone.now())
# p = Product(store = s, 
#   name="LEGO® Editions 43015 Lionel Messi - Futball-legenda", 
#   url="https://www.alza.hu/jatekok/lego-editions-43015-lionel-messi-futball-legenda-d13303401.htm?o=1",
#   price=21790.0,
#   score =99
# )


# DB:
# s.save() // must be before p.save so it has the foreign key connection
# p.save()

# Objects after save have id: s.id, p.id