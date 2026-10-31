"""subscriptions/forms.py"""
from django import forms
from decimal import Decimal
from accounts.models import Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from .models import Plan, Subscription, SubscriptionLine

FC = {"class": "form-control"}
FC_SELECT = {"class": "form-select"}


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            "plan_name", "product", "variant", "billing_cycle", "base_price",
            "min_quantity", "default_duration_months", "max_cycles",
            "auto_renew_default", "allow_pause", "max_pause_days",
            "grace_period_days", "is_active",
        ]
        widgets = {
            "plan_name": forms.TextInput(attrs={**FC, "placeholder": "e.g. Software A Enterprise Monthly"}),
            "product": forms.Select(attrs={**FC_SELECT, "id": "plan_product_select"}),
            "variant": forms.Select(attrs={**FC_SELECT, "id": "plan_variant_select"}),
            "billing_cycle": forms.Select(attrs=FC_SELECT),
            "base_price": forms.NumberInput(attrs={**FC, "step": "0.01"}),
            "min_quantity": forms.NumberInput(attrs={**FC, "min": 1}),
            "default_duration_months": forms.NumberInput(attrs={**FC, "min": 1}),
            "max_cycles": forms.NumberInput(attrs={**FC, "placeholder": "Leave empty for unlimited"}),
            "auto_renew_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_pause": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "max_pause_days": forms.NumberInput(attrs={**FC, "min": 1}),
            "grace_period_days": forms.NumberInput(attrs={**FC, "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ["customer", "plan", "quotation_validity_date", "auto_renew", "notes", "applied_discount"]
        widgets = {
            "customer": forms.Select(attrs=FC_SELECT),
            "plan": forms.Select(attrs=FC_SELECT),
            "applied_discount": forms.Select(attrs=FC_SELECT),
            "quotation_validity_date": forms.DateInput(attrs={**FC, "type": "date"}),
            "notes": forms.Textarea(attrs={**FC, "rows": 3}),
        }


SubscriptionLineFormSet = forms.inlineformset_factory(
    Subscription,
    SubscriptionLine,
    fields=["product", "variant", "quantity", "unit_price", "tax_rate"],
    extra=1,
    can_delete=True,
    widgets={
        "product": forms.Select(attrs=FC_SELECT),
        "variant": forms.Select(attrs=FC_SELECT),
        "quantity": forms.NumberInput(attrs=FC),
        "unit_price": forms.NumberInput(attrs=FC),
        "tax_rate": forms.NumberInput(attrs=FC),
    }
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "product_type", "base_sales_price", "cost_price",
            "tax_rate", "hsn_sac_code", "description", "is_active"
        ]
        widgets = {
            "name": forms.TextInput(attrs={**FC, "placeholder": "e.g. Software A"}),
            "product_type": forms.Select(attrs=FC_SELECT),
            "base_sales_price": forms.NumberInput(attrs={**FC, "step": "0.01"}),
            "cost_price": forms.NumberInput(attrs={**FC, "step": "0.01"}),
            "tax_rate": forms.NumberInput(attrs={**FC, "step": "0.01"}),
            "hsn_sac_code": forms.TextInput(attrs={**FC, "placeholder": "e.g. 997331"}),
            "description": forms.Textarea(attrs={**FC, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = [
            "product", "attribute_name", "attribute_value",
            "additional_price", "sku", "is_active"
        ]
        widgets = {
            "product": forms.Select(attrs=FC_SELECT),
            "attribute_name": forms.TextInput(attrs={**FC, "placeholder": "e.g. Edition or Brand"}),
            "attribute_value": forms.TextInput(attrs={**FC, "placeholder": "e.g. Odoo Enterprise"}),
            "additional_price": forms.NumberInput(attrs={**FC, "step": "0.01"}),
            "sku": forms.TextInput(attrs={**FC, "placeholder": "e.g. SOFT-A-ODOO-ENT"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CustomerForm(forms.ModelForm):
    name = forms.CharField(required=False, widget=forms.TextInput(attrs=FC))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs=FC))

    class Meta:
        model = Customer
        fields = [
            "company_name", "phone", "billing_address", "gst_number"
        ]
        widgets = {
            "company_name": forms.TextInput(attrs=FC),
            "phone": forms.TextInput(attrs=FC),
            "billing_address": forms.Textarea(attrs={**FC, "rows": 2}),
            "gst_number": forms.TextInput(attrs=FC),
        }


class PauseSubscriptionForm(forms.Form):
    pause_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={**FC, "type": "date"})
    )
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={**FC, "placeholder": "e.g. Seasonal suspension request"})
    )


class ResumeSubscriptionForm(forms.Form):
    resume_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={**FC, "type": "date"})
    )
