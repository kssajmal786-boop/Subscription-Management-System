"""
billing/tasks.py
================
Celery async tasks + Celery Beat scheduled crons.

Scheduled tasks (registered via Django Celery Beat):
  - daily_billing_task       – 00:05 IST daily
  - daily_overdue_check_task – 01:00 IST daily
  - daily_dunning_task       – 01:30 IST daily
  - process_renewals_task    – 02:00 IST daily

Ad-hoc tasks (enqueued by BillingService):
  - generate_invoice_pdf_task
  - send_invoice_email_task
  - send_payment_confirmation_task
  - send_dunning_email_task
"""
import logging
from celery import shared_task
from django.utils import timezone
from django.core.mail import EmailMessage
from django.conf import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Ad-hoc: PDF Generation
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_invoice_pdf_task(self, invoice_pk: int):
    """Generate and save PDF for an invoice, then trigger email delivery."""
    try:
        from .models import Invoice
        from .pdf_service import save_invoice_pdf

        invoice = Invoice.objects.select_related(
            "customer__user", "subscription__plan", "discount"
        ).get(pk=invoice_pk)

        rel_path = save_invoice_pdf(invoice)
        invoice.pdf_file_path = rel_path
        invoice.save(update_fields=["pdf_file_path"])

        logger.info("PDF generated for invoice %s → %s", invoice.invoice_number, rel_path)

        # Chain email delivery
        send_invoice_email_task.delay(invoice_pk)
        return rel_path

    except Exception as exc:
        logger.error("PDF generation failed for invoice %s: %s", invoice_pk, exc)
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Ad-hoc: Invoice Email
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_invoice_email_task(self, invoice_pk: int):
    """Email the invoice PDF to the customer."""
    try:
        import os
        from .models import Invoice, Notification
        from .pdf_service import generate_invoice_pdf

        invoice = Invoice.objects.select_related("customer__user", "subscription__plan").get(pk=invoice_pk)
        customer_email = invoice.customer.user.email
        customer_name = invoice.customer.user.get_full_name()

        pdf_bytes = generate_invoice_pdf(invoice)

        subject = f"Invoice {invoice.invoice_number} from {settings.COMPANY_NAME}"
        body = (
            f"Dear {customer_name},\n\n"
            f"Please find attached your invoice {invoice.invoice_number} "
            f"for the billing period {invoice.billing_period_start} to {invoice.billing_period_end}.\n\n"
            f"Amount Due: ₹{invoice.total_amount:,.2f}\n"
            f"Due Date: {invoice.due_date.strftime('%d %b %Y')}\n\n"
            f"Thank you for your business.\n\n"
            f"— {settings.COMPANY_NAME} Billing Team"
        )

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[customer_email],
        )
        email.attach(
            f"{invoice.invoice_number}.pdf",
            pdf_bytes,
            "application/pdf",
        )
        email_sent = False
        try:
            email.send(fail_silently=True)
            email_sent = True
        except Exception as e:
            logger.warning("Email delivery skipped or failed for invoice %s: %s", invoice_pk, e)

        # Create in-app notification
        Notification.objects.create(
            user=invoice.customer.user,
            event_type=Notification.EventType.INVOICE_GENERATED,
            subject=subject,
            message=f"Your invoice {invoice.invoice_number} for ₹{invoice.total_amount:,.2f} has been generated.",
            email_sent_status=email_sent,
            related_invoice=invoice,
        )

        logger.info("Invoice notification recorded for %s (%s)", customer_email, invoice.invoice_number)

    except Exception as exc:
        logger.error("Invoice email processing error for %s: %s", invoice_pk, exc)



# ──────────────────────────────────────────────────────────────────────────────
# Ad-hoc: Payment Confirmation
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_confirmation_task(self, payment_pk: int):
    """Send payment confirmation email with receipt PDF."""
    try:
        from .models import Payment, Notification
        from .pdf_service import generate_payment_receipt_pdf

        payment = Payment.objects.select_related(
            "invoice__subscription", "customer__user"
        ).get(pk=payment_pk)

        receipt_bytes = generate_payment_receipt_pdf(payment)
        customer_email = payment.customer.user.email
        customer_name = payment.customer.user.get_full_name()

        subject = f"Payment Received – {payment.payment_number}"
        body = (
            f"Dear {customer_name},\n\n"
            f"We have received your payment of ₹{payment.amount:,.2f} against "
            f"invoice {payment.invoice.invoice_number}.\n\n"
            f"Payment Reference: {payment.payment_number}\n"
            f"Transaction ID: {payment.transaction_reference or 'N/A'}\n"
            f"Balance Remaining: ₹{payment.invoice.balance_due:,.2f}\n\n"
            f"Thank you!\n— {settings.COMPANY_NAME}"
        )

        email = EmailMessage(
            subject=subject, body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[customer_email],
        )
        email.attach(f"{payment.payment_number}_receipt.pdf", receipt_bytes, "application/pdf")
        email_sent = False
        try:
            email.send(fail_silently=True)
            email_sent = True
        except Exception as e:
            logger.warning("Payment email delivery skipped or failed for %s: %s", payment_pk, e)

        Notification.objects.create(
            user=payment.customer.user,
            event_type=Notification.EventType.PAYMENT_RECEIVED,
            subject=subject,
            message=f"Payment ₹{payment.amount:,.2f} confirmed for invoice {payment.invoice.invoice_number}.",
            email_sent_status=email_sent,
            related_invoice=payment.invoice,
        )

    except Exception as exc:
        logger.error("Payment confirmation error for %s: %s", payment_pk, exc)



# ──────────────────────────────────────────────────────────────────────────────
# Ad-hoc: Dunning Email
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(bind=True, max_retries=2)
def send_dunning_email_task(self, invoice_pk: int, days_overdue: int):
    """Send overdue dunning reminder to customer."""
    try:
        from .models import Invoice, Notification

        invoice = Invoice.objects.select_related("customer__user").get(pk=invoice_pk)
        customer_email = invoice.customer.user.email
        customer_name = invoice.customer.user.get_full_name()

        if days_overdue == 0:
            subject = f"Payment Due Today – Invoice {invoice.invoice_number}"
            urgency = "is due today"
        elif days_overdue <= 3:
            subject = f"Payment Overdue – Invoice {invoice.invoice_number}"
            urgency = f"is {days_overdue} day(s) overdue"
        else:
            subject = f"FINAL NOTICE – Invoice {invoice.invoice_number}"
            urgency = f"is {days_overdue} days overdue"

        body = (
            f"Dear {customer_name},\n\n"
            f"This is a reminder that invoice {invoice.invoice_number} "
            f"for ₹{invoice.balance_due:,.2f} {urgency}.\n\n"
            f"Please make payment at your earliest convenience to avoid service interruption.\n\n"
            f"— {settings.COMPANY_NAME} Billing Team"
        )

        from django.core.mail import send_mail
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [customer_email], fail_silently=True)

        Notification.objects.create(
            user=invoice.customer.user,
            event_type=Notification.EventType.INVOICE_OVERDUE,
            subject=subject,
            message=f"Invoice {invoice.invoice_number} ₹{invoice.balance_due:,.2f} {urgency}.",
            email_sent_status=True,
            related_invoice=invoice,
        )

    except Exception as exc:
        logger.error("Dunning email failed for invoice %s: %s", invoice_pk, exc)


# ──────────────────────────────────────────────────────────────────────────────
# Scheduled Crons (triggered by Celery Beat)
# ──────────────────────────────────────────────────────────────────────────────
@shared_task(name="billing.tasks.daily_billing")
def daily_billing_task():
    """
    Daily at 00:05 – Generate invoices for all Active subscriptions due today.
    """
    from .services import BillingService
    from subscriptions.models import Subscription

    today = timezone.now().date()
    logger.info("Daily billing cron started for %s", today)

    due_subs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        next_billing_date__lte=today,
    ).select_related("customer", "plan", "applied_discount")

    generated = 0
    skipped = 0
    for sub in due_subs:
        result = BillingService.generate_invoice_for_subscription(sub, billing_date=today)
        if result:
            generated += 1
        else:
            skipped += 1

    logger.info("Daily billing complete: %s generated, %s skipped", generated, skipped)
    return {"generated": generated, "skipped": skipped, "date": str(today)}


@shared_task(name="billing.tasks.daily_overdue_check")
def daily_overdue_check_task():
    """Daily at 01:00 – Mark overdue invoices and update subscription statuses."""
    from .services import BillingService
    count = BillingService.mark_overdue_invoices()
    logger.info("Overdue check: %s invoices marked", count)
    return count


@shared_task(name="billing.tasks.daily_dunning")
def daily_dunning_task():
    """Daily at 01:30 – Send dunning reminders at T+0, T+3, T+7, plus upcoming due reminders & renewals."""
    from .models import Invoice, Notification
    from subscriptions.models import Subscription
    from django.core.mail import send_mail

    today = timezone.now().date()
    sent = 0

    # 1. Overdue dunning reminders (T+0, T+3, T+7)
    overdue_invoices = Invoice.objects.filter(
        status=Invoice.Status.OVERDUE,
    ).select_related("customer__user")

    for invoice in overdue_invoices:
        days_overdue = (today - invoice.due_date).days
        if days_overdue in (0, 3, 7):
            send_dunning_email_task.delay(invoice.pk, days_overdue)
            sent += 1
        elif days_overdue >= 10:
            # Transition subscription to Past_Due (grace period exceeded)
            sub = invoice.subscription
            if sub and sub.status == "Active":
                Subscription.objects.filter(pk=sub.pk).update(status=Subscription.Status.PAST_DUE)

    # 2. Upcoming payment reminders (T-3, T-1 before due date)
    from datetime import timedelta
    upcoming_invoices = Invoice.objects.filter(
        status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID],
        due_date__in=[today + timedelta(days=1), today + timedelta(days=3)],
    ).select_related("customer__user")

    for inv in upcoming_invoices:
        days_left = (inv.due_date - today).days
        subject = f"Upcoming Payment Reminder: Invoice {inv.invoice_number}"
        body = (
            f"Dear {inv.customer.user.get_full_name()},\n\n"
            f"This is a friendly reminder that invoice {inv.invoice_number} "
            f"for ₹{inv.balance_due:,.2f} is due on {inv.due_date.strftime('%d %b %Y')} ({days_left} day(s) away).\n\n"
            f"Please visit your portal to complete payment: /billing/portal/\n\n"
            f"— {settings.COMPANY_NAME} Billing"
        )
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [inv.customer.user.email], fail_silently=True)
        Notification.objects.create(
            user=inv.customer.user,
            event_type=Notification.EventType.INVOICE_GENERATED,
            subject=subject,
            message=f"Reminder: Invoice {inv.invoice_number} for ₹{inv.balance_due:,.2f} is due in {days_left} day(s).",
            email_sent_status=True,
            related_invoice=inv,
        )
        sent += 1

    # 3. Subscription renewal notifications (T-7, T-3 before expiry)
    expiring_subs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        expiry_date__in=[today + timedelta(days=3), today + timedelta(days=7)],
    ).select_related("customer__user", "plan")

    for sub in expiring_subs:
        days_left = (sub.expiry_date - today).days
        sub_subject = f"Subscription Renewal Reminder: {sub.plan.plan_name}"
        sub_body = (
            f"Dear {sub.customer.user.get_full_name()},\n\n"
            f"Your subscription {sub.subscription_number} for plan '{sub.plan.plan_name}' "
            f"will expire on {sub.expiry_date.strftime('%d %b %Y')} ({days_left} days left).\n\n"
            f"{'Auto-renewal is enabled for this subscription.' if sub.auto_renew else 'Please log in to your portal to renew your subscription.'}\n\n"
            f"— {settings.COMPANY_NAME}"
        )
        send_mail(sub_subject, sub_body, settings.DEFAULT_FROM_EMAIL, [sub.customer.user.email], fail_silently=True)
        Notification.objects.create(
            user=sub.customer.user,
            event_type=Notification.EventType.RENEWAL_REMINDER,
            subject=sub_subject,
            message=f"Subscription {sub.subscription_number} expires in {days_left} days.",
            email_sent_status=True,
        )
        sent += 1

    logger.info("Daily dunning & notification task completed: %s actions taken", sent)
    return sent



@shared_task(name="billing.tasks.process_renewals")
def process_renewals_task():
    """Daily at 02:00 – Auto-renew or close expiring subscriptions."""
    from .services import BillingService
    BillingService.process_renewals()
    logger.info("Renewals processing complete for %s", timezone.now().date())


@shared_task(name="billing.tasks.rebuild_monthly_snapshots")
def rebuild_monthly_snapshots_task():
    """Weekly – Rebuild MonthlyRevenueSnapshot from Invoice and Payment tables."""
    from .models import Invoice, Payment, MonthlyRevenueSnapshot
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth
    import datetime

    # Billed amounts from invoices
    inv_data = (
        Invoice.objects
        .exclude(status=Invoice.Status.CANCELLED)
        .annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(
            billed=Sum("total_amount"),
            tax=Sum("tax_amount"),
            discount=Sum("discount_amount"),
        )
    )

    # Collected from payments
    pay_data = (
        Payment.objects
        .filter(status=Payment.Status.SUCCESS)
        .annotate(month=TruncMonth("payment_date"))
        .values("month")
        .annotate(collected=Sum("amount"))
    )

    pay_map = {p["month"].strftime("%Y-%m"): p["collected"] for p in pay_data if p["month"]}

    for inv in inv_data:
        if not inv["month"]:
            continue
        year_month = inv["month"].strftime("%Y-%m")
        MonthlyRevenueSnapshot.objects.update_or_create(
            year_month=year_month,
            defaults={
                "billed_amount": inv["billed"] or Decimal("0.00"),
                "tax_collected": inv["tax"] or Decimal("0.00"),
                "discounts_given": inv["discount"] or Decimal("0.00"),
                "collected_amount": pay_map.get(year_month, Decimal("0.00")),
            },
        )

    from django.core.cache import cache
    cache.delete("admin_dashboard_kpis")
    logger.info("Monthly revenue snapshots rebuilt")


from decimal import Decimal
