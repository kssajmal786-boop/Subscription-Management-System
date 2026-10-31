"""
billing/models.py – Discounts, Invoices, Invoice Lines, Payments,
                    Monthly Revenue Snapshots, and Notifications.

All monetary fields use DECIMAL(12,2) – never float.
Idempotency constraint: UNIQUE(subscription_id, billing_period_start, billing_period_end)
"""
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from catalog.models import Product, ProductVariant
from accounts.models import Customer, User


# ---------------------------------------------------------------------------
# Discount Rule Engine
# ---------------------------------------------------------------------------
class Discount(models.Model):
    class DiscountType(models.TextChoices):
        FIXED = "Fixed", "Fixed Amount"
        PERCENTAGE = "Percentage", "Percentage"

    class ApplicableTo(models.TextChoices):
        ALL = "All", "All"
        FIRST_INVOICE = "First_Invoice", "First Invoice Only"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    max_discount_cap = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                           help_text="Max discount for Percentage type (leave blank for no cap)")

    # Eligibility constraints
    min_purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    min_quantity = models.PositiveIntegerField(default=1)
    start_date = models.DateField()
    end_date = models.DateField()
    max_usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Global cap; blank = unlimited")
    used_count = models.PositiveIntegerField(default=0)
    max_uses_per_customer = models.PositiveIntegerField(null=True, blank=True)
    applicable_cycles = models.CharField(max_length=20, choices=ApplicableTo.choices, default=ApplicableTo.ALL)

    # Scope restrictions (nullable = applies to all)
    applicable_product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    applicable_plan = models.ForeignKey("subscriptions.Plan", on_delete=models.SET_NULL, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "discounts"
        indexes = [models.Index(fields=["is_active", "start_date", "end_date"])]
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} – {self.name}"

    def is_valid_for_date(self, date=None):
        date = date or timezone.now().date()
        return self.is_active and self.start_date <= date <= self.end_date

    def usage_limit_reached(self):
        return self.max_usage_limit is not None and self.used_count >= self.max_usage_limit

    def customer_usage_count(self, customer):
        return Invoice.objects.filter(
            customer=customer,
            discount=self,
            status__in=["Confirmed", "Partially_Paid", "Paid"],
        ).count()

    def is_eligible(self, subtotal: Decimal, total_quantity: int, customer, subscription=None, invoice_sequence: int = 1):
        """Full eligibility check. Returns (True, None) or (False, reason_string)."""
        if not self.is_valid_for_date():
            return False, "Discount expired or inactive"
        if self.usage_limit_reached():
            return False, "Global usage limit reached"
        if subtotal < self.min_purchase_amount:
            return False, f"Minimum purchase ₹{self.min_purchase_amount} not met"
        if total_quantity < self.min_quantity:
            return False, f"Minimum quantity {self.min_quantity} not met"
        if self.max_uses_per_customer and self.customer_usage_count(customer) >= self.max_uses_per_customer:
            return False, "Per-customer usage limit reached"
        if self.applicable_cycles == self.ApplicableTo.FIRST_INVOICE and invoice_sequence > 1:
            return False, "First-invoice-only discount"
        if subscription and self.applicable_plan and subscription.plan != self.applicable_plan:
            return False, "Plan restriction"
        return True, None

    def calculate_discount_amount(self, subtotal: Decimal) -> Decimal:
        if self.discount_type == self.DiscountType.FIXED:
            return min(self.discount_value, subtotal)
        else:  # Percentage
            amount = subtotal * self.discount_value / 100
            if self.max_discount_cap:
                amount = min(amount, self.max_discount_cap)
            return amount.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Invoice & Invoice Lines
# ---------------------------------------------------------------------------
class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "Draft", "Draft"
        CONFIRMED = "Confirmed", "Confirmed"
        PARTIALLY_PAID = "Partially_Paid", "Partially Paid"
        PAID = "Paid", "Paid"
        OVERDUE = "Overdue", "Overdue"
        CANCELLED = "Cancelled", "Cancelled"

    invoice_number = models.CharField(max_length=30, unique=True)
    subscription = models.ForeignKey(
        "subscriptions.Subscription", on_delete=models.PROTECT, related_name="invoices"
    )
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    discount = models.ForeignKey(Discount, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")

    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    invoice_date = models.DateField()
    due_date = models.DateField()

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    pdf_file_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "billing_period_start", "billing_period_end"],
                condition=~models.Q(status="Cancelled"),
                name="uq_sub_period",
            )
        ]
        indexes = [
            models.Index(fields=["status", "due_date"], name="idx_inv_status_due"),
            models.Index(fields=["customer", "status"]),
        ]
        ordering = ["-invoice_date"]

    def __str__(self):
        return self.invoice_number

    @classmethod
    def generate_number(cls):
        year = timezone.now().year
        last = cls.objects.filter(invoice_number__startswith=f"INV-{year}-").order_by("-id").first()
        seq = 1
        if last:
            try:
                seq = int(last.invoice_number.split("-")[-1]) + 1
            except ValueError:
                seq = cls.objects.count() + 1
        return f"INV-{year}-{seq:05d}"

    @property
    def is_overdue(self):
        return self.status in (self.Status.CONFIRMED, self.Status.PARTIALLY_PAID) and \
               timezone.now().date() > self.due_date

    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0

    @property
    def aging_bucket(self):
        if not self.is_overdue:
            return "Current"
        days = self.days_overdue()
        if days <= 15:
            return "1–15 days"
        elif days <= 30:
            return "16–30 days"
        elif days <= 60:
            return "31–60 days"
        return "60+ days"



class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "invoice_lines"
        indexes = [models.Index(fields=["invoice"])]

    def __str__(self):
        return f"{self.description} x{self.quantity}"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class Payment(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "Success", "Success"
        FAILED = "Failed", "Failed"
        REFUNDED = "Refunded", "Refunded"
        PENDING = "Pending", "Pending"

    class Method(models.TextChoices):
        CASH = "Cash", "Cash"
        BANK_TRANSFER = "Bank_Transfer", "Bank Transfer / NEFT"
        CARD = "Card", "Card"
        UPI = "UPI", "UPI"

    payment_number = models.CharField(max_length=30, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="recorded_payments")

    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    payment_method = models.CharField(max_length=20, choices=Method.choices)
    transaction_reference = models.CharField(max_length=200, blank=True, help_text="UTR / Gateway Ref")
    payment_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments"
        indexes = [
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["payment_date"]),
        ]
        ordering = ["-payment_date"]

    def __str__(self):
        return f"{self.payment_number} – ₹{self.amount}"

    @classmethod
    def generate_number(cls):
        year = timezone.now().year
        last = cls.objects.filter(payment_number__startswith=f"PAY-{year}-").order_by("-id").first()
        seq = 1
        if last:
            try:
                seq = int(last.payment_number.split("-")[-1]) + 1
            except ValueError:
                seq = cls.objects.count() + 1
        return f"PAY-{year}-{seq:05d}"


# ---------------------------------------------------------------------------
# Pre-aggregated Monthly Revenue Snapshots (for sub-2s dashboard)
# ---------------------------------------------------------------------------
class MonthlyRevenueSnapshot(models.Model):
    year_month = models.CharField(max_length=7, unique=True, help_text="Format: YYYY-MM")
    billed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    collected_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_collected = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    discounts_given = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    active_subscriptions_count = models.PositiveIntegerField(default=0)
    overdue_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "monthly_revenue_snapshots"
        ordering = ["-year_month"]

    def __str__(self):
        return self.year_month


# ---------------------------------------------------------------------------
# In-app Notifications
# ---------------------------------------------------------------------------
class Notification(models.Model):
    class EventType(models.TextChoices):
        INVOICE_GENERATED = "invoice_generated", "Invoice Generated"
        PAYMENT_RECEIVED = "payment_received", "Payment Received"
        PAYMENT_FAILED = "payment_failed", "Payment Failed"
        SUBSCRIPTION_ACTIVATED = "subscription_activated", "Subscription Activated"
        SUBSCRIPTION_EXPIRING = "subscription_expiring", "Subscription Expiring"
        INVOICE_OVERDUE = "invoice_overdue", "Invoice Overdue"
        RENEWAL_REMINDER = "renewal_reminder", "Renewal Reminder"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    event_type = models.CharField(max_length=50, choices=EventType.choices)
    subject = models.CharField(max_length=300)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    email_sent_status = models.BooleanField(default=False)
    related_invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        indexes = [models.Index(fields=["user", "is_read", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} – {self.user.email}"
