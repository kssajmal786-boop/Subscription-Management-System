"""billing/urls.py"""
from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    # Invoice Center
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf_download, name="invoice_pdf"),
    path("invoices/<int:pk>/email/", views.invoice_send_email, name="invoice_email"),
    path("invoices/<int:pk>/void/", views.invoice_void, name="invoice_void"),
    path("invoices/generate/<int:subscription_pk>/", views.generate_invoice_manual, name="generate_invoice"),
    path("invoices/outstanding/", views.outstanding_invoices, name="outstanding_invoices"),
    path("invoices/overdue/", views.overdue_invoices, name="overdue_invoices"),

    # Discounts
    path("discounts/", views.discount_list, name="discount_list"),
    path("discounts/create/", views.discount_create, name="discount_create"),
    path("discounts/<int:pk>/edit/", views.discount_edit, name="discount_edit"),
    path("discounts/<int:pk>/toggle/", views.discount_toggle, name="discount_toggle"),

    # Payments
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/record/<int:invoice_pk>/", views.record_payment, name="record_payment"),
    path("payments/<int:pk>/receipt/", views.payment_receipt_download, name="payment_receipt"),

    # Customer Portal
    path("portal/", views.customer_portal, name="customer_portal"),
    path("portal/invoices/", views.customer_invoices, name="customer_invoices"),
    path("portal/pay/<int:invoice_pk>/", views.customer_make_payment, name="customer_make_payment"),
    path("portal/invoices/<int:invoice_pk>/pay/", views.customer_make_payment),
    path("portal/notifications/", views.customer_notifications, name="customer_notifications"),


    # Reports & Exports
    path("reports/", views.financial_reports, name="reports"),
    path("reports/invoices/csv/", views.export_invoices_csv, name="export_invoices_csv"),
    path("reports/payments/csv/", views.export_payments_csv, name="export_payments_csv"),
    path("reports/revenue/csv/", views.export_revenue_csv, name="export_revenue_csv"),
    path("reports/financial/pdf/", views.financial_report_pdf, name="financial_report_pdf"),
]

