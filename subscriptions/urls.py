"""subscriptions/urls.py – Unified Subscriptions, Quotations, Plans & Catalog routing"""
from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    # Dashboard
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),

    # 1. Product Catalog & Variants (CBVs)
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_update"),
    path("products/<int:pk>/archive/", views.ProductArchiveToggleView.as_view(), name="product_archive_toggle"),
    path("products/<int:product_id>/variants/new/", views.VariantCreateView.as_view(), name="variant_create"),
    path("variants/<int:pk>/edit/", views.VariantUpdateView.as_view(), name="variant_update"),
    path("variants/<int:pk>/toggle/", views.VariantToggleView.as_view(), name="variant_toggle"),

    # 2. Subscription Plans
    path("plans/", views.plan_list, name="plan_list"),
    path("plans/create/", views.plan_create, name="plan_create"),
    path("plans/new/", views.PlanCreateView.as_view(), name="plan_new"),
    path("plans/<int:pk>/", views.PlanDetailView.as_view(), name="plan_detail"),
    path("plans/<int:pk>/edit/", views.PlanUpdateView.as_view(), name="plan_update"),
    path("plans/<int:pk>/form-edit/", views.plan_edit, name="plan_edit"),

    # 3. Quotation Builder & Tracker
    path("quotations/builder/", views.QuotationBuilderView.as_view(), name="quotation_builder"),
    path("quotations/", views.QuotationTrackerView.as_view(), name="quotation_tracker"),
    path("quotations/<int:pk>/", views.QuotationDetailView.as_view(), name="quotation_detail"),
    path("quotations/<int:pk>/send/", views.QuotationSendActionView.as_view(), name="quotation_send"),
    path("quotations/<int:pk>/confirm/", views.QuotationConfirmActionView.as_view(), name="quotation_confirm"),
    path("quotations/<int:pk>/reject/", views.QuotationRejectActionView.as_view(), name="quotation_reject"),

    # 4. Subscriptions – primary & aliases
    path("", views.subscription_list, name="subscription_list"),
    path("all/", views.SubscriptionListView.as_view(), name="subscription_all"),
    path("list/", views.subscription_list, name="list"),
    path("create/", views.subscription_create, name="subscription_create"),
    path("new/", views.subscription_create, name="create"),
    path("<int:pk>/", views.subscription_detail, name="subscription_detail"),
    path("<int:pk>/detail/", views.subscription_detail, name="detail"),
    path("<int:pk>/view/", views.SubscriptionDetailView.as_view(), name="subscription_view"),
    path("<int:pk>/confirm/", views.subscription_confirm, name="subscription_confirm"),
    path("<int:pk>/confirm-action/", views.subscription_confirm, name="confirm"),
    path("<int:pk>/activate/", views.subscription_confirm, name="activate"),
    path("<int:pk>/pause/", views.subscription_pause, name="subscription_pause"),
    path("<int:pk>/pause-action/", views.SubscriptionPauseActionView.as_view(), name="pause_action"),
    path("<int:pk>/pause-toggle/", views.subscription_pause, name="pause"),
    path("<int:pk>/resume/", views.subscription_resume, name="subscription_resume"),
    path("<int:pk>/resume-action/", views.SubscriptionResumeActionView.as_view(), name="resume_action"),
    path("<int:pk>/resume-toggle/", views.subscription_resume, name="resume"),
    path("<int:pk>/cancel/", views.SubscriptionCancelActionView.as_view(), name="subscription_cancel"),
    path("<int:pk>/close/", views.subscription_close, name="subscription_close"),
    path("<int:pk>/close-action/", views.subscription_close, name="close"),
    path("<int:pk>/renew/", views.subscription_renew, name="subscription_renew"),
    path("<int:pk>/renew-action/", views.subscription_renew, name="renew"),
    path("<int:pk>/accept/", views.quotation_accept_customer, name="quotation_accept"),
    path("<int:pk>/accept-action/", views.quotation_accept_customer, name="accept"),
    path("<int:pk>/toggle-autorenew/", views.subscription_toggle_autorenew, name="toggle_autorenew"),
]
