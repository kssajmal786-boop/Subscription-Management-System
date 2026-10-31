"""
accounts/urls.py
Comprehensive URL Routing for Accounts Web Controllers and REST API.
"""
from django.urls import path, include
from accounts import views

app_name = 'accounts'

urlpatterns = [
    # ── Authentication ──
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('verification-sent/', views.verification_sent_view, name='verification_sent'),
    path('verify-email/<str:token>/', views.verify_email_view, name='verify_email'),
    path('resend-verification/', views.resend_verification_view, name='resend_verification'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/<str:token>/', views.reset_password_view, name='reset_password'),
    path('profile/', views.profile_view, name='profile'),
    path('change-password/', views.change_password_view, name='change_password'),

    # ── Customer Management (Staff / Admin) ──
    path('customers/', views.customer_list_view, name='customer_list'),
    path('customers/create/', views.customer_create_view, name='customer_create'),
    path('customers/<int:pk>/', views.customer_detail_view, name='customer_detail'),
    path('customers/<int:pk>/edit/', views.customer_edit_view, name='customer_edit'),
    path('customers/<int:pk>/toggle-active/', views.customer_toggle_active_view, name='customer_toggle_active'),

    # ── Staff Management (Admin Only) ──
    path('staff/', views.staff_list_view, name='staff_list'),
    path('staff/create/', views.staff_create_view, name='staff_create'),
    path('staff/<int:pk>/edit/', views.staff_edit_view, name='staff_edit'),
    path('staff/<int:pk>/toggle-active/', views.staff_toggle_active_view, name='staff_toggle_active'),

    # ── System User Management (Admin Only) ──
    path('users/', views.user_management_view, name='user_management'),
    path('users/<int:user_id>/toggle-active/', views.user_toggle_active_view, name='user_toggle_active'),

    # ── Notifications ──
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),

    # ── REST API ──
    path('api/', include('accounts.api_urls', namespace='api')),
]
