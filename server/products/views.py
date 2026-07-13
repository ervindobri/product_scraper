import threading
from datetime import timedelta

from django.shortcuts import render
from django.http import Http404, HttpResponse
from django.db.models import Case, IntegerField, When
from django.views import generic
from django.urls import reverse
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import Product, SearchQuery, Store
from .serializers import (
    ProductSerializer,
    SearchQuerySerializer,
    StoreSerializer,
)
from .services import refresh_search_query

# results younger than this are served straight from the DB
SEARCH_MAX_AGE = timedelta(hours=1)

# one lock per query so concurrent requests can't scrape the same thing twice
# (per-process; a multi-worker deployment needs a shared lock, e.g. in the DB)
_refresh_locks: dict[str, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _refresh_lock(query_text: str) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(query_text, threading.Lock())

# def index(request):
#     return HttpResponse("products index.")


# def detail(request, store_id):
#     try:
#         store = Store.objects.get(pk=store_id)
#     except Store.DoesNotExist:
#         raise Http404("Store does not exist")
#     return render(request, "products/detail.html", {"store": store})


class IndexView(generic.ListView):
    template_name = "products/index.html"
    # context_object_name = "latest_stores_list"

    def get_queryset(self):
        """Return the last five published questions."""
        return Store.objects.order_by("-pub_date")[:5]


class DetailView(generic.DetailView):
    model = Store
    template_name = "products/detail.html"

def name(request, store_id):
    response = "You're looking at the name of store %s."
    return HttpResponse(response % store_id)


def pub_date(request, pk):
    return HttpResponse("Pub date is %s." % pk)





class StoreViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows stores to be viewed or edited.

    Provides list/retrieve/create/update/destroy at /api/stores/.
    """

    queryset = Store.objects.all().order_by("-pub_date")
    serializer_class = StoreSerializer
    # TODO: tighten permissions, e.g.
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    # TODO: filter the queryset if needed, e.g. by country:
    # def get_queryset(self):
    #     ...


class SearchQueryViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows search queries to be viewed or edited.

    Provides list/retrieve/create/update/destroy at /api/queries/.
    """

    queryset = SearchQuery.objects.all().order_by("-last_searched_date")
    serializer_class = SearchQuerySerializer
    # scope for the ScopedRateThrottle on the search action below
    throttle_scope = "search"

    @action(
        detail=False,
        methods=["get"],
        throttle_classes=[ScopedRateThrottle],
    )
    def search(self, request):
        """
        GET /api/queries/search/?query=mac+mini+m4[&limit=50]

        Serves products for the query from the DB; if the query has never
        been scraped or is older than SEARCH_MAX_AGE, re-runs the scrapers
        first (upserting products and refreshing results_count /
        last_searched_date). Only one refresh runs per query at a time.
        """
        raw = request.query_params.get("query", "")
        # normalize so "Mac  Mini" and "mac mini" share one SearchQuery row
        query_text = " ".join(raw.split()).lower()
        if not query_text:
            return Response(
                {"detail": "Missing required 'query' parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = None
        if "limit" in request.query_params:
            try:
                limit = int(request.query_params["limit"])
                if limit <= 0:
                    raise ValueError
            except ValueError:
                return Response(
                    {"detail": "'limit' must be a positive integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        search_query, _ = SearchQuery.objects.get_or_create(query=query_text)

        refresh_summary = None
        if self._is_stale(search_query):
            with _refresh_lock(query_text):
                # another request may have refreshed while we waited
                search_query.refresh_from_db()
                if self._is_stale(search_query):
                    refresh_summary = refresh_search_query(search_query)

        products = search_query.products.all()
        if search_query.last_searched_date:
            # hide products the latest scrape no longer found (delisted)
            products = products.filter(last_seen__gte=search_query.last_searched_date)
        products = products.annotate(
            unpriced=Case(When(price_huf=0, then=1), default=0,
                          output_field=IntegerField()),
        ).order_by("-score", "unpriced", "price_huf")
        if limit is not None:
            products = products[:limit]

        data = {
            "query": SearchQuerySerializer(search_query).data,
            "refreshed": bool(refresh_summary and refresh_summary["ok"]),
            "products": ProductSerializer(products, many=True).data,
        }
        if refresh_summary:
            data["scrape"] = {
                "stores_ok": refresh_summary["stores_ok"],
                "stores_failed": refresh_summary["stores_failed"],
                "new_products": refresh_summary["new"],
            }
            if not refresh_summary["ok"]:
                data["refresh_error"] = (
                    "every store failed to scrape; serving cached results"
                )
        return Response(data)

    @staticmethod
    def _is_stale(search_query) -> bool:
        return (
            search_query.last_searched_date is None
            or timezone.now() - search_query.last_searched_date > SEARCH_MAX_AGE
        )


class ProductViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows products to be viewed or edited.

    Provides list/retrieve/create/update/destroy at /api/products/.
    """

    # pagination needs a stable ordering; TODO: pick a meaningful one, e.g. "-score"
    queryset = Product.objects.all().order_by("-id")
    serializer_class = ProductSerializer
    # TODO: tighten permissions, e.g.
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    # TODO: filter by store / minimum score via query params, e.g.
    # def get_queryset(self):
    #     qs = super().get_queryset()
    #     store_id = self.request.query_params.get("store")
    #     ...
    #     return qs

    # TODO: custom endpoint template, e.g. trigger a scrape:
    # @action(detail=False, methods=["post"])
    # def scrape(self, request):
    #     ...
    #     return Response({"status": "started"})
    # (imports: from rest_framework.decorators import action
    #           from rest_framework.response import Response)