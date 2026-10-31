"""catalog/admin.py"""
from django.contrib import admin
from .models import Product, ProductVariant


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ("attribute_name", "attribute_value", "additional_price", "sku", "is_active")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "product_type", "base_sales_price", "tax_rate", "is_active")
    list_filter = ("product_type", "is_active")
    search_fields = ("name", "hsn_sac_code")
    inlines = [ProductVariantInline]
