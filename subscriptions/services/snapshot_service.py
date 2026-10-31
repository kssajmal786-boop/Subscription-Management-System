from decimal import Decimal
from django.db import transaction
from catalog.models import Product, ProductVariant
from subscriptions.models import SubscriptionLine, Subscription


class SnapshotService:
    """
    Enforces contract immutability by snapshotting agreed product prices,
    variant price differentials, and tax rates at quotation creation and confirmation.
    Future catalog price or tax changes will NOT modify existing subscription lines.
    """

    @staticmethod
    def get_effective_price_and_tax(product: Product, variant: ProductVariant = None):
        """
        Calculates the current catalog unit price and tax rate for a product/variant pair.
        """
        if variant:
            if variant.product_id != product.pk:
                raise ValueError(f"Variant {variant.sku} does not belong to Product {product.name}")
            unit_price = variant.effective_price
        else:
            unit_price = product.base_sales_price

        tax_rate = product.tax_rate
        return Decimal(unit_price), Decimal(tax_rate)

    @staticmethod
    @transaction.atomic
    def create_line_with_snapshot(
        subscription: Subscription,
        product: Product,
        variant: ProductVariant = None,
        quantity: int = 1,
        custom_price: Decimal = None,
        custom_tax_rate: Decimal = None
    ) -> SubscriptionLine:
        """
        Creates a new SubscriptionLine with snapshot unit_price and tax_rate.
        """
        if quantity < 1:
            raise ValueError("Line quantity must be at least 1.")

        catalog_price, catalog_tax_rate = SnapshotService.get_effective_price_and_tax(product, variant)
        
        unit_price = custom_price if custom_price is not None else catalog_price
        tax_rate = custom_tax_rate if custom_tax_rate is not None else catalog_tax_rate

        line = SubscriptionLine.objects.create(
            subscription=subscription,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_price=Decimal(unit_price).quantize(Decimal('0.01')),
            tax_rate=Decimal(tax_rate).quantize(Decimal('0.01'))
        )
        return line

    @staticmethod
    @transaction.atomic
    def verify_and_lock_snapshots(subscription: Subscription):
        """
        Verifies that all lines on a subscription have valid frozen snapshots.
        Ensures line_subtotal, tax_amount, and line_total are calculated and persisted.
        """
        lines = subscription.lines.select_for_update().all()
        if not lines.exists():
            raise ValueError("Subscription has no line items.")

        for line in lines:
            line.save()  # Recalculates line_subtotal, tax_amount, line_total from frozen snapshots
