"""subscriptions/forms.py"""
from django import forms
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
            "plan_name": forms.TextInput(attrs=FC),
            "product": forms.Select(attrs=FC_SELECT),
            "variant": forms.Select(attrs=FC_SELECT),
            "billing_cycle": forms.Select(attrs=FC_SELECT),
            "base_price": forms.NumberInput(attrs=FC),
            "min_quantity": forms.NumberInput(attrs=FC),
            "default_duration_months": forms.NumberInput(attrs=FC),
            "max_cycles": forms.NumberInput(attrs=FC),
            "max_pause_days": forms.NumberInput(attrs=FC),
            "grace_period_days": forms.NumberInput(attrs=FC),
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
