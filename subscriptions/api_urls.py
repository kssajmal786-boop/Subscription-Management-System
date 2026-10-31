from django.urls import path, include
from rest_framework.routers import DefaultRouter
from subscriptions.views.api_views import (
    CustomerViewSet, ProductViewSet, ProductVariantViewSet,
    PlanViewSet, DiscountViewSet, SubscriptionViewSet
)

router = DefaultRouter()
router.register(r'customers', CustomerViewSet, basename='api-customer')
router.register(r'products', ProductViewSet, basename='api-product')
router.register(r'variants', ProductVariantViewSet, basename='api-variant')
router.register(r'plans', PlanViewSet, basename='api-plan')
router.register(r'discounts', DiscountViewSet, basename='api-discount')
router.register(r'subscriptions', SubscriptionViewSet, basename='api-subscription')

urlpatterns = [
    path('', include(router.urls)),
]
