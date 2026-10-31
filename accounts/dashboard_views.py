"""
accounts/dashboard_views.py
Role-based dashboard views with Redis-cached KPI aggregation.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.core.cache import cache
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal


def dashboard_redirect(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    role = request.user.role
    if role == 'Admin':
        return redirect('dashboard:admin')
    elif role == 'Staff':
        return redirect('dashboard:staff')
    else:
        return redirect('dashboard:customer')


@login_required
def admin_dashboard(request):
    if request.user.role not in ('Admin', 'Staff'):
        return redirect('dashboard:customer')

    cache_key = 'dashboard_kpi'
    kpis = cache.get(cache_key)

    if kpis is None:
        from accounts.models import Customer
        from subscriptions.models import Subscription
        from billing.models import Invoice, MonthlyRevenueSnapshot
        from payments.models import Payment

        today = timezone.now().date()
        this_month = today.strftime('%Y-%m')
        last_month = (today.replace(day=1) - __import__('datetime').timedelta(days=1)).strftime('%Y-%m')

        total_customers = Customer.objects.filter(user__is_active=True).count()
        customers_last_month = Customer.objects.filter(
            created_at__month=(today.month - 1 if today.month > 1 else 12),
            created_at__year=(today.year if today.month > 1 else today.year - 1),
        ).count()
        customer_growth = 0
        if customers_last_month > 0:
            customer_growth = round(((total_customers - customers_last_month) / customers_last_month) * 100, 1)

        active_subs = Subscription.objects.filter(status='Active')
        active_count = active_subs.count()

        # MRR computation
        mrr = Decimal('0.00')
        for sub in active_subs.select_related('plan'):
            mrr += sub.mrr

        # Revenue metrics
        collected = Payment.objects.filter(status='Success').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        pending = Invoice.objects.filter(
            status__in=['Confirmed', 'Partially_Paid']
        ).aggregate(t=Sum('balance_due'))['t'] or Decimal('0.00')
        overdue_qs = Invoice.objects.filter(status='Overdue')
        overdue_count = overdue_qs.count()
        overdue_amount = overdue_qs.aggregate(t=Sum('balance_due'))['t'] or Decimal('0.00')

        # Subscription status breakdown for doughnut chart
        status_breakdown = dict(
            Subscription.objects.values('status').annotate(c=Count('id')).values_list('status', 'c')
        )

        # 12-month revenue trend from snapshots
        snapshots = list(
            MonthlyRevenueSnapshot.objects.order_by('-year_month')[:12]
        )
        snapshots.reverse()
        trend_labels = [s.year_month for s in snapshots]
        trend_billed = [float(s.billed_amount) for s in snapshots]
        trend_collected = [float(s.collected_amount) for s in snapshots]

        # Payment method distribution
        pay_methods = dict(
            Payment.objects.filter(status='Success')
            .values('payment_method')
            .annotate(total=Sum('amount'))
            .values_list('payment_method', 'total')
        )

        # Expiring quotations (within 3 days)
        expiring_quotations = Subscription.objects.filter(
            status='Quotation',
            quotation_validity_date__lte=today + __import__('datetime').timedelta(days=3),
            quotation_validity_date__gte=today,
        ).select_related('customer')[:5]

        # Today's invoices
        todays_invoices = Invoice.objects.filter(invoice_date=today).count()

        kpis = {
            'total_customers': total_customers,
            'customer_growth': customer_growth,
            'active_subscriptions': active_count,
            'mrr': float(mrr),
            'collected_revenue': float(collected),
            'pending_receivables': float(pending),
            'overdue_count': overdue_count,
            'overdue_amount': float(overdue_amount),
            'status_breakdown': status_breakdown,
            'trend_labels': trend_labels,
            'trend_billed': trend_billed,
            'trend_collected': trend_collected,
            'pay_methods': {k: float(v) for k, v in pay_methods.items()},
            'todays_invoices': todays_invoices,
        }
        cache.set(cache_key, kpis, timeout=300)
        expiring_quotations_list = list(expiring_quotations)
    else:
        from subscriptions.models import Subscription
        today = timezone.now().date()
        expiring_quotations_list = list(
            Subscription.objects.filter(
                status='Quotation',
                quotation_validity_date__lte=today + __import__('datetime').timedelta(days=3),
                quotation_validity_date__gte=today,
            ).select_related('customer')[:5]
        )

    return render(request, 'admin_dash/dashboard.html', {
        'kpis': kpis,
        'expiring_quotations': expiring_quotations_list,
        'page_title': 'Executive Dashboard',
    })


@login_required
def staff_dashboard(request):
    if request.user.role == 'Customer':
        return redirect('dashboard:customer')

    from subscriptions.models import Subscription
    from billing.models import Invoice
    today = timezone.now().date()

    context = {
        'expiring_quotations': Subscription.objects.filter(
            status='Quotation',
            quotation_validity_date__lte=today + __import__('datetime').timedelta(days=3),
        ).select_related('customer')[:10],
        'due_renewals': Subscription.objects.filter(
            status='Active',
            next_billing_date__lte=today + __import__('datetime').timedelta(days=3),
        ).select_related('customer', 'plan')[:10],
        'todays_invoices': Invoice.objects.filter(
            invoice_date=today
        ).select_related('customer')[:10],
        'overdue_invoices': Invoice.objects.filter(
            status='Overdue'
        ).select_related('customer').order_by('due_date')[:10],
        'page_title': 'Staff Operations Dashboard',
    }
    return render(request, 'staff/dashboard.html', context)


@login_required
def customer_dashboard(request):
    if request.user.role != 'Customer':
        return redirect('dashboard:admin')

    try:
        customer = request.user.customer_profile
    except Exception:
        return redirect('accounts:profile')

    from subscriptions.models import Subscription
    from billing.models import Invoice

    subscriptions = Subscription.objects.filter(
        customer=customer
    ).select_related('plan').order_by('-created_at')

    recent_invoices = Invoice.objects.filter(
        customer=customer
    ).order_by('-invoice_date')[:5]

    outstanding = customer.get_outstanding_balance()

    return render(request, 'customer/dashboard.html', {
        'customer': customer,
        'subscriptions': subscriptions,
        'recent_invoices': recent_invoices,
        'outstanding': outstanding,
        'page_title': 'My Subscription Portal',
    })
