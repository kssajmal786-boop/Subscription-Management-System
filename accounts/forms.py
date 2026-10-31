"""
accounts/forms.py
Forms for Customer Registration, Authentication, Password Recovery,
Staff Provisioning, and Customer Profile Administration.
"""
from django import forms
from django.contrib.auth import authenticate
from accounts.models import User, Customer, Staff
from accounts.services import PasswordPolicyValidator


class LoginForm(forms.Form):
    """User login form with remember-me capability."""
    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'name@company.com',
            'autocomplete': 'email',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '•••••••••',
            'autocomplete': 'current-password',
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'remember_me'})
    )


class CustomerRegistrationForm(forms.Form):
    """Customer self-registration with password policy and corporate details."""
    name = forms.CharField(
        label='Full Name',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Jane Doe'})
    )
    email = forms.EmailField(
        label='Work Email Address',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'jane@enterprise.com'})
    )
    company_name = forms.CharField(
        label='Company / Entity Name',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Acme Corp'})
    )
    phone = forms.CharField(
        label='Contact Phone',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'})
    )
    gst_number = forms.CharField(
        label='GSTIN / Tax ID',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '27AABCS1429B1Z0'})
    )
    billing_address = forms.CharField(
        label='Registered Billing Address',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Street, Area...'})
    )
    city = forms.CharField(
        label='City',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mumbai'})
    )
    state = forms.CharField(
        label='State',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Maharashtra'})
    )
    pincode = forms.CharField(
        label='PIN / Postal Code',
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '400001'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Min 9 chars, mixed case, number, symbol'})
    )
    confirm_password = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Re-enter password'})
    )

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email

    def clean_password(self):
        pwd = self.cleaned_data['password']
        errors = PasswordPolicyValidator.validate(pwd)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return pwd

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data


class ForgotPasswordForm(forms.Form):
    """Password recovery request form."""
    email = forms.EmailField(
        label='Verified Email Address',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@company.com', 'autofocus': True})
    )


class ResetPasswordForm(forms.Form):
    """New password submission form with policy validation."""
    new_password = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '•••••••••'})
    )
    confirm_password = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '•••••••••'})
    )

    def clean_new_password(self):
        pwd = self.cleaned_data['new_password']
        errors = PasswordPolicyValidator.validate(pwd)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return pwd

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('new_password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data


class ChangePasswordForm(forms.Form):
    """In-portal password change form."""
    current_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    confirm_password = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        cur = self.cleaned_data['current_password']
        if not self.user.check_password(cur):
            raise forms.ValidationError('Current password is incorrect.')
        return cur

    def clean_new_password(self):
        pwd = self.cleaned_data['new_password']
        errors = PasswordPolicyValidator.validate(pwd)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return pwd

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password')
        p2 = cleaned.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned


class ProfileUpdateForm(forms.ModelForm):
    """Basic profile details for all user types."""
    name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['name'].initial = self.instance.name

    def save(self, commit=True):
        user = super().save(commit=False)
        name_val = self.cleaned_data.get('name')
        if name_val:
            user.name = name_val
        if commit:
            user.save()
        return user



class CustomerProfileForm(forms.ModelForm):
    """Corporate customer metadata form."""
    class Meta:
        model = Customer
        fields = ['company_name', 'phone', 'gst_number', 'pan_number', 'billing_address', 'city', 'state', 'pincode']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'gst_number': forms.TextInput(attrs={'class': 'form-control'}),
            'pan_number': forms.TextInput(attrs={'class': 'form-control'}),
            'billing_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
        }


class StaffCreationForm(forms.Form):
    """Admin-only form for provisioning new Staff or Admin accounts."""
    name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    role = forms.ChoiceField(
        choices=[('Staff', 'Operations Staff'), ('Admin', 'Administrator')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    employee_code = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'class': 'form-control'}))
    department = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    designation = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('User with this email already exists.')
        return email

    def clean_employee_code(self):
        code = self.cleaned_data['employee_code'].strip()
        if Staff.objects.filter(employee_code=code).exists():
            raise forms.ValidationError('Employee code is already in use.')
        return code

    def clean_password(self):
        pwd = self.cleaned_data['password']
        errors = PasswordPolicyValidator.validate(pwd)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return pwd


class StaffUpdateForm(forms.ModelForm):
    """Admin form for editing staff profile and departments."""
    name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    role = forms.ChoiceField(
        choices=[('Staff', 'Operations Staff'), ('Admin', 'Administrator')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    is_active = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    class Meta:
        model = Staff
        fields = ['employee_code', 'department', 'designation']
        widgets = {
            'employee_code': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['name'].initial = self.instance.user.name
            self.fields['email'].initial = self.instance.user.email
            self.fields['role'].initial = self.instance.user.role
            self.fields['is_active'].initial = self.instance.user.is_active


class CustomerAdminForm(forms.ModelForm):
    """Staff/Admin form for creating or updating customers."""
    name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    is_active = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to generate temporary password'}))

    class Meta:
        model = Customer
        fields = ['company_name', 'phone', 'gst_number', 'pan_number', 'billing_address', 'city', 'state', 'pincode', 'status']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'gst_number': forms.TextInput(attrs={'class': 'form-control'}),
            'pan_number': forms.TextInput(attrs={'class': 'form-control'}),
            'billing_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'user') and self.instance.user:
            self.fields['name'].initial = self.instance.user.name
            self.fields['email'].initial = self.instance.user.email
            self.fields['is_active'].initial = self.instance.user.is_active


# Compatibility alias
StaffCreateForm = StaffCreationForm

