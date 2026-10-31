"""
accounts/api_urls.py
API URL Routing for Authentication, Customer, Staff, and User management.
"""
from django.urls import path
from accounts import api_views

app_name = 'accounts_api'

urlpatterns = [
    # Auth Endpoints
    path('auth/register/', api_views.RegisterAPIView.as_view(), name='api_register'),
    path('auth/login/', api_views.LoginAPIView.as_view(), name='api_login'),
    path('auth/logout/', api_views.LogoutAPIView.as_view(), name='api_logout'),
    path('auth/me/', api_views.MeAPIView.as_view(), name='api_me'),
    path('auth/forgot-password/', api_views.ForgotPasswordAPIView.as_view(), name='api_forgot_password'),
    path('auth/reset-password/', api_views.ResetPasswordAPIView.as_view(), name='api_reset_password'),
    path('auth/verify-email/', api_views.VerifyEmailAPIView.as_view(), name='api_verify_email'),
    path('auth/change-password/', api_views.ChangePasswordAPIView.as_view(), name='api_change_password'),

    # Customer Management
    path('customers/', api_views.CustomerListCreateAPIView.as_view(), name='api_customer_list_create'),
    path('customers/<int:pk>/', api_views.CustomerDetailAPIView.as_view(), name='api_customer_detail'),
    path('customers/<int:pk>/toggle-active/', api_views.CustomerToggleActiveAPIView.as_view(), name='api_customer_toggle_active'),

    # Staff Management (Admin only)
    path('staff/', api_views.StaffListCreateAPIView.as_view(), name='api_staff_list_create'),
    path('staff/<int:pk>/', api_views.StaffDetailAPIView.as_view(), name='api_staff_detail'),
    path('staff/<int:pk>/toggle-active/', api_views.StaffToggleActiveAPIView.as_view(), name='api_staff_toggle_active'),

    # System User Management (Admin only)
    path('users/', api_views.UserListAPIView.as_view(), name='api_user_list'),
    path('users/<int:pk>/toggle-active/', api_views.UserToggleActiveAPIView.as_view(), name='api_user_toggle_active'),
    path('audit-logs/', api_views.AuditLogListAPIView.as_view(), name='api_audit_logs'),
]
