"""
billing/services.py
==================
BillingService – Core financial calculation engine.

Architecture:
  - All monetary math uses Decimal(12,2); never float.
  - Invoice generation is wrapped in transaction.atomic() + select_for_update().
  - The DB UNIQUE constraint on (subscription_id, period_start, period_end) is the
    final guard against race-condition duplicate invoices.
  - Payment reconciliation locks the Invoice row before writing.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize to 2 decimal places using banker's rounding."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class BillingService:
    """Stateless service class – all methods are class/static methods."""

    # ------------------------------------------------------------------
    # 1. Idempotent Invoice Generation
    # ------------------------------------------------------------------
    @classmethod
    def generate_invoice_for_subscription(cls, subscription, billing_date=None):
        """
        Generate an invoice for one subscription billing cycle.

        Steps:
          1. Acquire row-level lock on subscription.
          2. Compute billing window.
          3. Check for existing non-cancelled invoice (app + DB guard).
          4. Build line items from SubscriptionLines (snapshotted prices).
          5. Apply eligible discount.
          6. Calculate per-line taxes.
          7. Insert Invoice + InvoiceLines atomically.
          8. Advance next_billing_date.
          9. Enqueue async PDF + email tasks.

        Returns: Invoice instance or None if skipped (duplicate / not due).
        """
        from .models import Invoice, InvoiceLine, Discount, MonthlyRevenueSnapshot
        from subscriptions.models import Subscription

        billing_date = billing_date or timezone.now().date()

        with transaction.atomic():
            # Step 1 – Row-level lock on subscription
            sub = (
                Subscription.objects
                .select_for_update()
                .select_related("customer", "plan", "applied_discount")
                .get(pk=subscription.pk)
            )

            if sub.status != Subscription.Status.ACTIVE:
                logger.info("Skipping non-active subscription %s (status=%s)", sub.pk, sub.status)
                return None

            if sub.next_billing_date and sub.next_billing_date > billing_date:
                logger.info("Subscription %s not yet due (next=%s)", sub.pk, sub.next_billing_date)
                return None

            # Step 2 – Compute billing window
            period_start = sub.next_billing_date or billing_date
            delta = sub.plan.cycle_delta()
            period_end = period_start + delta - __import__("datetime").timedelta(days=1)

            # Step 3 – Duplicate check (application-level before DB insert)
            existing = Invoice.objects.filter(
                subscription=sub,
                billing_period_start=period_start,
                billing_period_end=period_end,
            ).exclude(status=Invoice.Status.CANCELLED).first()

            if existing:
                logger.warning("Duplicate invoice attempt for sub %s period %s–%s (exists: %s)",
                               sub.pk, period_start, period_end, existing.invoice_number)
                return existing

            # Step 4 – Build line items from snapshotted SubscriptionLines
            lines = sub.lines.select_related("product", "variant").all()
            if not lines.exists():
                logger.error("Subscription %s has no lines – cannot generate invoice", sub.pk)
                return None

            # Count existing invoices for this subscription (for discount cycle check)
            invoice_sequence = Invoice.objects.filter(subscription=sub).count() + 1

            subtotal = Decimal("0.00")
            total_qty = 0
            line_data = []
            for line in lines:
                line_sub = _q(line.unit_price * line.quantity)
                subtotal += line_sub
                total_qty += line.quantity
                line_data.append({
                    "product": line.product,
                    "variant": line.variant,
                    "description": f"{line.product.name}" + (f" – {line.variant.attribute_value}" if line.variant else ""),
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "tax_rate": line.tax_rate,
                    "line_subtotal": line_sub,
                })

            # Step 5 – Evaluate discount eligibility
            discount_amount = Decimal("0.00")
            applied_discount = sub.applied_discount
            if applied_discount:
                eligible, reason = applied_discount.is_eligible(
                    subtotal=subtotal,
                    total_quantity=total_qty,
                    customer=sub.customer,
                    subscription=sub,
                    invoice_sequence=invoice_sequence,
                )
                if eligible:
                    discount_amount = _q(applied_discount.calculate_discount_amount(subtotal))
                    # Atomically increment used_count
                    Discount.objects.filter(pk=applied_discount.pk).update(
                        used_count=models_f("used_count") + 1
                    )
                else:
                    logger.info("Discount %s not eligible for sub %s: %s",
                                applied_discount.code, sub.pk, reason)
                    applied_discount = None

            taxable_base = subtotal - discount_amount

            # Step 6 – Per-line tax calculation (distribute discount proportionally)
            total_tax = Decimal("0.00")
            final_lines = []
            for ld in line_data:
                # Proportional discount allocation
                if subtotal > 0:
                    line_discount = _q(discount_amount * ld["line_subtotal"] / subtotal)
                else:
                    line_discount = Decimal("0.00")
                line_taxable = _q(ld["line_subtotal"] - line_discount)
                line_tax = _q(line_taxable * ld["tax_rate"] / 100)
                line_total = _q(line_taxable + line_tax)
                total_tax += line_tax
                final_lines.append({**ld, "discount_amount": line_discount,
                                    "taxable_amount": line_taxable,
                                    "tax_amount": line_tax, "line_total": line_total})

            total_tax = _q(total_tax)
            total_amount = _q(taxable_base + total_tax)
            due_date = period_end + __import__("datetime").timedelta(days=settings.INVOICE_DUE_DAYS)

            # Step 7 – Insert Invoice (DB UNIQUE constraint is the final race guard)
            try:
                invoice = Invoice.objects.create(
                    invoice_number=Invoice.generate_number(),
                    subscription=sub,
                    customer=sub.customer,
                    discount=applied_discount,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    invoice_date=billing_date,
                    due_date=due_date,
                    subtotal=subtotal,
                    discount_amount=discount_amount,
                    taxable_amount=taxable_base,
                    tax_amount=total_tax,
                    total_amount=total_amount,
                    amount_paid=Decimal("0.00"),
                    balance_due=total_amount,
                    status=Invoice.Status.CONFIRMED,
                )
            except IntegrityError:
                logger.warning("DB unique constraint caught duplicate for sub %s period %s–%s",
                               sub.pk, period_start, period_end)
                return Invoice.objects.filter(
                    subscription=sub,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                ).exclude(status=Invoice.Status.CANCELLED).first()

            # Insert InvoiceLines
            InvoiceLine.objects.bulk_create([
                InvoiceLine(
                    invoice=invoice,
                    product=fl["product"],
                    variant=fl["variant"],
                    description=fl["description"],
                    quantity=fl["quantity"],
                    unit_price=fl["unit_price"],
                    discount_amount=fl["discount_amount"],
                    tax_rate=fl["tax_rate"],
                    taxable_amount=fl["taxable_amount"],
                    tax_amount=fl["tax_amount"],
                    line_total=fl["line_total"],
                )
                for fl in final_lines
            ])

            # Step 8 – Advance next_billing_date
            sub.next_billing_date = period_end + __import__("datetime").timedelta(days=1)
            sub.save(update_fields=["next_billing_date"])

            # Update monthly snapshot
            cls._update_monthly_snapshot(invoice)

        # Step 9 – Async tasks (outside transaction for performance)
        from .tasks import generate_invoice_pdf_task, send_invoice_email_task
        generate_invoice_pdf_task.delay(invoice.pk)

        logger.info("Generated invoice %s for subscription %s (₹%s)",
                    invoice.invoice_number, sub.subscription_number, total_amount)
        return invoice

    # ------------------------------------------------------------------
    # 2. Full & Partial Payment Reconciliation
    # ------------------------------------------------------------------
    @classmethod
    def record_payment(cls, invoice_id=None, amount=None, payment_method: str = "Cash",
                       payment_date=None, recorded_by=None, transaction_reference: str = "",
                       notes: str = "", invoice=None) -> "Payment":
        """
        Atomically record a payment against an invoice.

        Rules:
          - amount must be > 0 and <= balance_due.
          - Invoice is row-locked before any writes.
          - Transitions: Confirmed/Partially_Paid → Partially_Paid or Paid.
          - If invoice becomes Paid and subscription is Past_Due, restore to Active.
          - Updates MonthlyRevenueSnapshot and invalidates Redis dashboard cache.
        """
        from .models import Invoice, Payment, MonthlyRevenueSnapshot
        from subscriptions.models import Subscription
        from django.core.cache import cache
        from django.utils import timezone

        if invoice is not None and invoice_id is None:
            invoice_id = invoice.pk if hasattr(invoice, "pk") else invoice

        if payment_date is None:
            payment_date = timezone.now().date()

        if amount is None:
            raise ValueError("Payment amount must be provided")

        amount = _q(Decimal(str(amount)))

        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

            # Validation
            if invoice.status in (Invoice.Status.PAID, Invoice.Status.CANCELLED):
                raise ValueError(f"Cannot pay {invoice.status.lower()} invoice")
            if amount <= Decimal("0.00"):
                raise ValueError("Payment amount must be positive")
            if amount > invoice.balance_due:
                raise ValueError(
                    f"Payment ₹{amount} exceeds balance due ₹{invoice.balance_due}. "
                    "Record a credit note for overpayments."
                )

            # Create payment record
            payment = Payment.objects.create(
                payment_number=Payment.generate_number(),
                invoice=invoice,
                customer=invoice.customer,
                recorded_by=recorded_by,
                amount=amount,
                payment_method=payment_method,
                transaction_reference=transaction_reference,
                payment_date=payment_date,
                status=Payment.Status.SUCCESS,
                notes=notes,
            )

            # Update invoice
            invoice.amount_paid = _q(invoice.amount_paid + amount)
            invoice.balance_due = _q(invoice.total_amount - invoice.amount_paid)

            if invoice.balance_due == Decimal("0.00"):
                invoice.status = Invoice.Status.PAID
                # Restore Past_Due subscription
                sub = invoice.subscription
                if sub.status == Subscription.Status.PAST_DUE:
                    sub.status = Subscription.Status.ACTIVE
                    sub.save(update_fields=["status"])
            else:
                invoice.status = Invoice.Status.PARTIALLY_PAID

            invoice.save(update_fields=["amount_paid", "balance_due", "status", "updated_at"])

            # Update monthly snapshot collected amount
            year_month = payment.payment_date.strftime("%Y-%m")
            MonthlyRevenueSnapshot.objects.update_or_create(
                year_month=year_month,
                defaults={},
            )
            MonthlyRevenueSnapshot.objects.filter(year_month=year_month).update(
                collected_amount=models_f("collected_amount") + amount,
            )

        # Invalidate Redis dashboard cache
        cache.delete("admin_dashboard_kpis")

        # Send payment confirmation async
        from .tasks import send_payment_confirmation_task
        send_payment_confirmation_task.delay(payment.pk)

        return payment

    # ------------------------------------------------------------------
    # 3. Discount Eligibility Check (used by views)
    # ------------------------------------------------------------------
    @classmethod
    def validate_discount_code(cls, code: str, subtotal: Decimal, total_quantity: int,
                                customer, subscription=None, invoice_sequence: int = 1):
        """Returns (discount_obj, discount_amount, error_message)."""
        from .models import Discount
        try:
            discount = Discount.objects.get(code__iexact=code, is_active=True)
        except Discount.DoesNotExist:
            return None, Decimal("0.00"), "Invalid discount code"

        eligible, reason = discount.is_eligible(
            subtotal, total_quantity, customer, subscription, invoice_sequence
        )
        if not eligible:
            return None, Decimal("0.00"), reason

        amount = discount.calculate_discount_amount(subtotal)
        return discount, amount, None

    # ------------------------------------------------------------------
    # 4. Overdue detection (called by Celery Beat daily cron)
    # ------------------------------------------------------------------
    @classmethod
    def mark_overdue_invoices(cls):
        """Mark all unpaid past-due invoices as Overdue and trigger dunning."""
        from .models import Invoice
        from subscriptions.models import Subscription

        today = timezone.now().date()
        overdue_qs = Invoice.objects.filter(
            status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID],
            due_date__lt=today,
        ).select_related("subscription__plan", "customer__user")

        count = 0
        for invoice in overdue_qs:
            invoice.status = Invoice.Status.OVERDUE
            invoice.save(update_fields=["status", "updated_at"])

            sub = invoice.subscription
            days_overdue = (today - invoice.due_date).days
            grace = sub.plan.grace_period_days if sub.plan else 7

            if days_overdue >= grace and sub.status == Subscription.Status.ACTIVE:
                sub.status = Subscription.Status.PAST_DUE
                sub.save(update_fields=["status"])

            count += 1

        logger.info("Marked %s invoices as overdue", count)
        return count

    # ------------------------------------------------------------------
    # 5. Auto-Renewal
    # ------------------------------------------------------------------
    @classmethod
    def process_renewals(cls):
        """Auto-renew or close subscriptions reaching expiry_date."""
        from subscriptions.models import Subscription
        from dateutil.relativedelta import relativedelta

        today = timezone.now().date()
        expiring = Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            expiry_date__lte=today,
        ).select_related("plan", "customer")

        for sub in expiring:
            overdue_exists = sub.invoices.filter(
                status__in=["Confirmed", "Partially_Paid", "Overdue"]
            ).exists()

            if sub.auto_renew and not overdue_exists:
                sub.expiry_date = sub.expiry_date + relativedelta(
                    months=sub.plan.default_duration_months
                )
                sub.save(update_fields=["expiry_date"])
                cls.generate_invoice_for_subscription(sub, today)
                logger.info("Auto-renewed subscription %s", sub.subscription_number)
            else:
                sub.status = Subscription.Status.CLOSED
                sub.save(update_fields=["status"])
                logger.info("Closed subscription %s (auto_renew=%s, overdue=%s)",
                            sub.subscription_number, sub.auto_renew, overdue_exists)

    # ------------------------------------------------------------------
    # 6. Pro-rata mid-cycle upgrade
    # ------------------------------------------------------------------
    @classmethod
    def generate_proration_invoice(cls, subscription, new_cycle_price: Decimal,
                                   old_cycle_price: Decimal, billing_date=None):
        """
        Generate a prorated adjustment invoice for mid-cycle upgrades.
        Prorated charge = (new_price - old_price) × (D_remaining / D_total)
        """
        from .models import Invoice, InvoiceLine
        import datetime

        billing_date = billing_date or timezone.now().date()
        sub = subscription

        if sub.next_billing_date is None:
            return None

        period_end = sub.next_billing_date - datetime.timedelta(days=1)
        d_remaining = (sub.next_billing_date - billing_date).days
        d_total = (sub.plan.cycle_delta())
        if hasattr(d_total, "days"):
            d_total_days = d_total.days
        else:
            d_total_days = (billing_date + d_total - billing_date).days

        if d_total_days <= 0:
            return None

        prorated_charge = _q(
            (new_cycle_price - old_cycle_price) * Decimal(d_remaining) / Decimal(d_total_days)
        )

        if prorated_charge <= Decimal("0.00"):
            return None

        tax_rate = sub.plan.product.tax_rate
        tax_amount = _q(prorated_charge * tax_rate / 100)
        total = _q(prorated_charge + tax_amount)

        with transaction.atomic():
            invoice = Invoice.objects.create(
                invoice_number=Invoice.generate_number(),
                subscription=sub,
                customer=sub.customer,
                billing_period_start=billing_date,
                billing_period_end=period_end,
                invoice_date=billing_date,
                due_date=billing_date + __import__("datetime").timedelta(days=settings.INVOICE_DUE_DAYS),
                subtotal=prorated_charge,
                discount_amount=Decimal("0.00"),
                taxable_amount=prorated_charge,
                tax_amount=tax_amount,
                total_amount=total,
                amount_paid=Decimal("0.00"),
                balance_due=total,
                status=Invoice.Status.CONFIRMED,
                notes="Prorated mid-cycle upgrade adjustment",
            )
            InvoiceLine.objects.create(
                invoice=invoice,
                product=sub.plan.product,
                variant=sub.plan.variant,
                description=f"Prorated upgrade ({d_remaining}/{d_total_days} days)",
                quantity=1,
                unit_price=prorated_charge,
                discount_amount=Decimal("0.00"),
                tax_rate=tax_rate,
                taxable_amount=prorated_charge,
                tax_amount=tax_amount,
                line_total=total,
            )
            cls._update_monthly_snapshot(invoice)

        from .tasks import generate_invoice_pdf_task
        generate_invoice_pdf_task.delay(invoice.pk)
        return invoice

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _update_monthly_snapshot(invoice):
        """Increment billed_amount and tax_collected in MonthlyRevenueSnapshot."""
        from .models import MonthlyRevenueSnapshot
        year_month = invoice.invoice_date.strftime("%Y-%m")
        obj, _ = MonthlyRevenueSnapshot.objects.get_or_create(year_month=year_month)
        MonthlyRevenueSnapshot.objects.filter(year_month=year_month).update(
            billed_amount=models_f("billed_amount") + invoice.total_amount,
            tax_collected=models_f("tax_collected") + invoice.tax_amount,
            discounts_given=models_f("discounts_given") + invoice.discount_amount,
        )
        from django.core.cache import cache
        cache.delete("admin_dashboard_kpis")


# Helper for F() expressions without circular import
def models_f(field_name):
    from django.db.models import F
    return F(field_name)
