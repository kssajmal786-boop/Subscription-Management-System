from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import date
from decimal import Decimal

from accounts.models import Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from subscriptions.models import (
    Plan, Subscription, SubscriptionLine, SubscriptionHistory
)
from subscriptions.forms import (
    ProductForm, ProductVariantForm, PlanForm, CustomerForm,
    PauseSubscriptionForm, ResumeSubscriptionForm
)
from subscriptions.services import (
    QuotationService, LifecycleService, PauseResumeService, SnapshotService
)


class DashboardView(View):
    """
    Subscribify Module Overview & Operations Dashboard.
    """
    def get(self, request):
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()

        total_products = Product.objects.count()
        active_products = Product.objects.filter(is_active=True).count()
        total_plans = Plan.objects.filter(is_active=True).count()
        
        # Quotation stats
        pending_quotations = Subscription.objects.filter(
            status__in=[Subscription.Status.DRAFT, Subscription.Status.QUOTATION]
        ).count()
        
        # Subscriptions stats
        active_subs = Subscription.objects.filter(status=Subscription.Status.ACTIVE)
        active_subs_count = active_subs.count()
        paused_subs_count = Subscription.objects.filter(status=Subscription.Status.PAUSED).count()
        confirmed_subs_count = Subscription.objects.filter(status=Subscription.Status.CONFIRMED).count()

        # Due for billing today or overdue billing
        due_billing_count = Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            next_billing_date__lte=today
        ).count()

        # Estimated MRR (Monthly Recurring Revenue) from active subscriptions
        mrr_estimate = Decimal('0.00')
        for sub in active_subs.select_related('plan').prefetch_related('lines'):
            sub_total = sub.total_amount
            cycle = sub.plan.billing_cycle
            if cycle == Plan.BillingCycle.MONTHLY:
                mrr_estimate += sub_total
            elif cycle == Plan.BillingCycle.YEARLY:
                mrr_estimate += (sub_total / Decimal('12.00'))
            elif cycle == Plan.BillingCycle.QUARTERLY:
                mrr_estimate += (sub_total / Decimal('3.00'))
            elif cycle == Plan.BillingCycle.WEEKLY:
                mrr_estimate += (sub_total * Decimal('4.33'))
            elif cycle == Plan.BillingCycle.DAILY:
                mrr_estimate += (sub_total * Decimal('30.00'))

        recent_subscriptions = Subscription.objects.select_related(
            'customer', 'plan'
        ).order_by('-created_at')[:8]

        recent_history = SubscriptionHistory.objects.select_related(
            'subscription'
        ).order_by('-created_at')[:8]

        context = {
            'total_products': total_products,
            'active_products': active_products,
            'total_plans': total_plans,
            'pending_quotations': pending_quotations,
            'active_subs_count': active_subs_count,
            'paused_subs_count': paused_subs_count,
            'confirmed_subs_count': confirmed_subs_count,
            'due_billing_count': due_billing_count,
            'mrr_estimate': mrr_estimate.quantize(Decimal('0.01')),
            'recent_subscriptions': recent_subscriptions,
            'recent_history': recent_history,
        }
        return render(request, 'subscriptions/dashboard.html', context)


# ==========================================
# 1. Product & Variant Catalog Management
# ==========================================

class ProductListView(View):
    def get(self, request):
        qs = Product.objects.prefetch_related('variants').all().order_by('name')

        search = request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(hsn_sac_code__icontains=search))

        product_type = request.GET.get('type')
        if product_type:
            qs = qs.filter(product_type=product_type)

        status_filter = request.GET.get('status')
        if status_filter == 'active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'archived':
            qs = qs.filter(is_active=False)

        context = {
            'products': qs,
            'search': search,
            'selected_type': product_type,
            'selected_status': status_filter,
            'product_types': Product.ProductType.choices,
        }
        return render(request, 'subscriptions/products/product_list.html', context)


class ProductCreateView(View):
    def get(self, request):
        form = ProductForm(initial={'is_active': True, 'tax_rate': 18.00})
        return render(request, 'subscriptions/products/product_form.html', {'form': form, 'is_create': True})

    def post(self, request):
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product '{product.name}' created successfully.")
            return redirect('subscriptions:product_detail', pk=product.pk)
        return render(request, 'subscriptions/products/product_form.html', {'form': form, 'is_create': True})


class ProductUpdateView(View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductForm(instance=product)
        return render(request, 'subscriptions/products/product_form.html', {
            'form': form,
            'product': product,
            'is_create': False
        })

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product '{product.name}' updated successfully.")
            return redirect('subscriptions:product_detail', pk=product.pk)
        return render(request, 'subscriptions/products/product_form.html', {
            'form': form,
            'product': product,
            'is_create': False
        })


class ProductDetailView(View):
    def get(self, request, pk):
        product = get_object_or_404(Product.objects.prefetch_related('variants', 'plans'), pk=pk)
        variant_form = ProductVariantForm(initial={'product': product, 'is_active': True})
        return render(request, 'subscriptions/products/product_detail.html', {
            'product': product,
            'variant_form': variant_form,
        })


class ProductArchiveToggleView(View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = not product.is_active
        product.save(update_fields=['is_active', 'updated_at'])
        state = "restored" if product.is_active else "archived"
        messages.info(request, f"Product '{product.name}' has been {state}.")
        return redirect('subscriptions:product_list')


class VariantCreateView(View):
    def post(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        form = ProductVariantForm(request.POST)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            variant.save()
            messages.success(request, f"Variant '{variant.attribute_value}' (SKU: {variant.sku}) added.")
        else:
            for error in form.errors.values():
                messages.error(request, error)
        return redirect('subscriptions:product_detail', pk=product_id)


class VariantUpdateView(View):
    def get(self, request, pk):
        variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=pk)
        form = ProductVariantForm(instance=variant)
        return render(request, 'subscriptions/products/variant_form.html', {'form': form, 'variant': variant})

    def post(self, request, pk):
        variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=pk)
        form = ProductVariantForm(request.POST, instance=variant)
        if form.is_valid():
            form.save()
            messages.success(request, f"Variant '{variant.attribute_value}' updated.")
            return redirect('subscriptions:product_detail', pk=variant.product_id)
        return render(request, 'subscriptions/products/variant_form.html', {'form': form, 'variant': variant})


class VariantToggleView(View):
    def post(self, request, pk):
        variant = get_object_or_404(ProductVariant, pk=pk)
        variant.is_active = not variant.is_active
        variant.save(update_fields=['is_active', 'updated_at'])
        state = "activated" if variant.is_active else "deactivated"
        messages.info(request, f"Variant '{variant.attribute_value}' has been {state}.")
        return redirect('subscriptions:product_detail', pk=variant.product_id)


# ==========================================
# 2. Subscription Plan Management
# ==========================================

class PlanListView(View):
    def get(self, request):
        qs = Plan.objects.select_related('product', 'variant').all().order_by('plan_name')

        cycle = request.GET.get('cycle')
        if cycle:
            qs = qs.filter(billing_cycle=cycle)

        product_id = request.GET.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)

        context = {
            'plans': qs,
            'selected_cycle': cycle,
            'selected_product': product_id,
            'cycles': Plan.BillingCycle.choices,
            'products': Product.objects.filter(is_active=True),
        }
        return render(request, 'subscriptions/plans/plan_list.html', context)


class PlanCreateView(View):
    def get(self, request):
        form = PlanForm(initial={'is_active': True, 'allow_pause': True, 'auto_renew_default': True})
        return render(request, 'subscriptions/plans/plan_form.html', {'form': form, 'is_create': True})

    def post(self, request):
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Plan '{plan.plan_name}' created successfully.")
            return redirect('subscriptions:plan_list')
        return render(request, 'subscriptions/plans/plan_form.html', {'form': form, 'is_create': True})


class PlanUpdateView(View):
    def get(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanForm(instance=plan)
        return render(request, 'subscriptions/plans/plan_form.html', {
            'form': form,
            'plan': plan,
            'is_create': False
        })

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Plan '{plan.plan_name}' updated successfully.")
            return redirect('subscriptions:plan_list')
        return render(request, 'subscriptions/plans/plan_form.html', {
            'form': form,
            'plan': plan,
            'is_create': False
        })


class PlanDetailView(View):
    def get(self, request, pk):
        plan = get_object_or_404(Plan.objects.select_related('product', 'variant'), pk=pk)
        subscriptions_count = plan.subscriptions.count()
        return render(request, 'subscriptions/plans/plan_detail.html', {
            'plan': plan,
            'subscriptions_count': subscriptions_count
        })


# ==========================================
# 3. Quotation Management & Builder
# ==========================================

class QuotationBuilderView(View):
    """
    Interactive Quotation Builder:
    Select customer, plan, add/remove dynamic product and variant lines,
    calculate subtotal, taxes, apply discounts, set validity date,
    and save as Draft or Send Quotation.
    """
    def get(self, request):
        customers = Customer.objects.filter(is_active=True)
        plans = Plan.objects.filter(is_active=True).select_related('product', 'variant')
        products = Product.objects.filter(is_active=True).prefetch_related('variants')
        discounts = Discount.objects.filter(is_active=True)

        context = {
            'customers': customers,
            'plans': plans,
            'products': products,
            'discounts': discounts,
        }
        return render(request, 'subscriptions/quotations/quotation_builder.html', context)

    def post(self, request):
        try:
            customer_id = request.POST.get('customer_id')
            plan_id = request.POST.get('plan_id')
            validity_days = int(request.POST.get('validity_days', 15))
            discount_code = request.POST.get('discount_code', '').strip()
            notes = request.POST.get('notes', '').strip()
            action_type = request.POST.get('action_type', 'save_draft')

            customer = get_object_or_404(Customer, pk=customer_id)
            plan = get_object_or_404(Plan, pk=plan_id)

            # Parse lines from dynamic form
            product_ids = request.POST.getlist('product_id[]')
            variant_ids = request.POST.getlist('variant_id[]')
            quantities = request.POST.getlist('quantity[]')
            custom_prices = request.POST.getlist('custom_price[]')

            lines_data = []
            for i in range(len(product_ids)):
                if not product_ids[i]:
                    continue
                p_id = int(product_ids[i])
                v_id = int(variant_ids[i]) if (i < len(variant_ids) and variant_ids[i]) else None
                qty = int(quantities[i]) if (i < len(quantities) and quantities[i]) else 1
                c_price = Decimal(custom_prices[i]) if (i < len(custom_prices) and custom_prices[i]) else None

                lines_data.append({
                    'product_id': p_id,
                    'variant_id': v_id,
                    'quantity': qty,
                    'custom_price': c_price
                })

            if not lines_data:
                messages.error(request, "Please add at least one line item to the quotation.")
                return redirect('subscriptions:quotation_builder')

            # Create quotation
            subscription = QuotationService.create_quotation(
                customer=customer,
                plan=plan,
                lines_data=lines_data,
                validity_days=validity_days,
                discount_code=discount_code if discount_code else None,
                notes=notes,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )

            # If user clicked "Send Quotation Directly"
            if action_type == 'send_now':
                QuotationService.send_quotation(
                    subscription.pk,
                    user_name=request.user.username if request.user.is_authenticated else 'Staff'
                )
                messages.success(request, f"Quotation {subscription.subscription_number} created and sent to {customer.company_name}!")
            else:
                messages.success(request, f"Draft Quotation {subscription.subscription_number} saved successfully.")

            return redirect('subscriptions:quotation_detail', pk=subscription.pk)

        except Exception as e:
            messages.error(request, f"Failed to create quotation: {str(e)}")
            return redirect('subscriptions:quotation_builder')


class QuotationTrackerView(View):
    """
    Quotation Tracker: view all Draft and Sent quotations, filter by validity,
    customer, and quick conversion actions.
    """
    def get(self, request):
        qs = Subscription.objects.filter(
            status__in=[Subscription.Status.DRAFT, Subscription.Status.QUOTATION]
        ).select_related('customer', 'plan').prefetch_related('lines').order_by('-created_at')

        status_filter = request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        search = request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(subscription_number__icontains=search) |
                Q(customer__company_name__icontains=search) |
                Q(customer__email__icontains=search)
            )

        context = {
            'quotations': qs,
            'selected_status': status_filter,
            'search': search,
            'today': timezone.localdate() if timezone.is_aware(timezone.now()) else date.today(),
        }
        return render(request, 'subscriptions/quotations/quotation_tracker.html', context)


class QuotationDetailView(View):
    """
    Quotation Details page with itemized lines, taxes, discounts,
    history audit, and workflow actions (Send, Accept & Confirm, Reject).
    """
    def get(self, request, pk):
        quotation = get_object_or_404(
            Subscription.objects.select_related('customer', 'plan', 'applied_discount')
            .prefetch_related('lines__product', 'lines__variant', 'history'),
            pk=pk
        )
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        is_expired = quotation.quotation_validity_date and quotation.quotation_validity_date < today

        context = {
            'quotation': quotation,
            'is_expired': is_expired,
            'today': today,
        }
        return render(request, 'subscriptions/quotations/quotation_detail.html', context)


class QuotationSendActionView(View):
    def post(self, request, pk):
        try:
            sub = QuotationService.send_quotation(
                pk,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            messages.success(request, f"Quotation {sub.subscription_number} sent to customer.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        return redirect('subscriptions:quotation_detail', pk=pk)


class QuotationConfirmActionView(View):
    def post(self, request, pk):
        try:
            sub = LifecycleService.confirm_quotation(
                pk,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            messages.success(
                request,
                f"Quotation confirmed! Upgraded to Subscription {sub.subscription_number} with price snapshot."
            )
            return redirect('subscriptions:subscription_detail', pk=sub.pk)
        except Exception as e:
            messages.error(request, f"Confirmation failed: {str(e)}")
            return redirect('subscriptions:quotation_detail', pk=pk)


class QuotationRejectActionView(View):
    def post(self, request, pk):
        try:
            reason = request.POST.get('reason', 'Customer rejected quotation')
            sub = LifecycleService.cancel_subscription(
                pk,
                reason=reason,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            messages.info(request, f"Quotation {sub.subscription_number} marked as Cancelled/Rejected.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        return redirect('subscriptions:quotation_tracker')


# ==========================================
# 4. Subscription Lifecycle Management
# ==========================================

class SubscriptionListView(View):
    """
    Subscription Manager: Filter and monitor Active, Paused, Past Due,
    Confirmed, and Closed subscriptions.
    """
    def get(self, request):
        qs = Subscription.objects.exclude(
            status__in=[Subscription.Status.DRAFT, Subscription.Status.QUOTATION]
        ).select_related('customer', 'plan').prefetch_related('lines').order_by('-created_at')

        status_filter = request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        search = request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(subscription_number__icontains=search) |
                Q(customer__company_name__icontains=search) |
                Q(customer__email__icontains=search)
            )

        context = {
            'subscriptions': qs,
            'selected_status': status_filter,
            'search': search,
            'statuses': [s for s in Subscription.Status.choices if s[0] not in ['Draft', 'Quotation']],
            'today': timezone.localdate() if timezone.is_aware(timezone.now()) else date.today(),
        }
        return render(request, 'subscriptions/subscriptions/subscription_list.html', context)


class SubscriptionDetailView(View):
    """
    Detailed contract view with frozen price snapshot lines,
    recurring billing timeline, pause duration metrics, and lifecycle controls.
    """
    def get(self, request, pk):
        subscription = get_object_or_404(
            Subscription.objects.select_related('customer', 'plan', 'applied_discount')
            .prefetch_related('lines__product', 'lines__variant', 'history'),
            pk=pk
        )
        pause_form = PauseSubscriptionForm()
        resume_form = ResumeSubscriptionForm()
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()

        context = {
            'subscription': subscription,
            'pause_form': pause_form,
            'resume_form': resume_form,
            'today': today,
        }
        return render(request, 'subscriptions/subscriptions/subscription_detail.html', context)


class SubscriptionPauseActionView(View):
    """
    Executes pause on active subscription.
    """
    def post(self, request, pk):
        try:
            form = PauseSubscriptionForm(request.POST)
            pause_date = None
            reason = ''
            if form.is_valid():
                pause_date = form.cleaned_data.get('pause_date')
                reason = form.cleaned_data.get('reason')

            sub = PauseResumeService.pause_subscription(
                subscription_id=pk,
                pause_date=pause_date,
                reason=reason,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            messages.warning(
                request,
                f"Subscription {sub.subscription_number} paused as of {sub.paused_at}. Billing is suspended."
            )
        except Exception as e:
            messages.error(request, f"Pause failed: {str(e)}")
        return redirect('subscriptions:subscription_detail', pk=pk)


class SubscriptionResumeActionView(View):
    """
    Executes resume on paused subscription:
    Calculates paused duration and shifts next_billing_date and expiry_date.
    """
    def post(self, request, pk):
        try:
            form = ResumeSubscriptionForm(request.POST)
            resume_date = None
            if form.is_valid():
                resume_date = form.cleaned_data.get('resume_date')

            res = PauseResumeService.resume_subscription(
                subscription_id=pk,
                resume_date=resume_date,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            sub = res['subscription']
            paused_days = res['paused_days']
            messages.success(
                request,
                f"Subscription {sub.subscription_number} resumed! Paused for {paused_days} days. "
                f"Next Billing shifted to {res['new_next_billing_date']} and Expiry shifted to {res['new_expiry_date']}."
            )
        except Exception as e:
            messages.error(request, f"Resume failed: {str(e)}")
        return redirect('subscriptions:subscription_detail', pk=pk)


class SubscriptionCancelActionView(View):
    """
    Cancels an active or paused subscription.
    """
    def post(self, request, pk):
        try:
            reason = request.POST.get('reason', 'Cancelled by administrator')
            sub = LifecycleService.cancel_subscription(
                subscription_id=pk,
                reason=reason,
                user_name=request.user.username if request.user.is_authenticated else 'Staff'
            )
            messages.info(request, f"Subscription {sub.subscription_number} has been cancelled.")
        except Exception as e:
            messages.error(request, f"Cancellation failed: {str(e)}")
        return redirect('subscriptions:subscription_detail', pk=pk)
