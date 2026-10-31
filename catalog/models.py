"""
catalog/models.py – Products and Product Variants.
"""
from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Product(models.Model):
    class ProductType(models.TextChoices):
        SERVICE = "Service", "Service"
        LICENSE = "License", "License"
        CONSUMABLE = "Consumable", "Consumable"

    name = models.CharField(max_length=200)
    product_type = models.CharField(max_length=20, choices=ProductType.choices, default=ProductType.SERVICE)
    base_sales_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"), help_text="Tax % (e.g. 18 for 18% GST)")
    hsn_sac_code = models.CharField(max_length=20, blank=True, verbose_name="HSN/SAC Code")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        indexes = [models.Index(fields=["is_active", "name"])]
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def effective_price(self):
        """Base price – variants add on top of this."""
        return self.base_sales_price


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    attribute_name = models.CharField(max_length=100, help_text="e.g. Brand, Edition, Deployment Type")
    attribute_value = models.CharField(max_length=100, help_text="e.g. Odoo Enterprise, Standard")
    additional_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"),
                                           help_text="Added on top of product base price")
    sku = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "product_variants"
        unique_together = [("product", "attribute_name", "attribute_value")]
        ordering = ["attribute_name", "attribute_value"]

    def __str__(self):
        return f"{self.product.name} – {self.attribute_value}"

    @property
    def effective_price(self):
        return self.product.base_sales_price + self.additional_price

    @property
    def tax_rate(self):
        return self.product.tax_rate


def __getattr__(name):
    """
    Cross-app compatibility: Dynamically re-export Plan and Discount
    without circular import issues.
    """
    if name == "Plan":
        from subscriptions.models import Plan
        return Plan
    if name == "Discount":
        from billing.models import Discount
        return Discount
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

