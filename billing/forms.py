"""billing/forms.py – Discount, Payment, and Invoice filter forms."""
from django import forms
from .models import Discount, Payment, Invoice
from accounts.models import Customer

FC = {"class": "form-control"}
FC_SELECT = {"class": "form-select"}
FC_DATE = {**FC, "type": "date"}


class DiscountForm(forms.ModelForm):
    class Meta:
        model = Discount
        fields = [
            "code", "name", "discount_type", "discount_value", "max_discount_cap",
            "min_purchase_amount", "min_quantity", "start_date", "end_date",
            "max_usage_limit", "max_uses_per_customer", "applicable_cycles",
            "applicable_product", "applicable_plan", "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs=FC),
            "name": forms.TextInput(attrs=FC),
            "discount_type": forms.Select(attrs=FC_SELECT),
            "discount_value": forms.NumberInput(attrs=FC),
            "max_discount_cap": forms.NumberInput(attrs=FC),
            "min_purchase_amount": forms.NumberInput(attrs=FC),
            "min_quantity": forms.NumberInput(attrs=FC),
            "start_date": forms.DateInput(attrs=FC_DATE),
            "end_date": forms.DateInput(attrs=FC_DATE),
            "max_usage_limit": forms.NumberInput(attrs=FC),
            "max_uses_per_customer": forms.NumberInput(attrs=FC),
            "applicable_cycles": forms.Select(attrs=FC_SELECT),
            "applicable_product": forms.Select(attrs=FC_SELECT),
            "applicable_plan": forms.Select(attrs=FC_SELECT),
        }

    def clean_code(self):
        code = self.cleaned_data["code"].upper().strip()
        qs = Discount.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This discount code already exists.")
        return code

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("End date must be after start date.")
        return cleaned


class PaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2,
        min_value="0.01",
        widget=forms.NumberInput(attrs={**FC, "step": "0.01"}),
    )
    payment_method = forms.ChoiceField(
        choices=Payment.Method.choices,
        widget=forms.Select(attrs=FC_SELECT),
    )
    payment_date = forms.DateField(widget=forms.DateInput(attrs=FC_DATE))
    transaction_reference = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={**FC, "placeholder": "UTR / Gateway Reference"}),
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={**FC, "rows": 2}))


class InvoiceFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", "All Statuses")] + Invoice.Status.choices,
        required=False, widget=forms.Select(attrs=FC_SELECT),
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.select_related("user").all(),
        required=False, empty_label="All Customers",
        widget=forms.Select(attrs=FC_SELECT),
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs=FC_DATE))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs=FC_DATE))
    search = forms.CharField(required=False, widget=forms.TextInput(
        attrs={**FC, "placeholder": "Invoice number..."}))


class PaymentFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", "All")] + Payment.Status.choices,
        required=False, widget=forms.Select(attrs=FC_SELECT),
    )
    method = forms.ChoiceField(
        choices=[("", "All Methods")] + Payment.Method.choices,
        required=False, widget=forms.Select(attrs=FC_SELECT),
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs=FC_DATE))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs=FC_DATE))


class DiscountCodeCheckForm(forms.Form):
    code = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={**FC, "placeholder": "Enter discount code"}),
    )
