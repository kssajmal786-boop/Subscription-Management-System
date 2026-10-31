"""reports/urls.py"""
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_dashboard, name='dashboard'),
    path('api/revenue/', views.revenue_data, name='revenue_data'),
    path('aging/', views.aging_report, name='aging'),
    path('products/', views.product_revenue_report, name='product_revenue'),
    path('export/invoices/', views.export_invoices_csv, name='export_invoices'),
    path('export/payments/', views.export_payments_csv, name='export_payments'),
]
