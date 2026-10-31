"""
billing/api_views.py – DRF API ViewSets for billing resources.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Invoice, Payment, Discount, MonthlyRevenueSnapshot
from .serializers import (
    InvoiceSerializer, PaymentSerializer,
    DiscountSerializer, MonthlySnapshotSerializer
)
from .services import BillingService


class IsAdminOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ("Admin", "Staff")


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "Admin"


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/billing/invoices/          – List invoices (Admin/Staff)
    GET /api/billing/invoices/{id}/     – Invoice detail
    POST /api/billing/invoices/{id}/generate_pdf/ – Regenerate PDF
    """
    serializer_class = InvoiceSerializer
    permission_classes = [IsAdminOrStaff]

    def get_queryset(self):
        qs = Invoice.objects.select_related(
            "customer__user", "subscription__plan", "discount"
        ).prefetch_related("lines__product", "lines__variant")

        # Allow customers to see only their invoices
        if self.request.user.role == "Customer":
            qs = qs.filter(customer__user=self.request.user)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by("-invoice_date")

    @action(detail=True, methods=["post"])
    def generate_pdf(self, request, pk=None):
        invoice = self.get_object()
        from .tasks import generate_invoice_pdf_task
        generate_invoice_pdf_task.delay(invoice.pk)
        return Response({"message": "PDF generation queued", "invoice": invoice.invoice_number})

    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrStaff])
    def record_payment(self, request, pk=None):
        invoice = self.get_object()
        amount = request.data.get("amount")
        method = request.data.get("payment_method", "Bank_Transfer")
        reference = request.data.get("transaction_reference", "")
        notes = request.data.get("notes", "")

        if not amount:
            return Response({"error": "amount is required"}, status=400)

        try:
            payment = BillingService.record_payment(
                invoice_id=invoice.pk,
                amount=amount,
                payment_method=method,
                payment_date=timezone.now().date(),
                recorded_by=request.user,
                transaction_reference=reference,
                notes=notes,
            )
            return Response(PaymentSerializer(payment).data, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/billing/payments/      – List payments
    GET /api/billing/payments/{id}/ – Payment detail
    """
    serializer_class = PaymentSerializer
    permission_classes = [IsAdminOrStaff]

    def get_queryset(self):
        qs = Payment.objects.select_related("invoice", "customer__user", "recorded_by")
        if self.request.user.role == "Customer":
            qs = qs.filter(customer__user=self.request.user)
        return qs.order_by("-payment_date")


class DiscountViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for discounts (Admin only).
    GET /api/billing/discounts/
    POST /api/billing/discounts/
    GET /api/billing/discounts/{id}/
    PUT/PATCH /api/billing/discounts/{id}/
    DELETE /api/billing/discounts/{id}/
    POST /api/billing/discounts/validate/ – Check discount eligibility
    """
    serializer_class = DiscountSerializer
    permission_classes = [IsAdmin]
    queryset = Discount.objects.all().order_by("-created_at")

    @action(detail=False, methods=["post"], permission_classes=[IsAdminOrStaff])
    def validate(self, request):
        """Validate a discount code against given subtotal and quantity."""
        from decimal import Decimal
        code = request.data.get("code", "")
        subtotal = Decimal(str(request.data.get("subtotal", "0")))
        quantity = int(request.data.get("quantity", 1))

        discount, amount, error = BillingService.validate_discount_code(
            code=code, subtotal=subtotal,
            total_quantity=quantity, customer=None,
        )
        if error:
            return Response({"valid": False, "error": error})
        return Response({
            "valid": True,
            "discount_code": discount.code,
            "discount_name": discount.name,
            "discount_type": discount.discount_type,
            "discount_amount": float(amount),
        })


class MonthlySnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/billing/snapshots/ – Monthly revenue data for charts
    """
    serializer_class = MonthlySnapshotSerializer
    permission_classes = [IsAdmin]
    queryset = MonthlyRevenueSnapshot.objects.order_by("-year_month")[:24]
