"""
billing/views.py
================
All billing UI views:
  - Invoice Center (list, detail, PDF download, email)
  - Discount Configuration (CRUD)
  - Payment Ledger (record, history, outstanding)
  - Customer Portal (self-service)
  - Financial Reports
"""
import os
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator
from django.core.cache import cache

from .models import Invoice, Payment, Discount, Notification
from .services import BillingService
from .forms import (
    DiscountForm, PaymentForm, InvoiceFilterForm,
    PaymentFilterForm, DiscountCodeCheckForm
)
from accounts.decorators import admin_required, staff_or_admin_required, customer_required
from accounts.models import Customer


# ─────────────────────────────────────────────────────────────────────────────
# Invoice Center
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@staff_or_admin_required
def invoice_list(request):
    """Invoice center with filtering by status, date, customer."""
    form = InvoiceFilterForm(request.GET)
    qs = Invoice.objects.select_related("customer__user", "subscription__plan", "discount")

    if form.is_valid():
        if form.cleaned_data.get("status"):
            qs = qs.filter(status=form.cleaned_data["status"])
        if form.cleaned_data.get("customer"):
            qs = qs.filter(customer=form.cleaned_data["customer"])
        if form.cleaned_data.get("date_from"):
            qs = qs.filter(invoice_date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data.get("date_to"):
            qs = qs.filter(invoice_date__lte=form.cleaned_data["date_to"])
        if form.cleaned_data.get("search"):
            qs = qs.filter(invoice_number__icontains=form.cleaned_data["search"])

    qs = qs.order_by("-invoice_date")
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page", 1))

    # Summary stats
    totals = qs.aggregate(
        total_billed=Sum("total_amount"),
        total_paid=Sum("amount_paid"),
        total_due=Sum("balance_due"),
    )

    return render(request, "billing/invoice_list.html", {
        "page": page,
        "form": form,
        "totals": totals,
        "status_choices": Invoice.Status.choices,
    })


@login_required
@staff_or_admin_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "customer__user", "subscription__plan", "discount"
        ).prefetch_related("lines__product", "lines__variant", "payments__recorded_by"),
        pk=pk,
    )
    payments = invoice.payments.filter(status=Payment.Status.SUCCESS)
    return render(request, "billing/invoice_detail.html", {
        "invoice": invoice,
        "payments": payments,
    })


@login_required
def invoice_pdf_download(request, pk):
    """Download or preview PDF invoice."""
    if request.user.role == "Customer":
        invoice = get_object_or_404(Invoice, pk=pk, customer__user=request.user)
    else:
        invoice = get_object_or_404(Invoice, pk=pk)

    from .pdf_service import generate_invoice_pdf
    pdf_bytes = generate_invoice_pdf(invoice)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "inline" if request.GET.get("preview") else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{invoice.invoice_number}.pdf"'
    return response


@login_required
@staff_or_admin_required
def invoice_send_email(request, pk):
    """Manually trigger invoice email."""
    invoice = get_object_or_404(Invoice, pk=pk)
    from .tasks import send_invoice_email_task
    send_invoice_email_task.delay(invoice.pk)
    messages.success(request, f"Invoice email queued for {invoice.customer}.")
    return redirect("billing:invoice_detail", pk=pk)


@login_required
@staff_or_admin_required
def invoice_void(request, pk):
    """Void/cancel a Draft invoice."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.status != Invoice.Status.DRAFT:
        messages.error(request, "Only Draft invoices can be voided.")
        return redirect("billing:invoice_detail", pk=pk)
    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=["status"])
    messages.success(request, f"Invoice {invoice.invoice_number} voided.")
    return redirect("billing:invoice_list")


@login_required
@staff_or_admin_required
def generate_invoice_manual(request, subscription_pk):
    """Manually generate an invoice for a subscription."""
    from subscriptions.models import Subscription
    sub = get_object_or_404(Subscription, pk=subscription_pk)
    invoice = BillingService.generate_invoice_for_subscription(sub, timezone.now().date())
    if invoice:
        messages.success(request, f"Invoice {invoice.invoice_number} generated.")
        return redirect("billing:invoice_detail", pk=invoice.pk)
    messages.error(request, "Could not generate invoice (check subscription status or billing date).")
    return redirect("subscriptions:subscription_detail", pk=subscription_pk)


# ─────────────────────────────────────────────────────────────────────────────
# Discount Management (Admin only)
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@admin_required
def discount_list(request):
    discounts = Discount.objects.order_by("-created_at")
    return render(request, "billing/discount_list.html", {"discounts": discounts})


@login_required
@admin_required
def discount_create(request):
    form = DiscountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Discount rule created.")
        return redirect("billing:discount_list")
    return render(request, "billing/discount_form.html", {"form": form, "title": "New Discount"})


@login_required
@admin_required
def discount_edit(request, pk):
    discount = get_object_or_404(Discount, pk=pk)
    form = DiscountForm(request.POST or None, instance=discount)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Discount updated.")
        return redirect("billing:discount_list")
    return render(request, "billing/discount_form.html", {"form": form, "title": "Edit Discount", "discount": discount})


@login_required
@admin_required
def discount_toggle(request, pk):
    discount = get_object_or_404(Discount, pk=pk)
    discount.is_active = not discount.is_active
    discount.save(update_fields=["is_active"])
    messages.success(request, "Discount status updated.")
    return redirect("billing:discount_list")


# ─────────────────────────────────────────────────────────────────────────────
# Payment Ledger & Recording
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@staff_or_admin_required
def payment_list(request):
    """Payment ledger with filters."""
    form = PaymentFilterForm(request.GET)
    qs = Payment.objects.select_related("invoice", "customer__user", "recorded_by")

    if form.is_valid():
        if form.cleaned_data.get("status"):
            qs = qs.filter(status=form.cleaned_data["status"])
        if form.cleaned_data.get("method"):
            qs = qs.filter(payment_method=form.cleaned_data["method"])
        if form.cleaned_data.get("date_from"):
            qs = qs.filter(payment_date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data.get("date_to"):
            qs = qs.filter(payment_date__lte=form.cleaned_data["date_to"])

    qs = qs.order_by("-payment_date")
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page", 1))
    return render(request, "billing/payment_list.html", {"page": page, "form": form})


@login_required
@staff_or_admin_required
def record_payment(request, invoice_pk):
    """Record a full or partial payment against an invoice."""
    invoice = get_object_or_404(Invoice.objects.select_related("customer__user"), pk=invoice_pk)

    if invoice.status in (Invoice.Status.PAID, Invoice.Status.CANCELLED):
        messages.warning(request, f"Invoice is already {invoice.status}.")
        return redirect("billing:invoice_detail", pk=invoice_pk)

    form = PaymentForm(request.POST or None, initial={
        "amount": invoice.balance_due,
        "payment_date": timezone.now().date(),
    })

    if request.method == "POST" and form.is_valid():
        try:
            payment = BillingService.record_payment(
                invoice_id=invoice.pk,
                amount=form.cleaned_data["amount"],
                payment_method=form.cleaned_data["payment_method"],
                payment_date=form.cleaned_data["payment_date"],
                recorded_by=request.user,
                transaction_reference=form.cleaned_data.get("transaction_reference", ""),
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(request, f"Payment {payment.payment_number} recorded (₹{payment.amount:,.2f}).")
            return redirect("billing:invoice_detail", pk=invoice_pk)
        except ValueError as e:
            messages.error(request, str(e))

    return render(request, "billing/record_payment.html", {"form": form, "invoice": invoice})


@login_required
def payment_receipt_download(request, pk):
    """Download payment receipt PDF."""
    if request.user.role == "Customer":
        payment = get_object_or_404(Payment, pk=pk, customer__user=request.user)
    else:
        payment = get_object_or_404(Payment, pk=pk)
    from .pdf_service import generate_payment_receipt_pdf
    pdf_bytes = generate_payment_receipt_pdf(payment)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{payment.payment_number}_receipt.pdf"'
    return response


@login_required
@staff_or_admin_required
def outstanding_invoices(request):
    """View of all outstanding (unpaid/partially paid) invoices."""
    qs = Invoice.objects.filter(
        status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE]
    ).select_related("customer__user", "subscription").order_by("due_date")
    return render(request, "billing/outstanding_invoices.html", {"invoices": qs})


@login_required
@staff_or_admin_required
def overdue_invoices(request):
    """View of overdue invoices with aging buckets."""
    today = timezone.now().date()
    qs = Invoice.objects.filter(
        status=Invoice.Status.OVERDUE
    ).select_related("customer__user", "subscription").order_by("due_date")

    # Annotate aging bucket
    invoices_with_aging = []
    for inv in qs:
        days = (today - inv.due_date).days
        if days <= 15:
            bucket = "0–15 days"
        elif days <= 30:
            bucket = "16–30 days"
        elif days <= 60:
            bucket = "31–60 days"
        else:
            bucket = "60+ days"
        invoices_with_aging.append({"invoice": inv, "days_overdue": days, "bucket": bucket})

    return render(request, "billing/overdue_invoices.html", {
        "invoices_with_aging": invoices_with_aging,
        "total_overdue": qs.aggregate(total=Sum("balance_due"))["total"] or Decimal("0.00"),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Customer Self-Service Portal
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@customer_required
def customer_portal(request):
    """Customer dashboard: subscriptions, invoices, balance."""
    customer = get_object_or_404(Customer, user=request.user)
    subscriptions = customer.subscriptions.select_related("plan").order_by("-created_at")
    invoices = Invoice.objects.filter(customer=customer).order_by("-invoice_date")[:10]
    outstanding = Invoice.objects.filter(
        customer=customer,
        status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE]
    ).aggregate(total=Sum("balance_due"))["total"] or Decimal("0.00")
    unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()

    return render(request, "billing/customer_portal.html", {
        "customer": customer,
        "subscriptions": subscriptions,
        "invoices": invoices,
        "outstanding": outstanding,
        "unread_notifications": unread_notifications,
    })


@login_required
@customer_required
def customer_invoices(request):
    """Customer's full invoice history."""
    customer = get_object_or_404(Customer, user=request.user)
    qs = Invoice.objects.filter(customer=customer).order_by("-invoice_date")
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page", 1))
    return render(request, "billing/customer_invoices.html", {"page": page, "customer": customer})


@login_required
@customer_required
def customer_make_payment(request, invoice_pk):
    """Customer-initiated payment."""
    customer = get_object_or_404(Customer, user=request.user)
    invoice = get_object_or_404(Invoice, pk=invoice_pk, customer=customer)

    if invoice.status in (Invoice.Status.PAID, Invoice.Status.CANCELLED):
        messages.info(request, f"Invoice is already {invoice.status}.")
        return redirect("billing:customer_portal")

    form = PaymentForm(request.POST or None, initial={
        "amount": invoice.balance_due,
        "payment_date": timezone.now().date(),
    })
    # Limit methods for self-service
    form.fields["payment_method"].choices = [
        ("UPI", "UPI"),
        ("Card", "Card"),
        ("Bank_Transfer", "Bank Transfer / NEFT"),
    ]

    if request.method == "POST" and form.is_valid():
        try:
            payment = BillingService.record_payment(
                invoice_id=invoice.pk,
                amount=form.cleaned_data["amount"],
                payment_method=form.cleaned_data["payment_method"],
                payment_date=form.cleaned_data["payment_date"],
                recorded_by=request.user,
                transaction_reference=form.cleaned_data.get("transaction_reference", ""),
                notes="Customer self-service payment",
            )
            messages.success(request, f"Payment of ₹{payment.amount:,.2f} recorded. Reference: {payment.payment_number}")
            return redirect("billing:customer_portal")
        except ValueError as e:
            messages.error(request, str(e))

    return render(request, "billing/customer_make_payment.html", {"form": form, "invoice": invoice})


@login_required
@customer_required
def customer_notifications(request):
    """Mark all notifications as read and show them."""
    notifs = Notification.objects.filter(user=request.user).order_by("-created_at")
    notifs.filter(is_read=False).update(is_read=True)
    paginator = Paginator(notifs, 20)
    page = paginator.get_page(request.GET.get("page", 1))
    return render(request, "billing/notifications.html", {"page": page})


# ─────────────────────────────────────────────────────────────────────────────
# Financial Reports (Admin)
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@admin_required
def financial_reports(request):
    """Interactive financial reports with Chart.js and CSV/PDF export."""
    from .models import MonthlyRevenueSnapshot
    from catalog.models import Product
    from subscriptions.models import Subscription

    # Revenue by product
    from billing.models import InvoiceLine
    from django.db.models import Sum
    product_revenue = (
        InvoiceLine.objects
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .values("product__name")
        .annotate(total=Sum("line_total"))
        .order_by("-total")[:10]
    )

    # Subscription status distribution
    status_dist = (
        Subscription.objects
        .values("status")
        .annotate(count=Count("id"))
    )

    # Payment method distribution
    method_dist = (
        Payment.objects
        .filter(status=Payment.Status.SUCCESS)
        .values("payment_method")
        .annotate(total=Sum("amount"))
    )

    # Monthly snapshots for chart
    snapshots = list(MonthlyRevenueSnapshot.objects.order_by("-year_month")[:12])
    snapshots.reverse()

    return render(request, "billing/reports.html", {
        "product_revenue": list(product_revenue),
        "status_dist": list(status_dist),
        "method_dist": list(method_dist),
        "monthly_labels": [s.year_month for s in snapshots],
        "monthly_billed": [float(s.billed_amount) for s in snapshots],
        "monthly_collected": [float(s.collected_amount) for s in snapshots],
    })


@login_required
@admin_required
def export_invoices_csv(request):
    """Export all invoices to CSV."""
    import csv
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="invoices_export.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Invoice #", "Customer", "Subscription", "Period Start", "Period End",
        "Invoice Date", "Due Date", "Subtotal", "Tax", "Discount", "Total",
        "Amount Paid", "Balance Due", "Status"
    ])
    for inv in Invoice.objects.select_related("customer__user", "subscription").order_by("-invoice_date"):
        writer.writerow([
            inv.invoice_number,
            inv.customer.display_name,
            inv.subscription.subscription_number if inv.subscription else "-",
            inv.billing_period_start,
            inv.billing_period_end,
            inv.invoice_date,
            inv.due_date,
            inv.subtotal,
            inv.tax_amount,
            inv.discount_amount,
            inv.total_amount,
            inv.amount_paid,
            inv.balance_due,
            inv.status,
        ])
    return response


@login_required
@admin_required
def export_payments_csv(request):
    """Export all payment transactions to CSV."""
    import csv
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="payments_export.csv"'
    writer = csv.writer(response)
    writer.writerow(["Payment #", "Invoice #", "Customer", "Amount", "Method", "Transaction Ref", "Date", "Status"])
    for p in Payment.objects.select_related("invoice", "customer__user").order_by("-payment_date"):
        writer.writerow([
            p.payment_number,
            p.invoice.invoice_number if p.invoice else "-",
            p.customer.display_name,
            p.amount,
            p.payment_method,
            p.transaction_reference,
            p.payment_date,
            p.status,
        ])
    return response


@login_required
@admin_required
def export_revenue_csv(request):
    """Export monthly revenue snapshots to CSV."""
    import csv
    from .models import MonthlyRevenueSnapshot
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="revenue_snapshots.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Month (YYYY-MM)", "Billed Amount", "Collected Amount", "Tax Collected",
        "Discounts Given", "Active Subscriptions", "Overdue Amount", "New Customers"
    ])
    for s in MonthlyRevenueSnapshot.objects.all().order_by("-year_month"):
        writer.writerow([
            s.year_month,
            s.billed_amount,
            s.collected_amount,
            s.tax_collected,
            s.discounts_given,
            s.active_subscriptions_count,
            s.overdue_amount,
            getattr(s, "new_customers_count", 0),
        ])
    return response


@login_required
@admin_required
def financial_report_pdf(request):
    """Download executive financial report as ReportLab PDF."""
    from .models import MonthlyRevenueSnapshot, Invoice, Payment
    from subscriptions.models import Subscription
    from accounts.models import Customer
    from .pdf_service import generate_financial_report_pdf
    from django.db.models import Sum

    billed = Invoice.objects.exclude(status=Invoice.Status.CANCELLED).aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00")
    collected = Payment.objects.filter(status=Payment.Status.SUCCESS).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    pending = Invoice.objects.filter(status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID]).aggregate(t=Sum("balance_due"))["t"] or Decimal("0.00")
    overdue = Invoice.objects.filter(status=Invoice.Status.OVERDUE).aggregate(t=Sum("balance_due"))["t"] or Decimal("0.00")
    active_subs = Subscription.objects.filter(status="Active").count()
    customers = Customer.objects.filter(user__is_active=True).count()

    summary_data = {
        "billed": float(billed),
        "collected": float(collected),
        "pending": float(pending),
        "overdue": float(overdue),
        "active_subs": active_subs,
        "customers": customers,
    }
    snapshots = list(MonthlyRevenueSnapshot.objects.order_by("-year_month")[:12])

    pdf_bytes = generate_financial_report_pdf(summary_data, snapshots)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Financial_Report.pdf"'
    return response

