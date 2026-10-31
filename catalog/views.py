"""
catalog/views.py – Product and Variant CRUD (Admin only).
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Product, ProductVariant
from .forms import ProductForm, ProductVariantForm
from accounts.decorators import admin_required, staff_or_admin_required


@login_required
@staff_or_admin_required
def product_list(request):
    products = Product.objects.prefetch_related("variants").order_by("name")
    return render(request, "catalog/product_list.html", {"products": products})


@login_required
@admin_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product created successfully.")
        return redirect("catalog:product_list")
    return render(request, "catalog/product_form.html", {"form": form, "title": "New Product"})


@login_required
@admin_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product updated.")
        return redirect("catalog:product_list")
    return render(request, "catalog/product_form.html", {"form": form, "title": "Edit Product", "product": product})


@login_required
@admin_required
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    status = "activated" if product.is_active else "deactivated"
    messages.success(request, f"Product {status}.")
    return redirect("catalog:product_list")


@login_required
@admin_required
def variant_create(request, product_pk):
    product = get_object_or_404(Product, pk=product_pk)
    form = ProductVariantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)
        variant.product = product
        variant.save()
        messages.success(request, "Variant added.")
        return redirect("catalog:product_list")
    return render(request, "catalog/variant_form.html", {"form": form, "product": product})


@login_required
@admin_required
def variant_edit(request, pk):
    variant = get_object_or_404(ProductVariant, pk=pk)
    form = ProductVariantForm(request.POST or None, instance=variant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Variant updated.")
        return redirect("catalog:product_list")
    return render(request, "catalog/variant_form.html", {"form": form, "product": variant.product, "variant": variant})
