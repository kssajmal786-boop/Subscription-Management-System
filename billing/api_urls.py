"""billing/api_urls.py – DRF router for billing API."""
from rest_framework.routers import DefaultRouter
from . import api_views

app_name = "billing_api"

router = DefaultRouter()
router.register("invoices", api_views.InvoiceViewSet, basename="invoice")
router.register("payments", api_views.PaymentViewSet, basename="payment")
router.register("discounts", api_views.DiscountViewSet, basename="discount")
router.register("snapshots", api_views.MonthlySnapshotViewSet, basename="snapshot")

urlpatterns = router.urls
