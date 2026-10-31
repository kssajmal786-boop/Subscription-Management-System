from django.test import TestCase
from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from subscriptions.models import Customer, Product, ProductVariant, Plan, Discount, Subscription
from subscriptions.services import QuotationService, LifecycleService


class SubscriptionLifecycleTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='Rajesh Sharma',
            company_name='Brightloop Software',
            email='rajesh@brightloop.io',
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
            default_duration=12,
            min_quantity=1
        )

        self.discount = Discount.objects.create(
            code='DISC500',
            name='500 Off',
            discount_type=Discount.DiscountType.FIXED,
            discount_value=Decimal('500.00'),
            is_active=True
        )

        self.quotation = QuotationService.create_quotation(
            customer=self.customer,
            plan=self.plan,
            lines_data=[
                {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 1}
            ],
            discount_code='DISC500'
        )

    def test_quotation_conversion_to_subscription(self):
        original_number = self.quotation.subscription_number
        self.assertTrue(original_number.startswith('QUO-'))

        today = date.today()
        # Confirm quotation
        sub = LifecycleService.confirm_quotation(self.quotation.pk, start_date=today, user_name='Sales Mgr')

        self.assertEqual(sub.status, Subscription.Status.CONFIRMED)
        self.assertTrue(sub.subscription_number.startswith('SUB-'))
        self.assertEqual(sub.quotation_number, original_number)
        self.assertEqual(sub.start_date, today)
        self.assertEqual(sub.next_billing_date, today)
        
        # 12 monthly cycles = 360 days
        expected_expiry = today + timedelta(days=360)
        self.assertEqual(sub.expiry_date, expected_expiry)

        # Discount used count incremented
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.used_count, 1)

    def test_activate_subscription(self):
        LifecycleService.confirm_quotation(self.quotation.pk)
        active_sub = LifecycleService.activate_subscription(self.quotation.pk, user_name='System')

        self.assertEqual(active_sub.status, Subscription.Status.ACTIVE)
        self.assertIsNotNone(active_sub.next_billing_date)

    def test_cancel_subscription(self):
        cancelled_sub = LifecycleService.cancel_subscription(
            self.quotation.pk,
            reason='Customer changed requirements'
        )
        self.assertEqual(cancelled_sub.status, Subscription.Status.CANCELLED)

    def test_close_subscription(self):
        closed_sub = LifecycleService.close_subscription(
            self.quotation.pk,
            reason='End of contract term'
        )
        self.assertEqual(closed_sub.status, Subscription.Status.CLOSED)
