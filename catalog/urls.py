"""catalog/urls.py"""
from django.urls import path
from . import views

app_name = "catalog"

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("products/create/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/toggle/", views.product_toggle, name="product_toggle"),
    path("products/<int:product_pk>/variants/create/", views.variant_create, name="variant_create"),
    path("variants/<int:pk>/edit/", views.variant_edit, name="variant_edit"),
]
