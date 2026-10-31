"""
accounts/models.py – Custom User model + Customer and Staff profiles.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        name = extra_fields.pop("name", None)
        if name:
            parts = name.strip().split(" ", 1)
            extra_fields.setdefault("first_name", parts[0])
            extra_fields.setdefault("last_name", parts[1] if len(parts) > 1 else "")
        extra_fields.setdefault("first_name", "")
        extra_fields.setdefault("last_name", "")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "Admin", "Admin"
        STAFF = "Staff", "Staff"
        CUSTOMER = "Customer", "Customer"

    ROLE_CHOICES = Role.choices

    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def name(self):
        return self.get_full_name()

    @name.setter
    def name(self, val):
        parts = (val or "").strip().split(" ", 1)
        self.first_name = parts[0]
        self.last_name = parts[1] if len(parts) > 1 else ""

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    @property
    def is_staff_member(self):
        return self.role == self.Role.STAFF

    @property
    def created_at(self):
        return self.date_joined

    def is_locked(self):
        if self.locked_until and timezone.now() < self.locked_until:
            return True
        return False

    def record_failed_login(self, max_attempts=5, lockout_minutes=15):
        from datetime import timedelta
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = timezone.now() + timedelta(minutes=lockout_minutes)
        self.save(update_fields=["failed_login_attempts", "locked_until"])

    def reset_failed_logins(self):
        if self.failed_login_attempts > 0 or self.locked_until is not None:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_login_attempts", "locked_until"])


class Customer(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
        ("Pending_Verification", "Pending Verification"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_profile")
    company_name = models.CharField(max_length=200, blank=True)
    billing_address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    gst_number = models.CharField(max_length=20, blank=True, verbose_name="GSTIN")
    pan_number = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customers"
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def __str__(self):
        return self.company_name or self.user.get_full_name()

    @property
    def display_name(self):
        return self.company_name or self.user.get_full_name()

    @property
    def name(self):
        return self.user.get_full_name()

    @property
    def email(self):
        return self.user.email

    def get_outstanding_balance(self):
        try:
            from billing.models import Invoice
            from django.db.models import Sum
            from decimal import Decimal
            res = Invoice.objects.filter(
                customer=self,
                status__in=["Confirmed", "Partially_Paid", "Overdue"]
            ).aggregate(total=Sum("balance_due"))
            return res["total"] or Decimal("0.00")
        except Exception:
            from decimal import Decimal
            return Decimal("0.00")

    def get_active_subscriptions_count(self):
        try:
            from subscriptions.models import Subscription
            return Subscription.objects.filter(customer=self, status="Active").count()
        except Exception:
            return 0



class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    employee_code = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=100, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "staff"
        verbose_name = "Staff"
        verbose_name_plural = "Staff"

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_code})"


Staff = StaffProfile  # Compatibility alias for code referencing Staff


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_tokens")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "password_reset_tokens"

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    @classmethod
    def generate_for_user(cls, user, expires_hours=2):
        import secrets
        from datetime import timedelta
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(hours=expires_hours),
        )


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_verify_tokens")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "email_verification_tokens"

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    @classmethod
    def generate_for_user(cls, user, expires_hours=48):
        import secrets
        from datetime import timedelta
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(hours=expires_hours),
        )


class UserAuditLog(models.Model):
    ACTION_CHOICES = [
        ("LOGIN_SUCCESS", "Successful Login"),
        ("LOGIN_FAILED", "Failed Login Attempt"),
        ("ACCOUNT_LOCKED", "Account Locked"),
        ("LOGOUT", "User Logout"),
        ("REGISTER", "User Registration"),
        ("EMAIL_VERIFIED", "Email Verified"),
        ("PASSWORD_RESET_REQ", "Password Reset Requested"),
        ("PASSWORD_RESET_DONE", "Password Reset Completed"),
        ("STATUS_TOGGLED", "Account Active Status Changed"),
        ("STAFF_CREATED", "Staff Account Created"),
        ("CUSTOMER_CREATED", "Customer Account Created"),
        ("PERMISSION_DENIED", "Unauthorized Access Attempt"),
    ]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="actor_audit_logs")
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "user_audit_logs"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.action} on {self.user}"
