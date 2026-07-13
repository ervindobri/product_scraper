# format django data into json

from rest_framework import serializers

from .models import Product, SearchQuery, Store


class SearchQuerySerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchQuery
        fields = ["id", "query", "results_count", "last_searched_date"]

    # TODO: expose the query's products if needed, e.g.
    # products = ProductSerializer(many=True, read_only=True)
    # (define below ProductSerializer, or use a nested serializer)


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = [
            "id", "name", "url", "country", "pub_date",
            # scrape health, maintained by the refresh service
            "last_success", "failure_count",
        ]

    # TODO: add custom field validation if needed, e.g.
    # def validate_url(self, value):
    #     ...
    #     return value


class ProductSerializer(serializers.ModelSerializer):
    # represent the store by name (readable and writable, e.g. "Alza.hu")
    store = serializers.SlugRelatedField(
        slug_field="name",
        queryset=Store.objects.all(),
    )

    class Meta:
        model = Product
        fields = [
            "id", "store", "query", "name", "url",
            "price", "currency", "price_huf",
            "score", "first_seen", "last_seen",
        ]

    # TODO: expose computed fields if needed, e.g.
    # score_passes = serializers.SerializerMethodField()
    # def get_score_passes(self, obj):
    #     return obj.score_passes()
