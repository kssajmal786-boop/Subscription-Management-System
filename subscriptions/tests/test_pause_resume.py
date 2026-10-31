from django.test import TestCase
from decimal import Decimal
from datetime import date, timedelta
from subscriptions.models import Customer, Product, ProductVariant, Plan, Subscription
from subscriptions.services import QuotationService, LifecycleService, PauseResumeService


class PauseResumeTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='Test Contact',
            company_name='Brightloop Software',
            email='ops@brightloop.io',
            billing_address='Bangalore'
        )

        self.product = Product.objects.create(
            name='Software A',
            product_type=Product.ProductType.LICENSE,
            base_sales_price=Decimal('2000.00'),
            tax_rate=Decimal('18.00')
        )

        self.plan = Plan.objects.create(
            plan_name='Odoo Monthly Plan',
            product=self.product,
            billing_cycle=Plan.BillingCycle.MONTHLY,
            base_price=Decimal('2000.00'),
            allow_pause=True,
            max_pause_days=30,
            default_duration=12
        )

        # Create, confirm, and activate subscription
        sub = QuotationService.create_quotation(
            customer=self.customer,
            plan=self.plan,
            lines_data=[{'product_id': self.product.product_id, 'quantity': 1}]
        )
        sub = LifecycleService.confirm_quotation(sub.pk, start_date=date(2026, 1, 1))
        self.subscription = LifecycleService.activate_subscription(sub.pk)

    def test_pause_and_resume_date_shift_math(self):
        sub = self.subscription
        initial_next_billing = sub.next_billing_date  # 2026-01-01
        initial_expiry = sub.expiry_date              # 2026-01-01 + 360 days = 2026-12-27

        # 1. Pause subscription on 2026-01-10
        pause_date = date(2026, 1, 10)
        paused_sub = PauseResumeService.pause_subscription(
            sub.pk,
            pause_date=pause_date,
            reason='System migration pause'
        )

        self.assertEqual(paused_sub.status, Subscription.Status.PAUSED)
        self.assertEqual(paused_sub.paused_at, pause_date)

        # 2. Resume subscription on 2026-01-25 (Paused for exactly 15 days)
        resume_date = date(2026, 1, 25)
        res = PauseResumeService.resume_subscription(
            sub.pk,
            resume_date=resume_date,
            user_name='Ops Admin'
        )

        resumed_sub = res['subscription']
        self.assertEqual(res['paused_days'], 15)
        self.assertEqual(resumed_sub.status, Subscription.Status.ACTIVE)
        self.assertIsNone(resumed_sub.paused_at)
        self.assertEqual(resumed_sub.total_paused_days, 15)

        # Verify next_billing_date and expiry_date were shifted forward by exactly 15 days!
        expected_new_billing = initial_next_billing + timedelta(days=15)
        expected_new_expiry = initial_expiry + timedelta(days=15)

        self.assertEqual(resumed_sub.next_billing_date, expected_new_billing)
        self.assertEqual(resumed_sub.expiry_date, expected_new_expiry)

        # Verify audit history
        last_history = resumed_sub.history.first()
        self.assertEqual(last_history.action, 'RESUMED')
        self.assertIn("resumed on 2026-01-25 after 15 days on pause", last_history.description)

    def test_pause_not_allowed_on_plan(self):
        self.plan.allow_pause = False
        self.plan.save()

        with self.assertRaises(ValueError):
            PauseResumeService.pause_subscription(self.subscription.pk)

    def test_resume_date_cannot_precede_pause_date(self):
        PauseResumeService.pause_subscription(self.subscription.pk, pause_date=date(2026, 2, 10))

        with self.assertRaises(ValueError):
            PauseResumeService.resume_subscription(self.subscription.pk, resume_date=date(2026, 2, 5))
