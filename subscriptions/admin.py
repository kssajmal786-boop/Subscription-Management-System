"""subscriptions/admin.py"""
from django.contrib import admin
from .models import Plan, Subscription, SubscriptionLine


class SubscriptionLineInline(admin.TabularInline):
    model = SubscriptionLine
    extra = 0
    fields = ("product", "variant", "quantity", "unit_price", "tax_rate", "line_subtotal")
    readonly_fields = ("line_subtotal",)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("plan_name", "product", "billing_cycle", "base_price", "is_active")
    list_filter = ("billing_cycle", "is_active")
    search_fields = ("plan_name",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("subscription_number", "customer", "plan", "status", "next_billing_date")
    list_filter = ("status",)
    search_fields = ("subscription_number", "customer__company_name")
    inlines = [SubscriptionLineInline]
