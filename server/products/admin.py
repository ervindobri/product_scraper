from django.contrib import admin

# Register your models here.
from django.contrib import admin

from .models import PriceHistory, Product, SearchQuery, Store

admin.site.register(Store)
admin.site.register(Product)
admin.site.register(SearchQuery)
admin.site.register(PriceHistory)