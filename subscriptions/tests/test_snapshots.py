from django.test import TestCase
from decimal import Decimal
from subscriptions.models import Customer, Product, ProductVariant, Plan, Subscription, SubscriptionLine
from subscriptions.services import QuotationService, LifecycleService


class SnapshotImmutabilityTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='Test Customer',
            company_name='Brightloop Software',
            email='contracts@brightloop.io',
            billing_address='Bangalore'
        )

        self.product = Product.objects.create(
            name='Software A',
            product_type=Product.ProductType.LICENSE,
            base_sales_price=Decimal('2000.00'),
            tax_rate=Decimal('18.00')
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            attribute_name='Edition',
            attribute_value='Odoo Enterprise',
            additional_price=Decimal('560.00'),
            sku='SOFT-A-ODOO'
        )

        self.plan = Plan.objects.create(
            plan_name='Odoo Monthly Plan',
            product=self.product,
            variant=self.variant,
            billing_cycle=Plan.BillingCycle.MONTHLY,
            base_price=Decimal('2560.00'),
            min_quantity=1
        )

    def test_catalog_price_change_does_not_affect_existing_subscription(self):
        # 1. Create and confirm quotation with 2 units @ ₹2,560.00 + 18% tax
        sub = QuotationService.create_quotation(
            customer=self.customer,
            plan=self.plan,
            lines_data=[
                {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 2}
            ]
        )
        sub = LifecycleService.confirm_quotation(sub.pk)

        line = sub.lines.first()
        self.assertEqual(line.unit_price, Decimal('2560.00'))
        self.assertEqual(line.tax_rate, Decimal('18.00'))
        self.assertEqual(line.line_subtotal, Decimal('5120.00'))
        self.assertEqual(line.tax_amount, Decimal('921.60'))
        self.assertEqual(line.line_total, Decimal('6041.60'))
        original_total = sub.total_amount
        self.assertEqual(original_total, Decimal('6041.60'))

        # 2. Now simulate catalog price increase!
        # Base price increases from 2000 to 3500!
        self.product.base_sales_price = Decimal('3500.00')
        # Tax rate changes from 18% to 28%!
        self.product.tax_rate = Decimal('28.00')
        self.product.save()

        # Variant additional price increases from 560 to 1000!
        self.variant.additional_price = Decimal('1000.00')
        self.variant.save()

        # Effective price in catalog is now 3500 + 1000 = 4500.00!
        self.assertEqual(self.variant.effective_price, Decimal('4500.00'))

        # 3. Reload existing subscription and line from database
        sub.refresh_from_db()
        line.refresh_from_db()

        # The existing contract MUST remain completely unchanged!
        self.assertEqual(line.unit_price, Decimal('2560.00'))
        self.assertEqual(line.tax_rate, Decimal('18.00'))
        self.assertEqual(line.line_subtotal, Decimal('5120.00'))
        self.assertEqual(line.tax_amount, Decimal('921.60'))
        self.assertEqual(line.line_total, Decimal('6041.60'))
        self.assertEqual(sub.total_amount, Decimal('6041.60'))
