"""
billing/tests.py
================
Unit tests for:
  1. Tax calculations
  2. Discount eligibility and amount computation
  3. Invoice generation (idempotency, duplicate prevention)
  4. Payment reconciliation (full, partial, overpayment rejection)
  5. Concurrent duplicate invoice prevention

Run with: python manage.py test billing
"""
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import User, Customer
from catalog.models import Product, ProductVariant
from subscriptions.models import Plan, Subscription, SubscriptionLine
from billing.models import Discount, Invoice, InvoiceLine, Payment
from billing.services import BillingService, _q


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures Helper
# ─────────────────────────────────────────────────────────────────────────────
def make_user(email, role="Customer"):
    return User.objects.create_user(
        email=email, password="Test@1234", first_name="Test", last_name="User", role=role
    )


def make_customer(email="cust@test.com"):
    user = make_user(email, "Customer")
    return Customer.objects.create(user=user, company_name="Test Co")


def make_product(name="Software A", price="2000.00", tax_rate="18.00"):
    return Product.objects.create(
        name=name,
        product_type="Service",
        base_sales_price=Decimal(price),
        tax_rate=Decimal(tax_rate),
    )


def make_plan(product, price="2000.00", cycle="Monthly"):
    return Plan.objects.create(
        product=product,
        plan_name=f"{product.name} {cycle}",
        billing_cycle=cycle,
        base_price=Decimal(price),
        min_quantity=1,
        default_duration_months=12,
        grace_period_days=7,
    )


def make_subscription(customer, plan, status="Active", billing_date=None):
    today = billing_date or date.today()
    sub = Subscription.objects.create(
        subscription_number=Subscription.generate_number(),
        customer=customer,
        plan=plan,
        status=status,
        start_date=today,
        next_billing_date=today,
        expiry_date=today + timedelta(days=365),
        auto_renew=True,
    )
    SubscriptionLine.objects.create(
        subscription=sub,
        product=plan.product,
        quantity=1,
        unit_price=plan.base_price,
        tax_rate=plan.product.tax_rate,
    )
    return sub


def make_discount(code="SAVE10", dtype="Percentage", value="10.00",
                  start_days=0, end_days=30,
                  min_amount="0.00", min_qty=1, max_usage=None):
    today = date.today()
    return Discount.objects.create(
        code=code,
        name=f"Test Discount {code}",
        discount_type=dtype,
        discount_value=Decimal(value),
        start_date=today - timedelta(days=start_days),
        end_date=today + timedelta(days=end_days),
        min_purchase_amount=Decimal(min_amount),
        min_quantity=min_qty,
        max_usage_limit=max_usage,
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tax Calculation Tests
# ─────────────────────────────────────────────────────────────────────────────
class TaxCalculationTests(TestCase):
    """Test that GST tax is computed correctly on invoice lines."""

    def test_18_percent_tax_on_2000(self):
        """₹2,000 × 18% = ₹360.00 tax, ₹2,360 total."""
        taxable = Decimal("2000.00")
        tax_rate = Decimal("18.00")
        tax = _q(taxable * tax_rate / 100)
        self.assertEqual(tax, Decimal("360.00"))

    def test_zero_tax(self):
        taxable = Decimal("5000.00")
        tax = _q(taxable * Decimal("0.00") / 100)
        self.assertEqual(tax, Decimal("0.00"))

    def test_tax_decimal_precision(self):
        """Ensure no floating-point drift on ₹1,333.33 × 18%."""
        taxable = Decimal("1333.33")
        tax = _q(taxable * Decimal("18.00") / 100)
        self.assertEqual(tax, Decimal("240.00"))  # 240.0 rounded to 2dp

    def test_variant_price_calculation(self):
        """Odoo variant: base ₹2000 + additional ₹560 = ₹2560."""
        product = make_product(price="2000.00")
        variant = ProductVariant.objects.create(
            product=product,
            attribute_name="Brand",
            attribute_value="Odoo Enterprise",
            additional_price=Decimal("560.00"),
        )
        self.assertEqual(variant.effective_price, Decimal("2560.00"))
        tax = _q(variant.effective_price * Decimal("18.00") / 100)
        self.assertEqual(tax, Decimal("460.80"))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Discount Engine Tests
# ─────────────────────────────────────────────────────────────────────────────
class DiscountEligibilityTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.product = make_product()

    def test_percentage_discount_calculation(self):
        discount = make_discount(code="PCT10", dtype="Percentage", value="10.00")
        amount = discount.calculate_discount_amount(Decimal("2000.00"))
        self.assertEqual(amount, Decimal("200.00"))

    def test_fixed_discount_calculation(self):
        discount = make_discount(code="FIX500", dtype="Fixed", value="500.00")
        amount = discount.calculate_discount_amount(Decimal("2000.00"))
        self.assertEqual(amount, Decimal("500.00"))

    def test_fixed_discount_cannot_exceed_subtotal(self):
        discount = make_discount(code="BIGFIX", dtype="Fixed", value="9999.00")
        amount = discount.calculate_discount_amount(Decimal("100.00"))
        self.assertEqual(amount, Decimal("100.00"))  # Capped at subtotal

    def test_percentage_discount_with_cap(self):
        discount = make_discount(code="CAPPCT", dtype="Percentage", value="50.00")
        discount.max_discount_cap = Decimal("300.00")
        discount.save()
        amount = discount.calculate_discount_amount(Decimal("2000.00"))
        self.assertEqual(amount, Decimal("300.00"))  # 50% of 2000=1000, capped at 300

    def test_expired_discount_not_eligible(self):
        discount = Discount.objects.create(
            code="EXPIRED",
            name="Expired",
            discount_type="Fixed",
            discount_value=Decimal("100.00"),
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        eligible, reason = discount.is_eligible(
            Decimal("1000.00"), 1, self.customer
        )
        self.assertFalse(eligible)
        self.assertIn("expired", reason.lower())

    def test_min_purchase_amount_gate(self):
        discount = make_discount(code="MINAMT", min_amount="5000.00")
        eligible, reason = discount.is_eligible(
            Decimal("2000.00"), 1, self.customer
        )
        self.assertFalse(eligible)
        self.assertIn("Minimum purchase", reason)

    def test_max_usage_limit_gate(self):
        discount = make_discount(code="MAXUSE", max_usage=5)
        discount.used_count = 5
        discount.save()
        eligible, reason = discount.is_eligible(
            Decimal("2000.00"), 1, self.customer
        )
        self.assertFalse(eligible)
        self.assertIn("limit", reason.lower())

    def test_first_invoice_only_gate(self):
        discount = Discount.objects.create(
            code="FIRSTONLY",
            name="First Invoice Only",
            discount_type="Percentage",
            discount_value=Decimal("15.00"),
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            applicable_cycles=Discount.ApplicableTo.FIRST_INVOICE,
            is_active=True,
        )
        eligible, reason = discount.is_eligible(
            Decimal("2000.00"), 1, self.customer, invoice_sequence=2
        )
        self.assertFalse(eligible)

    def test_validate_discount_code_via_service(self):
        make_discount(code="VALID20", dtype="Percentage", value="20.00")
        discount, amount, error = BillingService.validate_discount_code(
            code="VALID20",
            subtotal=Decimal("1000.00"),
            total_quantity=1,
            customer=self.customer,
        )
        self.assertIsNone(error)
        self.assertEqual(amount, Decimal("200.00"))

    def test_invalid_discount_code_via_service(self):
        discount, amount, error = BillingService.validate_discount_code(
            code="DOESNOTEXIST",
            subtotal=Decimal("1000.00"),
            total_quantity=1,
            customer=self.customer,
        )
        self.assertIsNotNone(error)
        self.assertEqual(amount, Decimal("0.00"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Invoice Generation Tests (Idempotency)
# ─────────────────────────────────────────────────────────────────────────────
class InvoiceGenerationTests(TestCase):
    def setUp(self):
        self.customer = make_customer("inv@test.com")
        self.product = make_product()
        self.plan = make_plan(self.product, price="2000.00")

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_invoice_generated_correctly(self, mock_pdf):
        sub = make_subscription(self.customer, self.plan)
        invoice = BillingService.generate_invoice_for_subscription(sub)

        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.status, Invoice.Status.CONFIRMED)
        self.assertEqual(invoice.customer, self.customer)
        self.assertEqual(invoice.subtotal, Decimal("2000.00"))
        self.assertEqual(invoice.tax_amount, Decimal("360.00"))
        self.assertEqual(invoice.total_amount, Decimal("2360.00"))
        self.assertEqual(invoice.balance_due, Decimal("2360.00"))
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_invoice_number_format(self, mock_pdf):
        sub = make_subscription(self.customer, self.plan)
        invoice = BillingService.generate_invoice_for_subscription(sub)
        year = timezone.now().year
        self.assertTrue(invoice.invoice_number.startswith(f"INV-{year}-"))

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_idempotent_duplicate_prevention_same_period(self, mock_pdf):
        """Calling generate twice for the same period must return the same invoice."""
        sub = make_subscription(self.customer, self.plan)
        inv1 = BillingService.generate_invoice_for_subscription(sub)

        # Reset next_billing_date to same date to simulate duplicate call
        sub.refresh_from_db()
        sub.next_billing_date = inv1.billing_period_start
        sub.save(update_fields=["next_billing_date"])

        # This should detect the existing invoice and return it without creating a new one
        # (Application-level check)
        inv2 = BillingService.generate_invoice_for_subscription(sub)

        all_invoices = Invoice.objects.filter(subscription=sub).exclude(status="Cancelled")
        self.assertEqual(all_invoices.count(), 1)

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_discount_applied_to_invoice(self, mock_pdf):
        discount = make_discount(code="D10PCT", dtype="Percentage", value="10.00")
        sub = make_subscription(self.customer, self.plan)
        sub.applied_discount = discount
        sub.save()

        invoice = BillingService.generate_invoice_for_subscription(sub)
        self.assertEqual(invoice.discount_amount, Decimal("200.00"))   # 10% of 2000
        self.assertEqual(invoice.taxable_amount, Decimal("1800.00"))
        self.assertEqual(invoice.tax_amount, Decimal("324.00"))        # 18% of 1800
        self.assertEqual(invoice.total_amount, Decimal("2124.00"))

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_next_billing_date_advances(self, mock_pdf):
        sub = make_subscription(self.customer, self.plan)
        original_date = sub.next_billing_date
        invoice = BillingService.generate_invoice_for_subscription(sub)
        sub.refresh_from_db()
        # Monthly cycle: next billing should be original + ~1 month
        self.assertGreater(sub.next_billing_date, original_date)

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_skips_non_active_subscription(self, mock_pdf):
        sub = make_subscription(self.customer, self.plan, status="Paused")
        result = BillingService.generate_invoice_for_subscription(sub)
        self.assertIsNone(result)

    @patch("billing.tasks.generate_invoice_pdf_task.delay")
    def test_invoice_lines_created(self, mock_pdf):
        sub = make_subscription(self.customer, self.plan)
        invoice = BillingService.generate_invoice_for_subscription(sub)
        lines = invoice.lines.all()
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().quantity, 1)
        self.assertEqual(lines.first().unit_price, Decimal("2000.00"))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Payment Reconciliation Tests
# ─────────────────────────────────────────────────────────────────────────────
class PaymentReconciliationTests(TestCase):
    def setUp(self):
        self.admin_user = make_user("admin@test.com", "Admin")
        self.customer = make_customer("pay@test.com")
        self.product = make_product()
        self.plan = make_plan(self.product)

    def _make_invoice(self, total="2360.00"):
        """Create a Confirmed invoice directly."""
        sub = make_subscription(self.customer, self.plan)
        return Invoice.objects.create(
            invoice_number=Invoice.generate_number(),
            subscription=sub,
            customer=self.customer,
            billing_period_start=date.today(),
            billing_period_end=date.today() + timedelta(days=29),
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=15),
            subtotal=Decimal("2000.00"),
            discount_amount=Decimal("0.00"),
            taxable_amount=Decimal("2000.00"),
            tax_amount=Decimal("360.00"),
            total_amount=Decimal(total),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal(total),
            status=Invoice.Status.CONFIRMED,
        )

    @patch("billing.tasks.send_payment_confirmation_task.delay")
    def test_full_payment_marks_paid(self, mock_task):
        invoice = self._make_invoice()
        payment = BillingService.record_payment(
            invoice_id=invoice.pk,
            amount=Decimal("2360.00"),
            payment_method="Bank_Transfer",
            payment_date=date.today(),
            recorded_by=self.admin_user,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertEqual(invoice.amount_paid, Decimal("2360.00"))
        self.assertEqual(payment.status, Payment.Status.SUCCESS)

    @patch("billing.tasks.send_payment_confirmation_task.delay")
    def test_partial_payment_marks_partially_paid(self, mock_task):
        invoice = self._make_invoice()
        BillingService.record_payment(
            invoice_id=invoice.pk,
            amount=Decimal("1000.00"),
            payment_method="UPI",
            payment_date=date.today(),
            recorded_by=self.admin_user,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_paid, Decimal("1000.00"))
        self.assertEqual(invoice.balance_due, Decimal("1360.00"))

    @patch("billing.tasks.send_payment_confirmation_task.delay")
    def test_second_partial_payment_completes_invoice(self, mock_task):
        invoice = self._make_invoice()
        BillingService.record_payment(
            invoice_id=invoice.pk, amount=Decimal("1000.00"),
            payment_method="Cash", payment_date=date.today(), recorded_by=self.admin_user
        )
        BillingService.record_payment(
            invoice_id=invoice.pk, amount=Decimal("1360.00"),
            payment_method="UPI", payment_date=date.today(), recorded_by=self.admin_user
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))

    def test_overpayment_rejected(self):
        invoice = self._make_invoice()
        with self.assertRaises(ValueError) as ctx:
            BillingService.record_payment(
                invoice_id=invoice.pk,
                amount=Decimal("9999.00"),  # More than balance
                payment_method="Cash",
                payment_date=date.today(),
                recorded_by=self.admin_user,
            )
        self.assertIn("exceeds balance", str(ctx.exception))

    def test_zero_payment_rejected(self):
        invoice = self._make_invoice()
        with self.assertRaises(ValueError):
            BillingService.record_payment(
                invoice_id=invoice.pk, amount=Decimal("0.00"),
                payment_method="Cash", payment_date=date.today(), recorded_by=self.admin_user
            )

    def test_payment_on_paid_invoice_rejected(self):
        invoice = self._make_invoice()
        invoice.status = Invoice.Status.PAID
        invoice.save()
        with self.assertRaises(ValueError) as ctx:
            BillingService.record_payment(
                invoice_id=invoice.pk, amount=Decimal("100.00"),
                payment_method="Cash", payment_date=date.today(), recorded_by=self.admin_user
            )
        self.assertIn("paid", str(ctx.exception).lower())

    @patch("billing.tasks.send_payment_confirmation_task.delay")
    def test_payment_number_format(self, mock_task):
        invoice = self._make_invoice()
        payment = BillingService.record_payment(
            invoice_id=invoice.pk, amount=invoice.balance_due,
            payment_method="Card", payment_date=date.today(), recorded_by=self.admin_user
        )
        year = timezone.now().year
        self.assertTrue(payment.payment_number.startswith(f"PAY-{year}-"))

    @patch("billing.tasks.send_payment_confirmation_task.delay")
    def test_past_due_subscription_restored_on_full_payment(self, mock_task):
        """Paying off an overdue invoice should restore subscription to Active."""
        sub = make_subscription(self.customer, self.plan)
        sub.status = "Past_Due"
        sub.save()
        invoice = Invoice.objects.create(
            invoice_number=Invoice.generate_number(),
            subscription=sub,
            customer=self.customer,
            billing_period_start=date.today() - timedelta(days=30),
            billing_period_end=date.today() - timedelta(days=1),
            invoice_date=date.today() - timedelta(days=30),
            due_date=date.today() - timedelta(days=15),
            subtotal=Decimal("2000.00"),
            discount_amount=Decimal("0.00"),
            taxable_amount=Decimal("2000.00"),
            tax_amount=Decimal("360.00"),
            total_amount=Decimal("2360.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("2360.00"),
            status=Invoice.Status.OVERDUE,
        )
        BillingService.record_payment(
            invoice_id=invoice.pk, amount=Decimal("2360.00"),
            payment_method="Bank_Transfer", payment_date=date.today(), recorded_by=self.admin_user
        )
        sub.refresh_from_db()
        self.assertEqual(sub.status, "Active")


# ─────────────────────────────────────────────────────────────────────────────
# 5. DB Unique Constraint Test (Duplicate Invoice Prevention)
# ─────────────────────────────────────────────────────────────────────────────
class DuplicateInvoicePreventionTests(TestCase):
    """
    Verify the DB-level unique constraint uq_sub_period prevents
    duplicate non-cancelled invoices for the same billing period.
    """

    def setUp(self):
        self.customer = make_customer("dup@test.com")
        self.product = make_product()
        self.plan = make_plan(self.product)
        self.sub = make_subscription(self.customer, self.plan)

    def test_unique_constraint_raises_on_duplicate(self):
        """Inserting two non-cancelled invoices for same period raises IntegrityError."""
        from django.db import IntegrityError
        period_start = date.today()
        period_end = date.today() + timedelta(days=29)

        Invoice.objects.create(
            invoice_number="INV-TEST-00001",
            subscription=self.sub,
            customer=self.customer,
            billing_period_start=period_start,
            billing_period_end=period_end,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=15),
            subtotal=Decimal("2000.00"),
            taxable_amount=Decimal("2000.00"),
            tax_amount=Decimal("360.00"),
            total_amount=Decimal("2360.00"),
            balance_due=Decimal("2360.00"),
            status=Invoice.Status.CONFIRMED,
        )

        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                invoice_number="INV-TEST-00002",
                subscription=self.sub,
                customer=self.customer,
                billing_period_start=period_start,
                billing_period_end=period_end,
                invoice_date=date.today(),
                due_date=date.today() + timedelta(days=15),
                subtotal=Decimal("2000.00"),
                taxable_amount=Decimal("2000.00"),
                tax_amount=Decimal("360.00"),
                total_amount=Decimal("2360.00"),
                balance_due=Decimal("2360.00"),
                status=Invoice.Status.CONFIRMED,
            )

    def test_cancelled_invoices_allowed_same_period(self):
        """Cancelled invoices should not trigger the unique constraint."""
        period_start = date.today()
        period_end = date.today() + timedelta(days=29)
        base_kwargs = dict(
            subscription=self.sub, customer=self.customer,
            billing_period_start=period_start, billing_period_end=period_end,
            invoice_date=date.today(), due_date=date.today() + timedelta(days=15),
            subtotal=Decimal("2000.00"), taxable_amount=Decimal("2000.00"),
            tax_amount=Decimal("360.00"), total_amount=Decimal("2360.00"),
            balance_due=Decimal("2360.00"),
        )
        Invoice.objects.create(invoice_number="INV-CAN-001", status=Invoice.Status.CANCELLED, **base_kwargs)
        # This should not raise (cancelled + confirmed is allowed)
        Invoice.objects.create(invoice_number="INV-ACT-001", status=Invoice.Status.CONFIRMED, **base_kwargs)
        self.assertEqual(Invoice.objects.filter(subscription=self.sub).count(), 2)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Subscription Pause/Resume Tests
# ─────────────────────────────────────────────────────────────────────────────
class SubscriptionPauseResumeTests(TestCase):
    def setUp(self):
        self.customer = make_customer("pause@test.com")
        self.product = make_product()
        self.plan = make_plan(self.product)
        self.plan.allow_pause = True
        self.plan.save()

    def test_pause_active_subscription(self):
        sub = make_subscription(self.customer, self.plan)
        result = sub.pause(pause_date=date.today())
        self.assertTrue(result)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "Paused")
        self.assertEqual(sub.paused_at, date.today())

    def test_resume_shifts_billing_date(self):
        sub = make_subscription(self.customer, self.plan)
        original_billing = sub.next_billing_date
        pause_date = date.today()
        sub.pause(pause_date=pause_date)

        resume_date = pause_date + timedelta(days=10)
        sub.resume(resume_date=resume_date)
        sub.refresh_from_db()

        self.assertEqual(sub.status, "Active")
        self.assertEqual(sub.total_paused_days, 10)
        self.assertEqual(sub.next_billing_date, original_billing + timedelta(days=10))

    def test_cannot_pause_already_paused(self):
        sub = make_subscription(self.customer, self.plan)
        sub.pause()
        result = sub.pause()  # Second pause attempt
        self.assertFalse(result)

    def test_cannot_resume_active_subscription(self):
        sub = make_subscription(self.customer, self.plan)
        result = sub.resume()
        self.assertFalse(result)
