"""accounts/dashboard_urls.py – Root dashboard routing"""
from django.urls import path
from accounts.dashboard_views import (
    dashboard_redirect, admin_dashboard, staff_dashboard, customer_dashboard
)

app_name = "dashboard"

urlpatterns = [
    path("", dashboard_redirect, name="index"),
    path("home/", dashboard_redirect, name="home"),
    path("dashboard/", dashboard_redirect, name="redirect"),
    path("admin-dashboard/", admin_dashboard, name="admin"),
    path("staff-dashboard/", staff_dashboard, name="staff"),
    path("customer-dashboard/", customer_dashboard, name="customer"),
]
