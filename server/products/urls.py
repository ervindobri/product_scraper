from django.urls import include, path
from rest_framework import routers
from . import views


# Routers automatically generate the URL conf for viewsets
# (list/detail routes + the browsable API root).
router = routers.DefaultRouter()
router.register(r"stores", views.StoreViewSet)
router.register(r"products", views.ProductViewSet)
router.register(r"queries", views.SearchQueryViewSet)

app_name = "products"
urlpatterns = [
    # ex: /products/
    path("", views.IndexView.as_view(), name="index"),
    # ex: /products/1/
    path("<int:pk>/", views.DetailView.as_view(), name="detail"),
    # ex: /products/1/pub_date/
    path("<int:pk>/pub_date/", views.pub_date, name="pub_date"),
    # REST API: /products/api/stores/, /products/api/products/
    path("api/", include(router.urls)),
    # NOTE: login/logout for the browsable API lives in mysite/urls.py
    # (a nested namespace here would hide the login link).
]
