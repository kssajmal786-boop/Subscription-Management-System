"""
accounts/serializers.py
Django REST Framework serializers for Authentication, Customer lifecycle,
Staff provisioning, and Security Audit trail.
"""
from rest_framework import serializers
from accounts.models import User, Customer, Staff, UserAuditLog
from accounts.services import PasswordPolicyValidator


class UserSerializer(serializers.ModelSerializer):
    """Public serialization of user accounts."""
    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'role', 'is_active',
            'email_verified', 'created_at', 'last_login_ip'
        ]
        read_only_fields = ['id', 'role', 'email_verified', 'created_at', 'last_login_ip']


class CustomerSerializer(serializers.ModelSerializer):
    """Nested serializer for full customer data."""
    user = UserSerializer(read_only=True)
    outstanding_balance = serializers.SerializerMethodField()
    active_subscriptions_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'user', 'company_name', 'billing_address', 'phone',
            'gst_number', 'pan_number', 'city', 'state', 'pincode',
            'status', 'created_at', 'updated_at',
            'outstanding_balance', 'active_subscriptions_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_outstanding_balance(self, obj):
        return float(obj.get_outstanding_balance())

    def get_active_subscriptions_count(self, obj):
        return obj.get_active_subscriptions_count()


class CustomerRegistrationSerializer(serializers.Serializer):
    """Customer self-registration payload."""
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    company_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    gst_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    billing_address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('Email already registered.')
        return email

    def validate_password(self, value):
        errors = PasswordPolicyValidator.validate(value)
        if errors:
            raise serializers.ValidationError(' '.join(errors))
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class CustomerCreateUpdateSerializer(serializers.Serializer):
    """Staff/Admin customer creation & update payload."""
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    gst_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    pan_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    billing_address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False, default=True)
    status = serializers.ChoiceField(choices=Customer.STATUS_CHOICES, required=False, default='Active')


class StaffSerializer(serializers.ModelSerializer):
    """Staff member serialization."""
    user = UserSerializer(read_only=True)

    class Meta:
        model = Staff
        fields = [
            'id', 'user', 'employee_code', 'department',
            'designation', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class StaffCreateSerializer(serializers.Serializer):
    """Admin staff creation payload."""
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=['Staff', 'Admin'], default='Staff')
    employee_code = serializers.CharField(max_length=30)
    department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    designation = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('Email already in use.')
        return email

    def validate_employee_code(self, value):
        code = value.strip()
        if Staff.objects.filter(employee_code=code).exists():
            raise serializers.ValidationError('Employee code already exists.')
        return code

    def validate_password(self, value):
        errors = PasswordPolicyValidator.validate(value)
        if errors:
            raise serializers.ValidationError(' '.join(errors))
        return value


class StaffUpdateSerializer(serializers.Serializer):
    """Admin staff update payload."""
    name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    role = serializers.ChoiceField(choices=['Staff', 'Admin'], required=False)
    employee_code = serializers.CharField(max_length=30, required=False)
    department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    designation = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


class LoginSerializer(serializers.Serializer):
    """Login credentials payload."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(required=False, default=False)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        errors = PasswordPolicyValidator.validate(attrs['new_password'])
        if errors:
            raise serializers.ValidationError({'new_password': ' '.join(errors)})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        errors = PasswordPolicyValidator.validate(attrs['new_password'])
        if errors:
            raise serializers.ValidationError({'new_password': ' '.join(errors)})
        return attrs


class UserAuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.ReadOnlyField(source='actor.email')
    user_email = serializers.ReadOnlyField(source='user.email')

    class Meta:
        model = UserAuditLog
        fields = ['id', 'action', 'user_email', 'actor_email', 'ip_address', 'details', 'timestamp']
