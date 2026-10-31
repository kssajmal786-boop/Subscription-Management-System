from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from accounts.models import Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from subscriptions.models import (
    Plan, Subscription, SubscriptionLine, SubscriptionHistory
)
from .snapshot_service import SnapshotService


class QuotationService:
    """
    Manages Quotation creation, calculation of subtotals/taxes/discounts,
    sequential number generation, and quotation status transitions.
    """

    @staticmethod
    def generate_number(prefix: str = 'QUO') -> str:
        """
        Generates thread-safe sequential identifiers:
        e.g. QUO-2026-00001 or SUB-2026-00001.
        """
        year = timezone.now().year if timezone.is_aware(timezone.now()) else date.today().year
        # Count existing subscriptions/quotations for this year with this prefix
        count = Subscription.objects.filter(subscription_number__startswith=f"{prefix}-{year}-").count() + 1
        candidate = f"{prefix}-{year}-{count:05d}"
        
        # Guard against collisions
        while Subscription.objects.filter(subscription_number=candidate).exists():
            count += 1
            candidate = f"{prefix}-{year}-{count:05d}"
        return candidate

    @staticmethod
    def calculate_quotation_totals(lines_data: list, discount_code: str = None):
        """
        Computes dynamic quotation breakdown:
        lines_data: list of dicts with keys: product_id, variant_id (optional), quantity, custom_price (optional)
        discount_code: optional promo code
        """
        subtotal = Decimal('0.00')
        total_tax = Decimal('0.00')
        total_quantity = 0
        computed_lines = []

        for item in lines_data:
            product = Product.objects.get(pk=item['product_id'])
            variant = None
            if item.get('variant_id'):
                variant = ProductVariant.objects.get(pk=item['variant_id'])

            catalog_price, tax_rate = SnapshotService.get_effective_price_and_tax(product, variant)
            unit_price = Decimal(str(item.get('custom_price'))) if item.get('custom_price') is not None else catalog_price
            quantity = int(item.get('quantity', 1))
            total_quantity += quantity

            line_sub = (unit_price * quantity).quantize(Decimal('0.01'))
            line_tax = (line_sub * (tax_rate / Decimal('100.00'))).quantize(Decimal('0.01'))
            line_total = (line_sub + line_tax).quantize(Decimal('0.01'))

            subtotal += line_sub
            total_tax += line_tax

            computed_lines.append({
                'product': product,
                'variant': variant,
                'quantity': quantity,
                'unit_price': unit_price,
                'tax_rate': tax_rate,
                'line_subtotal': line_sub,
                'tax_amount': line_tax,
                'line_total': line_total,
            })

        discount_amount = Decimal('0.00')
        applied_discount = None
        discount_error = None

        if discount_code:
            try:
                discount = Discount.objects.get(code__iexact=discount_code.strip())
                if not discount.is_valid_now():
                    discount_error = f"Discount code '{discount_code}' is expired or inactive."
                elif subtotal < discount.min_purchase_amount:
                    discount_error = f"Minimum purchase amount of ₹{discount.min_purchase_amount} required for '{discount_code}'."
                elif total_quantity < discount.min_quantity:
                    discount_error = f"Minimum item quantity of {discount.min_quantity} required for '{discount_code}'."
                else:
                    discount_amount = discount.calculate_discount(subtotal, total_quantity)
                    applied_discount = discount
            except Discount.DoesNotExist:
                discount_error = f"Discount code '{discount_code}' not found."

        grand_total = max(Decimal('0.00'), subtotal - discount_amount) + total_tax

        return {
            'subtotal': subtotal.quantize(Decimal('0.01')),
            'discount_amount': discount_amount.quantize(Decimal('0.01')),
            'total_tax': total_tax.quantize(Decimal('0.01')),
            'grand_total': grand_total.quantize(Decimal('0.01')),
            'lines': computed_lines,
            'applied_discount': applied_discount,
            'discount_error': discount_error,
            'total_quantity': total_quantity,
        }

    @staticmethod
    @transaction.atomic
    def create_quotation(
        customer: Customer,
        plan: Plan,
        lines_data: list,
        validity_days: int = 15,
        discount_code: str = None,
        notes: str = '',
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Drafts a new quotation with line items and price snapshots.
        """
        if not lines_data:
            raise ValueError("Quotation must have at least one line item.")

        calc = QuotationService.calculate_quotation_totals(lines_data, discount_code)

        if calc['total_quantity'] < plan.min_quantity:
            raise ValueError(f"Plan '{plan.plan_name}' requires minimum quantity of {plan.min_quantity}. Given: {calc['total_quantity']}.")

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        validity_date = today + timedelta(days=validity_days)
        quotation_num = QuotationService.generate_number(prefix='QUO')

        subscription = Subscription.objects.create(
            subscription_number=quotation_num,
            quotation_number=quotation_num,
            customer=customer,
            plan=plan,
            applied_discount=calc['applied_discount'],
            discount_amount=calc['discount_amount'],
            quotation_validity_date=validity_date,
            auto_renew=plan.auto_renew_default,
            status=Subscription.Status.DRAFT,
            notes=notes
        )

        for line_item in calc['lines']:
            SnapshotService.create_line_with_snapshot(
                subscription=subscription,
                product=line_item['product'],
                variant=line_item['variant'],
                quantity=line_item['quantity'],
                custom_price=line_item['unit_price'],
                custom_tax_rate=line_item['tax_rate']
            )

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='CREATED_DRAFT',
            old_status='',
            new_status=Subscription.Status.DRAFT,
            description=f"Draft quotation created with total amount ₹{subscription.total_amount}. Valid until {validity_date}.",
            performed_by=user_name
        )

        return subscription

    @staticmethod
    @transaction.atomic
    def send_quotation(subscription_id: int, user_name: str = 'Staff') -> Subscription:
        """
        Transitions quotation from Draft to Quotation Sent.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
        if subscription.status != Subscription.Status.DRAFT:
            raise ValueError(f"Cannot send quotation in '{subscription.status}' status. Must be 'Draft'.")

        if not subscription.lines.exists():
            raise ValueError("Quotation has no line items.")

        old_status = subscription.status
        subscription.status = Subscription.Status.QUOTATION
        subscription.save(update_fields=['status', 'updated_at'])

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='QUOTATION_SENT',
            old_status=old_status,
            new_status=Subscription.Status.QUOTATION,
            description=f"Quotation {subscription.subscription_number} sent to customer ({subscription.customer.email}).",
            performed_by=user_name
        )
        return subscription
