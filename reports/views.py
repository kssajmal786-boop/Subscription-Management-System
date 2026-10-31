"""reports/views.py – Financial Reports & Exports"""
import csv
import json
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from accounts.decorators import admin_required
from billing.models import Invoice, MonthlyRevenueSnapshot
from payments.models import Payment
from subscriptions.models import Subscription


@login_required
@admin_required
def reports_dashboard(request):
    return render(request, 'admin_dash/reports.html', {'page_title': 'Financial Reports'})


@login_required
@admin_required
def revenue_data(request):
    """API endpoint: 12-month revenue chart data."""
    snapshots = MonthlyRevenueSnapshot.objects.order_by('-year_month')[:12]
    snapshots = list(reversed(snapshots))
    return JsonResponse({
        'labels': [s.year_month for s in snapshots],
        'billed': [float(s.billed_amount) for s in snapshots],
        'collected': [float(s.collected_amount) for s in snapshots],
    })


@login_required
@admin_required
def aging_report(request):
    """Aging receivables report grouped by overdue bucket."""
    today = timezone.now().date()
    overdue = Invoice.objects.filter(
        status__in=['Confirmed', 'Partially_Paid', 'Overdue']
    ).select_related('customer', 'subscription')

    buckets = {'Current': [], '1–15 days': [], '16–30 days': [], '31–60 days': [], '60+ days': []}
    for inv in overdue:
        bucket = inv.aging_bucket
        buckets[bucket].append(inv)

    bucket_totals = {k: sum(i.balance_due for i in v) for k, v in buckets.items()}

    return render(request, 'admin_dash/aging_report.html', {
        'buckets': buckets,
        'bucket_totals': bucket_totals,
        'page_title': 'Aging Receivables Report',
    })


@login_required
@admin_required
def product_revenue_report(request):
    """Revenue by product/variant."""
    from billing.models import InvoiceLine
    from django.db.models import Sum
    data = (
        InvoiceLine.objects
        .select_related('product', 'variant')
        .values('product__name', 'variant__attribute_value')
        .annotate(
            revenue=Sum('line_total'),
            tax=Sum('tax_amount'),
            count=Count('id')
        )
        .order_by('-revenue')
    )
    return render(request, 'admin_dash/product_revenue.html', {
        'data': data, 'page_title': 'Product Revenue Report'
    })


@login_required
@admin_required
def export_invoices_csv(request):
    """Export invoices to CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Invoice #', 'Customer', 'Subscription', 'Period Start', 'Period End',
        'Invoice Date', 'Due Date', 'Subtotal', 'Tax', 'Discount', 'Total',
        'Amount Paid', 'Balance Due', 'Status'
    ])
    for inv in Invoice.objects.select_related('customer__user', 'subscription').order_by('-invoice_date'):
        writer.writerow([
            inv.invoice_number, inv.customer.display_name, inv.subscription.subscription_number,
            inv.billing_period_start, inv.billing_period_end, inv.invoice_date, inv.due_date,
            inv.subtotal, inv.tax_amount, inv.discount_amount, inv.total_amount,
            inv.amount_paid, inv.balance_due, inv.status
        ])
    return response


@login_required
@admin_required
def export_payments_csv(request):
    """Export payments to CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="payments_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['Payment #', 'Invoice #', 'Customer', 'Amount', 'Method', 'Transaction Ref', 'Date', 'Status'])
    for p in Payment.objects.select_related('invoice', 'customer__user').order_by('-payment_date'):
        writer.writerow([
            p.payment_number, p.invoice.invoice_number, p.customer.display_name,
            p.amount, p.payment_method, p.transaction_reference, p.payment_date, p.status
        ])
    return response
