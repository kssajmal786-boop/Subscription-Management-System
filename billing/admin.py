"""billing/admin.py"""
from django.contrib import admin
from .models import Invoice, InvoiceLine, Payment, Discount, MonthlyRevenueSnapshot, Notification


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    readonly_fields = ("line_total", "tax_amount", "taxable_amount")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("payment_number", "amount", "payment_method", "status")
    fields = ("payment_number", "amount", "payment_method", "payment_date", "status", "transaction_reference")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer", "total_amount", "balance_due", "status", "due_date")
    list_filter = ("status",)
    search_fields = ("invoice_number", "customer__company_name")
    date_hierarchy = "invoice_date"
    inlines = [InvoiceLineInline, PaymentInline]
    readonly_fields = ("invoice_number", "total_amount", "balance_due", "amount_paid")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_number", "invoice", "amount", "payment_method", "status", "payment_date")
    list_filter = ("status", "payment_method")
    search_fields = ("payment_number", "transaction_reference")
    date_hierarchy = "payment_date"


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "discount_type", "discount_value", "used_count", "is_active", "end_date")
    list_filter = ("discount_type", "is_active", "applicable_cycles")
    search_fields = ("code", "name")


@admin.register(MonthlyRevenueSnapshot)
class MonthlySnapshotAdmin(admin.ModelAdmin):
    list_display = ("year_month", "billed_amount", "collected_amount", "active_subscriptions_count")
    ordering = ("-year_month",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "subject", "is_read", "created_at")
    list_filter = ("event_type", "is_read")
