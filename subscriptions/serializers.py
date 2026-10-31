from rest_framework import serializers
from decimal import Decimal
from accounts.models import Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from subscriptions.models import (
    Plan, Subscription, SubscriptionLine, SubscriptionHistory
)


class CustomerSerializer(serializers.ModelSerializer):
    customer_id = serializers.IntegerField(source='id', read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'customer_id', 'name', 'email', 'company_name', 'phone', 'billing_address', 'gst_number', 'status', 'created_at', 'updated_at'
        ]


class ProductVariantSerializer(serializers.ModelSerializer):
    variant_id = serializers.IntegerField(source='id', read_only=True)
    effective_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'variant_id', 'product', 'attribute_name', 'attribute_value',
            'additional_price', 'effective_price', 'sku', 'is_active',
            'created_at'
        ]


class ProductSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    active_variants_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'product_id', 'name', 'product_type', 'base_sales_price',
            'cost_price', 'tax_rate', 'hsn_sac_code', 'description',
            'is_active', 'variants', 'active_variants_count',
            'created_at', 'updated_at'
        ]


class PlanSerializer(serializers.ModelSerializer):
    plan_id = serializers.IntegerField(source='id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    variant_name = serializers.CharField(source='variant.attribute_value', read_only=True)
    default_duration = serializers.IntegerField(source='default_duration_months', read_only=True)

    class Meta:
        model = Plan
        fields = [
            'id', 'plan_id', 'plan_name', 'product', 'product_name',
            'variant', 'variant_name', 'billing_cycle', 'base_price',
            'min_quantity', 'default_duration', 'auto_renew_default',
            'allow_pause', 'max_pause_days', 'grace_period_days',
            'max_cycles', 'is_active', 'created_at'
        ]


class DiscountSerializer(serializers.ModelSerializer):
    discount_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = Discount
        fields = [
            'id', 'discount_id', 'code', 'name', 'discount_type', 'discount_value',
            'min_purchase_amount', 'min_quantity', 'start_date', 'end_date',
            'max_usage_limit', 'used_count', 'is_active', 'created_at'
        ]


class SubscriptionLineSerializer(serializers.ModelSerializer):
    line_id = serializers.IntegerField(source='id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    variant_name = serializers.CharField(source='variant.attribute_value', read_only=True)

    class Meta:
        model = SubscriptionLine
        fields = [
            'id', 'line_id', 'subscription', 'product', 'product_name',
            'variant', 'variant_name', 'quantity', 'unit_price',
            'tax_rate', 'line_subtotal', 'tax_amount', 'line_total'
        ]
        read_only_fields = ['line_subtotal', 'tax_amount', 'line_total']


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    history_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = SubscriptionHistory
        fields = [
            'id', 'history_id', 'subscription', 'action', 'old_status',
            'new_status', 'description', 'performed_by', 'created_at'
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    subscription_id = serializers.IntegerField(source='id', read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)
    plan_details = PlanSerializer(source='plan', read_only=True)
    lines = SubscriptionLineSerializer(many=True, read_only=True)
    history = SubscriptionHistorySerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_tax = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'subscription_id', 'subscription_number', 'quotation_number',
            'customer', 'customer_details', 'plan', 'plan_details',
            'applied_discount', 'discount_amount', 'quotation_validity_date',
            'start_date', 'next_billing_date', 'expiry_date', 'paused_at',
            'total_paused_days', 'auto_renew', 'status', 'notes',
            'subtotal', 'total_tax', 'total_amount', 'lines', 'history',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'subscription_number', 'quotation_number', 'subtotal',
            'total_tax', 'total_amount', 'total_paused_days', 'created_at', 'updated_at'
        ]


class QuotationLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(default=1, min_value=1)
    custom_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)


class QuotationCreateSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    plan_id = serializers.IntegerField()
    lines = QuotationLineInputSerializer(many=True)
    validity_days = serializers.IntegerField(default=15, min_value=1)
    discount_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)


class PauseSubscriptionSerializer(serializers.Serializer):
    pause_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class ResumeSubscriptionSerializer(serializers.Serializer):
    resume_date = serializers.DateField(required=False, allow_null=True)


class CancelSubscriptionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
