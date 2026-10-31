"""
billing/serializers.py – DRF serializers for the billing API.
"""
from rest_framework import serializers
from .models import Invoice, InvoiceLine, Payment, Discount, MonthlyRevenueSnapshot


class InvoiceLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    variant_name = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields = [
            "id", "product_name", "variant_name", "description",
            "quantity", "unit_price", "discount_amount",
            "tax_rate", "taxable_amount", "tax_amount", "line_total",
        ]

    def get_variant_name(self, obj):
        return obj.variant.attribute_value if obj.variant else None


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.user.get_full_name", read_only=True)
    customer_email = serializers.CharField(source="customer.user.email", read_only=True)
    subscription_number = serializers.CharField(source="subscription.subscription_number", read_only=True)
    discount_code = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "customer_name", "customer_email",
            "subscription_number", "discount_code",
            "billing_period_start", "billing_period_end",
            "invoice_date", "due_date",
            "subtotal", "discount_amount", "taxable_amount",
            "tax_amount", "total_amount", "amount_paid", "balance_due",
            "status", "pdf_file_path", "lines",
        ]

    def get_discount_code(self, obj):
        return obj.discount.code if obj.discount else None


class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    customer_name = serializers.CharField(source="customer.user.get_full_name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "payment_number", "invoice_number", "customer_name",
            "amount", "payment_method", "transaction_reference",
            "payment_date", "status", "notes",
        ]
        read_only_fields = ["payment_number", "invoice_number", "customer_name"]


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = [
            "id", "code", "name", "discount_type", "discount_value",
            "max_discount_cap", "min_purchase_amount", "min_quantity",
            "start_date", "end_date", "max_usage_limit", "used_count",
            "applicable_cycles", "is_active",
        ]


class MonthlySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthlyRevenueSnapshot
        fields = "__all__"
