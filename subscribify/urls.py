"""
Subscribify – Root URL Configuration
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("accounts/", include("accounts.urls", namespace="accounts")),
    path("catalog/", include("catalog.urls", namespace="catalog")),
    path("subscriptions/", include("subscriptions.urls", namespace="subscriptions")),
    path("billing/", include("billing.urls", namespace="billing")),
    path("reports/", include("reports.urls", namespace="reports")),
    path("dashboard/", include("accounts.dashboard_urls", namespace="dashboard")),
    # DRF API
    path("api/billing/", include("billing.api_urls", namespace="billing_api")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
