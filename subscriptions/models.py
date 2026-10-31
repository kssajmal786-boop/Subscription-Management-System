"""
subscriptions/models.py – Plans, Subscriptions (unified with Quotations), and Subscription Lines.
"""
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from catalog.models import Product, ProductVariant
from accounts.models import Customer


class Plan(models.Model):
    class BillingCycle(models.TextChoices):
        DAILY = "Daily", "Daily"
        WEEKLY = "Weekly", "Weekly"
        MONTHLY = "Monthly", "Monthly"
        QUARTERLY = "Quarterly", "Quarterly"
        YEARLY = "Yearly", "Yearly"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="plans")
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name="plans")
    plan_name = models.CharField(max_length=200)
    billing_cycle = models.CharField(max_length=20, choices=BillingCycle.choices, default=BillingCycle.MONTHLY)
    base_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))],
                                     help_text="Cycle price (overrides product base price if set)")
    min_quantity = models.PositiveIntegerField(default=1)
    default_duration_months = models.PositiveIntegerField(default=12, help_text="Contract duration in months")
    max_cycles = models.PositiveIntegerField(null=True, blank=True, help_text="Auto-close after N cycles (blank = perpetual)")
    auto_renew_default = models.BooleanField(default=True)
    allow_pause = models.BooleanField(default=True)
    max_pause_days = models.PositiveIntegerField(default=30)
    grace_period_days = models.PositiveIntegerField(default=7, help_text="Days before suspension after overdue invoice")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "plans"
        indexes = [models.Index(fields=["product", "is_active"])]
        ordering = ["plan_name"]

    def __str__(self):
        return f"{self.plan_name} ({self.billing_cycle})"

    def get_effective_price(self):
        if self.base_price and self.base_price > Decimal("0.00"):
            return self.base_price
        if self.variant:
            return self.variant.effective_price
        return self.product.effective_price

    def get_cycle_days(self):
        mapping = {"Daily": 1, "Weekly": 7, "Monthly": 30, "Quarterly": 90, "Yearly": 365}
        return mapping.get(self.billing_cycle, 30)

    def cycle_delta(self):
        """Return timedelta for one billing cycle."""
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta
        if self.billing_cycle == "Daily":
            return timedelta(days=1)
        elif self.billing_cycle == "Weekly":
            return timedelta(weeks=1)
        elif self.billing_cycle == "Monthly":
            return relativedelta(months=1)
        elif self.billing_cycle == "Quarterly":
            return relativedelta(months=3)
        elif self.billing_cycle == "Yearly":
            return relativedelta(years=1)


class Subscription(models.Model):
    class Status(models.TextChoices):
        DRAFT = "Draft", "Draft"
        QUOTATION = "Quotation", "Quotation"
        CONFIRMED = "Confirmed", "Confirmed"
        ACTIVE = "Active", "Active"
        PAUSED = "Paused", "Paused"
        PAST_DUE = "Past_Due", "Past Due"
        CLOSED = "Closed", "Closed"
        CANCELLED = "Cancelled", "Cancelled"

    subscription_number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    applied_discount = models.ForeignKey(
        "billing.Discount", on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions"
    )
    quotation_validity_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    paused_at = models.DateField(null=True, blank=True)
    total_paused_days = models.PositiveIntegerField(default=0)
    auto_renew = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, related_name="created_subscriptions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions"
        indexes = [
            models.Index(fields=["status", "next_billing_date"], name="idx_sub_billing"),
            models.Index(fields=["customer", "status"], name="idx_sub_cust"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subscription_number} – {self.customer}"

    @classmethod
    def generate_number(cls):
        year = timezone.now().year
        last = cls.objects.filter(subscription_number__startswith=f"SUB-{year}-").order_by("-id").first()
        seq = 1
        if last:
            try:
                seq = int(last.subscription_number.split("-")[-1]) + 1
            except ValueError:
                seq = cls.objects.count() + 1
        return f"SUB-{year}-{seq:05d}"

    def pause(self, pause_date=None):
        from django.utils import timezone
        if self.plan.allow_pause and self.status == self.Status.ACTIVE:
            self.paused_at = pause_date or timezone.now().date()
            self.status = self.Status.PAUSED
            self.save(update_fields=["status", "paused_at"])
            return True
        return False

    def resume(self, resume_date=None):
        from datetime import timedelta
        if self.status == self.Status.PAUSED and self.paused_at:
            resume = resume_date or timezone.now().date()
            delta = (resume - self.paused_at).days
            if self.next_billing_date:
                self.next_billing_date = self.next_billing_date + timedelta(days=delta)
            if self.expiry_date:
                self.expiry_date = self.expiry_date + timedelta(days=delta)
            self.total_paused_days += delta
            self.paused_at = None
            self.status = self.Status.ACTIVE
            self.save(update_fields=["status", "paused_at", "next_billing_date", "expiry_date", "total_paused_days"])
            return True
        return False

    def activate(self, start_date=None):
        """Transition from Quotation/Draft → Active and initialize billing schedules."""
        today = start_date or timezone.now().date()
        self.status = self.Status.ACTIVE
        self.start_date = today
        self.next_billing_date = today
        duration_months = self.plan.default_duration_months or 12
        from dateutil.relativedelta import relativedelta
        self.expiry_date = today + relativedelta(months=duration_months)
        if self.subscription_number.startswith("QUO"):
            self.subscription_number = self.subscription_number.replace("QUO", "SUB")
        self.save()


    def get_proration_charge(self, new_cycle_price):
        """Calculate pro-rata charge for mid-cycle upgrade."""
        if not self.next_billing_date or not self.start_date:
            return Decimal("0.00")
        today = timezone.now().date()
        cycle_days = self.plan.get_cycle_days()
        d_remaining = max(0, (self.next_billing_date - today).days)
        old_price = self.plan.get_effective_price()
        if new_cycle_price <= old_price:
            return Decimal("0.00")
        return (new_cycle_price - old_price) * Decimal(d_remaining) / Decimal(cycle_days)

    @property
    def is_quotation(self):
        return self.status in (self.Status.DRAFT, self.Status.QUOTATION)

    @property
    def next_invoice_date(self):
        return self.next_billing_date

    @property
    def end_date(self):
        return self.expiry_date

    @property
    def mrr(self):
        """Normalized monthly recurring revenue for this subscription."""
        if not self.plan:
            return Decimal("0.00")
        price = self.plan.get_effective_price()
        cycle = self.plan.billing_cycle
        factor = {"Daily": 30, "Weekly": 4.33, "Monthly": 1, "Quarterly": 1/3, "Yearly": 1/12}
        return price * Decimal(str(factor.get(cycle, 1)))


class SubscriptionLine(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Snapshot price at confirmation")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Snapshot tax rate at confirmation")
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "subscription_lines"
        indexes = [models.Index(fields=["subscription"])]

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"

    def save(self, *args, **kwargs):
        self.line_subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    @property
    def tax_amount(self):
        return self.line_subtotal * (self.tax_rate / Decimal("100"))

    @property
    def line_total_with_tax(self):
        return self.line_subtotal + self.tax_amount

