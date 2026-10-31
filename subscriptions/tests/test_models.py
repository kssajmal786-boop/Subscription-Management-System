from django.test import TestCase
from decimal import Decimal
from datetime import date, timedelta
from subscriptions.models import Customer, Product, ProductVariant, Plan, Discount


class ModelTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='Test Contact',
            company_name='Test Company',
            email='test@example.com',
            billing_address='123 Test St',
            gst_number='29ABCDE1234F1Z5'
        )

        self.product = Product.objects.create(
            name='Software A',
            product_type=Product.ProductType.LICENSE,
            base_sales_price=Decimal('2000.00'),
            cost_price=Decimal('1000.00'),
            tax_rate=Decimal('18.00'),
            hsn_sac_code='997331'
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            attribute_name='Edition',
            attribute_value='Odoo Enterprise',
            additional_price=Decimal('560.00'),
            sku='SOFT-A-ODOO-ENT'
        )

    def test_product_creation_and_effective_price(self):
        self.assertEqual(self.product.base_sales_price, Decimal('2000.00'))
        self.assertEqual(self.variant.effective_price, Decimal('2560.00'))
        self.assertEqual(self.product.active_variants_count, 1)

    def test_product_soft_archive(self):
        self.assertTrue(self.product.is_active)
        self.product.is_active = False
        self.product.save()
        self.assertFalse(Product.objects.get(pk=self.product.pk).is_active)

    def test_plan_configuration(self):
        plan = Plan.objects.create(
            plan_name='Enterprise Monthly',
            product=self.product,
            variant=self.variant,
            billing_cycle=Plan.BillingCycle.MONTHLY,
            base_price=Decimal('2560.00'),
            min_quantity=2,
            allow_pause=True,
            max_pause_days=30,
            grace_period_days=10
        )
        self.assertEqual(plan.base_price, Decimal('2560.00'))
        self.assertEqual(plan.min_quantity, 2)
        self.assertTrue(plan.allow_pause)

    def test_discount_calculations(self):
        # Percentage discount
        d_pct = Discount.objects.create(
            code='SAVE10',
            name='10% Off',
            discount_type=Discount.DiscountType.PERCENTAGE,
            discount_value=Decimal('10.00'),
            min_purchase_amount=Decimal('1000.00'),
            is_active=True
        )
        self.assertTrue(d_pct.is_valid_now())
        self.assertEqual(d_pct.calculate_discount(Decimal('5000.00')), Decimal('500.00'))
        # Subtotal below min purchase
        self.assertEqual(d_pct.calculate_discount(Decimal('500.00')), Decimal('0.00'))

        # Fixed discount
        d_fix = Discount.objects.create(
            code='FLAT300',
            name='Flat 300 Off',
            discount_type=Discount.DiscountType.FIXED,
            discount_value=Decimal('300.00'),
            min_purchase_amount=Decimal('1000.00'),
            is_active=True
        )
        self.assertEqual(d_fix.calculate_discount(Decimal('2000.00')), Decimal('300.00'))
