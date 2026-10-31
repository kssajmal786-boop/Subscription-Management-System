"""catalog/forms.py"""
from django import forms
from .models import Product, ProductVariant

FIELD_CLASS = {"class": "form-control"}


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "product_type", "base_sales_price", "cost_price",
                  "tax_rate", "hsn_sac_code", "description"]
        widgets = {f: forms.TextInput(attrs=FIELD_CLASS) for f in
                   ["name", "hsn_sac_code"]}
        widgets.update({
            "product_type": forms.Select(attrs=FIELD_CLASS),
            "base_sales_price": forms.NumberInput(attrs=FIELD_CLASS),
            "cost_price": forms.NumberInput(attrs=FIELD_CLASS),
            "tax_rate": forms.NumberInput(attrs=FIELD_CLASS),
            "description": forms.Textarea(attrs={**FIELD_CLASS, "rows": 3}),
        })


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ["attribute_name", "attribute_value", "additional_price", "sku"]
        widgets = {
            "attribute_name": forms.TextInput(attrs=FIELD_CLASS),
            "attribute_value": forms.TextInput(attrs=FIELD_CLASS),
            "additional_price": forms.NumberInput(attrs=FIELD_CLASS),
            "sku": forms.TextInput(attrs=FIELD_CLASS),
        }
