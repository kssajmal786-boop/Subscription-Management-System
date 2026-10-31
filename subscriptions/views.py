"""
subscriptions/views.py – Quotation builder, subscription lifecycle manager, plan management.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from .models import Plan, Subscription, SubscriptionLine
from .forms import PlanForm, SubscriptionForm, SubscriptionLineFormSet
from accounts.decorators import admin_required, staff_or_admin_required
from accounts.models import Customer


@login_required
@admin_required
def plan_list(request):
    plans = Plan.objects.select_related("product", "variant").order_by("plan_name")
    return render(request, "subscriptions/plan_list.html", {"plans": plans})


@login_required
@admin_required
def plan_create(request):
    form = PlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Plan created.")
        return redirect("subscriptions:plan_list")
    return render(request, "subscriptions/plan_form.html", {"form": form, "title": "New Plan"})


@login_required
@admin_required
def plan_edit(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Plan updated.")
        return redirect("subscriptions:plan_list")
    return render(request, "subscriptions/plan_form.html", {"form": form, "title": "Edit Plan", "plan": plan})


@login_required
@staff_or_admin_required
def subscription_list(request):
    status_filter = request.GET.get("status", "")
    qs = Subscription.objects.select_related("customer", "plan").order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    return render(request, "subscriptions/subscription_list.html", {
        "subscriptions": qs,
        "status_filter": status_filter,
        "status_choices": Subscription.Status.choices,
    })


@login_required
@staff_or_admin_required
def subscription_create(request):
    """Quotation/Subscription builder."""
    form = SubscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            sub = form.save(commit=False)
            sub.subscription_number = Subscription.generate_number()
            sub.status = Subscription.Status.QUOTATION
            sub.created_by = request.user
            sub.save()
            # Create one default line from plan
            plan = sub.plan
            unit_price = plan.variant.effective_price if plan.variant else plan.base_price
            tax_rate = plan.variant.tax_rate if plan.variant else plan.product.tax_rate
            SubscriptionLine.objects.create(
                subscription=sub,
                product=plan.product,
                variant=plan.variant,
                quantity=plan.min_quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
            )
        messages.success(request, f"Quotation {sub.subscription_number} created.")
        return redirect("subscriptions:subscription_detail", pk=sub.pk)
    return render(request, "subscriptions/subscription_form.html", {"form": form, "title": "New Quotation"})


@login_required
@staff_or_admin_required
def subscription_detail(request, pk):
    sub = get_object_or_404(Subscription.objects.select_related("customer", "plan", "applied_discount"), pk=pk)
    lines = sub.lines.select_related("product", "variant").all()
    invoices = sub.invoices.order_by("-invoice_date") if hasattr(sub, "invoices") else []
    return render(request, "subscriptions/subscription_detail.html", {
        "sub": sub,
        "lines": lines,
        "invoices": invoices,
    })


@login_required
@staff_or_admin_required
def subscription_confirm(request, pk):
    """Confirm a Quotation → Active."""
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.status not in (Subscription.Status.QUOTATION, Subscription.Status.CONFIRMED):
        messages.error(request, "Only Quotations can be confirmed.")
        return redirect("subscriptions:subscription_detail", pk=pk)
    with transaction.atomic():
        today = timezone.now().date()
        sub.start_date = today
        sub.next_billing_date = today
        sub.expiry_date = today + __import__("dateutil.relativedelta", fromlist=["relativedelta"]).relativedelta(
            months=sub.plan.default_duration_months)
        sub.status = Subscription.Status.ACTIVE
        sub.save()
        # Generate first invoice immediately
        from billing.services import BillingService
        BillingService.generate_invoice_for_subscription(sub)
    messages.success(request, f"Subscription {sub.subscription_number} is now Active.")
    return redirect("subscriptions:subscription_detail", pk=pk)


@login_required
@staff_or_admin_required
def subscription_pause(request, pk):
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.pause():
        messages.success(request, "Subscription paused.")
    else:
        messages.error(request, "Subscription cannot be paused.")
    return redirect("subscriptions:subscription_detail", pk=pk)


@login_required
@staff_or_admin_required
def subscription_resume(request, pk):
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.resume():
        messages.success(request, "Subscription resumed.")
    else:
        messages.error(request, "Subscription cannot be resumed.")
    return redirect("subscriptions:subscription_detail", pk=pk)


@login_required
@staff_or_admin_required
def subscription_close(request, pk):
    """Close/Cancel subscription; stops all future recurring billing."""
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.status in (Subscription.Status.CLOSED, Subscription.Status.CANCELLED):
        messages.info(request, "Subscription is already closed.")
    else:
        sub.status = Subscription.Status.CLOSED
        sub.save(update_fields=["status"])
        messages.success(request, f"Subscription {sub.subscription_number} has been closed.")
    return redirect("subscriptions:subscription_detail", pk=pk)


@login_required
@staff_or_admin_required
def subscription_renew(request, pk):
    """Renew an active subscription for another contract duration cycle."""
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.status != Subscription.Status.ACTIVE:
        messages.error(request, "Only active subscriptions can be renewed.")
        return redirect("subscriptions:subscription_detail", pk=pk)
    from dateutil.relativedelta import relativedelta
    months = sub.plan.default_duration_months or 12
    if sub.expiry_date:
        sub.expiry_date = sub.expiry_date + relativedelta(months=months)
    else:
        sub.expiry_date = timezone.now().date() + relativedelta(months=months)
    sub.save(update_fields=["expiry_date"])
    messages.success(request, f"Subscription {sub.subscription_number} renewed until {sub.expiry_date}.")
    return redirect("subscriptions:subscription_detail", pk=pk)


@login_required
def quotation_accept_customer(request, pk):
    """Customer accepts quotation from portal, converting it to Active and generating invoice."""
    sub = get_object_or_404(Subscription, pk=pk)
    if request.user.role == "Customer":
        if not hasattr(request.user, "customer_profile") or sub.customer != request.user.customer_profile:
            messages.error(request, "Access denied.")
            return redirect("dashboard:customer")
    if sub.status not in (Subscription.Status.QUOTATION, Subscription.Status.CONFIRMED):
        messages.error(request, "Quotation is no longer pending acceptance.")
        return redirect("dashboard:customer")
    with transaction.atomic():
        today = timezone.now().date()
        sub.start_date = today
        sub.next_billing_date = today
        months = sub.plan.default_duration_months or 12
        from dateutil.relativedelta import relativedelta
        sub.expiry_date = today + relativedelta(months=months)
        sub.status = Subscription.Status.ACTIVE
        sub.save()
        from billing.services import BillingService
        BillingService.generate_invoice_for_subscription(sub)
    messages.success(request, f"Quotation {sub.subscription_number} accepted! Your subscription is now active.")
    return redirect("dashboard:customer")


@login_required
@staff_or_admin_required
def subscription_toggle_autorenew(request, pk):
    """Toggle auto-renew flag on a subscription."""
    sub = get_object_or_404(Subscription, pk=pk)
    sub.auto_renew = not sub.auto_renew
    sub.save(update_fields=["auto_renew"])
    state = "enabled" if sub.auto_renew else "disabled"
    messages.success(request, f"Auto-renew {state} for {sub.subscription_number}.")
    return redirect("subscriptions:subscription_detail", pk=pk)


