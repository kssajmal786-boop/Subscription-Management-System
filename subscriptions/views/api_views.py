from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from datetime import date
from django.db.models import Q

from accounts.models import Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from subscriptions.models import (
    Plan, Subscription, SubscriptionLine, SubscriptionHistory
)
from subscriptions.serializers import (
    CustomerSerializer, ProductSerializer, ProductVariantSerializer,
    PlanSerializer, DiscountSerializer, SubscriptionSerializer,
    QuotationCreateSerializer, PauseSubscriptionSerializer,
    ResumeSubscriptionSerializer, CancelSubscriptionSerializer
)
from subscriptions.services import (
    QuotationService, LifecycleService, PauseResumeService, SnapshotService
)


class CustomerViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Customer profiles.
    """
    permission_classes = [AllowAny]
    queryset = Customer.objects.all().order_by('-created_at')
    serializer_class = CustomerSerializer
    search_fields = ['name', 'company_name', 'email', 'gst_number']


class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD & Search API for Products catalog.
    Supports soft-archiving to protect contract integrity.
    """
    queryset = Product.objects.all().prefetch_related('variants').order_by('name')
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        active_filter = self.request.query_params.get('is_active')
        if active_filter is not None:
            qs = qs.filter(is_active=active_filter.lower() in ('true', '1'))
        ptype = self.request.query_params.get('product_type')
        if ptype:
            qs = qs.filter(product_type=ptype)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(hsn_sac_code__icontains=search))
        return qs

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        product = self.get_object()
        product.is_active = False
        product.save(update_fields=['is_active', 'updated_at'])
        return Response({'status': 'archived', 'product_id': product.product_id, 'is_active': False})

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        product = self.get_object()
        product.is_active = True
        product.save(update_fields=['is_active', 'updated_at'])
        return Response({'status': 'restored', 'product_id': product.product_id, 'is_active': True})


class ProductVariantViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Product Variants with price differentials and SKUs.
    """
    queryset = ProductVariant.objects.select_related('product').all().order_by('product', 'attribute_value')
    serializer_class = ProductVariantSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        active_filter = self.request.query_params.get('is_active')
        if active_filter is not None:
            qs = qs.filter(is_active=active_filter.lower() in ('true', '1'))
        return qs

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        variant = self.get_object()
        variant.is_active = not variant.is_active
        variant.save(update_fields=['is_active', 'updated_at'])
        return Response({
            'status': 'toggled',
            'variant_id': variant.variant_id,
            'is_active': variant.is_active
        })


class PlanViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Reusable Subscription Plans.
    """
    queryset = Plan.objects.select_related('product', 'variant').all().order_by('plan_name')
    serializer_class = PlanSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        cycle = self.request.query_params.get('billing_cycle')
        if cycle:
            qs = qs.filter(billing_cycle=cycle)
        product_id = self.request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        active_filter = self.request.query_params.get('is_active')
        if active_filter is not None:
            qs = qs.filter(is_active=active_filter.lower() in ('true', '1'))
        return qs


class DiscountViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Promotional & Volume Discounts.
    """
    queryset = Discount.objects.all().order_by('code')
    serializer_class = DiscountSerializer
    permission_classes = [AllowAny]


class SubscriptionViewSet(viewsets.ModelViewSet):
    """
    Unified API for Quotations and Subscriptions Lifecycle:
    Draft -> Quotation -> Confirmed -> Active -> Paused / Past Due -> Closed / Cancelled.
    """
    queryset = Subscription.objects.select_related(
        'customer', 'plan', 'plan__product', 'plan__variant', 'applied_discount'
    ).prefetch_related('lines', 'lines__product', 'lines__variant', 'history').all().order_by('-created_at')
    serializer_class = SubscriptionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        customer_id = self.request.query_params.get('customer_id')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        sub_type = self.request.query_params.get('type')
        if sub_type == 'quotation':
            qs = qs.filter(status__in=[Subscription.Status.DRAFT, Subscription.Status.QUOTATION])
        elif sub_type == 'subscription':
            qs = qs.exclude(status__in=[Subscription.Status.DRAFT, Subscription.Status.QUOTATION])
        return qs

    def create(self, request, *args, **kwargs):
        """
        Custom create endpoint: drafts a new quotation with line items and price snapshots.
        """
        serializer = QuotationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            customer = Customer.objects.get(pk=data['customer_id'])
            plan = Plan.objects.get(pk=data['plan_id'])
            subscription = QuotationService.create_quotation(
                customer=customer,
                plan=plan,
                lines_data=data['lines'],
                validity_days=data.get('validity_days', 15),
                discount_code=data.get('discount_code'),
                notes=data.get('notes', ''),
                user_name=request.user.username if request.user.is_authenticated else 'API Client'
            )
            output = SubscriptionSerializer(subscription).data
            return Response(output, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='calculate')
    def calculate_quotation(self, request):
        """
        Stateless calculation preview for quotation builder.
        Accepts: lines: [{product_id, variant_id, quantity, custom_price}], discount_code
        """
        lines = request.data.get('lines', [])
        discount_code = request.data.get('discount_code')
        try:
            res = QuotationService.calculate_quotation_totals(lines, discount_code)
            formatted_lines = []
            for line in res['lines']:
                formatted_lines.append({
                    'product_id': line['product'].product_id,
                    'product_name': line['product'].name,
                    'variant_id': line['variant'].variant_id if line['variant'] else None,
                    'variant_name': line['variant'].attribute_value if line['variant'] else None,
                    'quantity': line['quantity'],
                    'unit_price': str(line['unit_price']),
                    'tax_rate': str(line['tax_rate']),
                    'line_subtotal': str(line['line_subtotal']),
                    'tax_amount': str(line['tax_amount']),
                    'line_total': str(line['line_total']),
                })
            return Response({
                'subtotal': str(res['subtotal']),
                'discount_amount': str(res['discount_amount']),
                'total_tax': str(res['total_tax']),
                'grand_total': str(res['grand_total']),
                'total_quantity': res['total_quantity'],
                'discount_applied': res['applied_discount'].code if res['applied_discount'] else None,
                'discount_error': res['discount_error'],
                'lines': formatted_lines,
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """
        Sends draft quotation to customer.
        """
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        try:
            sub = QuotationService.send_quotation(pk, user_name=user_name)
            return Response(SubscriptionSerializer(sub).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        Accepts & confirms quotation -> upgrades to active contract.
        """
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        start_date = request.data.get('start_date')
        try:
            sub = LifecycleService.confirm_quotation(pk, start_date=start_date, user_name=user_name)
            return Response(SubscriptionSerializer(sub).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """
        Activates confirmed subscription into recurring billing.
        """
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        try:
            sub = LifecycleService.activate_subscription(pk, user_name=user_name)
            return Response(SubscriptionSerializer(sub).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """
        Pauses an active subscription.
        """
        serializer = PauseSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        try:
            sub = PauseResumeService.pause_subscription(
                subscription_id=pk,
                pause_date=serializer.validated_data.get('pause_date'),
                reason=serializer.validated_data.get('reason', ''),
                user_name=user_name
            )
            return Response(SubscriptionSerializer(sub).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """
        Resumes a paused subscription with pause-duration date shift.
        """
        serializer = ResumeSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        try:
            res = PauseResumeService.resume_subscription(
                subscription_id=pk,
                resume_date=serializer.validated_data.get('resume_date'),
                user_name=user_name
            )
            data = SubscriptionSerializer(res['subscription']).data
            data['resume_details'] = {
                'paused_days': res['paused_days'],
                'old_next_billing_date': res['old_next_billing_date'],
                'new_next_billing_date': res['new_next_billing_date'],
                'old_expiry_date': res['old_expiry_date'],
                'new_expiry_date': res['new_expiry_date'],
            }
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancels a quotation or subscription.
        """
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_name = request.user.username if request.user.is_authenticated else 'Staff'
        try:
            sub = LifecycleService.cancel_subscription(
                subscription_id=pk,
                reason=serializer.validated_data.get('reason', ''),
                user_name=user_name
            )
            return Response(SubscriptionSerializer(sub).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='due-billing')
    def due_billing(self, request):
        """
        CRITICAL INTEGRATION ENDPOINT FOR MODULE 5 (Automated Billing Engine):
        Returns all Active subscriptions whose next_billing_date <= today.
        """
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        subs = Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            next_billing_date__lte=today
        ).select_related('customer', 'plan').prefetch_related('lines')
        return Response(SubscriptionSerializer(subs, many=True).data)
