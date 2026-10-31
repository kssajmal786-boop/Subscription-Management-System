from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from billing.models import Discount
from subscriptions.models import (
    Subscription, SubscriptionLine, SubscriptionHistory, Plan
)
from .snapshot_service import SnapshotService
from .quotation_service import QuotationService


class LifecycleService:
    """
    Orchestrates the unified quote-to-subscription lifecycle:
    Draft -> Quotation -> Confirmed -> Active -> Paused / Past Due -> Closed / Cancelled.
    Enforces atomic database transactions with row-level locks (SELECT ... FOR UPDATE).
    """

    @staticmethod
    def calculate_cycle_delta(billing_cycle: str, duration_cycles: int = 1) -> timedelta:
        """
        Calculates timedelta for a given billing cycle and cycle count.
        """
        if billing_cycle == Plan.BillingCycle.DAILY:
            return timedelta(days=1 * duration_cycles)
        elif billing_cycle == Plan.BillingCycle.WEEKLY:
            return timedelta(weeks=1 * duration_cycles)
        elif billing_cycle == Plan.BillingCycle.MONTHLY:
            return timedelta(days=30 * duration_cycles)
        elif billing_cycle == Plan.BillingCycle.QUARTERLY:
            return timedelta(days=90 * duration_cycles)
        elif billing_cycle == Plan.BillingCycle.YEARLY:
            return timedelta(days=365 * duration_cycles)
        return timedelta(days=30 * duration_cycles)

    @staticmethod
    @transaction.atomic
    def confirm_quotation(
        subscription_id: int,
        start_date: date = None,
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Converts an accepted quotation into a Confirmed Subscription.
        1. Row-level locks the subscription row.
        2. Upgrades sequence identifier from QUO-... to SUB-....
        3. Freezes price snapshots on all lines.
        4. Calculates start_date, next_billing_date, and initial expiry_date.
        5. Atomically increments discount usage count.
        6. Creates comprehensive audit trail.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        if subscription.status not in [Subscription.Status.DRAFT, Subscription.Status.QUOTATION]:
            raise ValueError(
                f"Cannot confirm subscription in '{subscription.status}' status. "
                f"Must be 'Draft' or 'Quotation'."
            )

        if not subscription.lines.exists():
            raise ValueError("Cannot confirm quotation with no line items.")

        old_status = subscription.status
        old_number = subscription.subscription_number

        # 1. Upgrade sequence number to SUB-YYYY-XXXXX while preserving quotation reference
        sub_number = QuotationService.generate_number(prefix='SUB')
        subscription.quotation_number = old_number
        subscription.subscription_number = sub_number

        # 2. Set commencement and billing dates
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        effective_start = start_date or today
        subscription.start_date = effective_start
        subscription.next_billing_date = effective_start

        # Calculate contract expiration based on default plan duration
        duration = subscription.plan.default_duration or 1
        delta = LifecycleService.calculate_cycle_delta(subscription.plan.billing_cycle, duration)
        subscription.expiry_date = effective_start + delta

        # 3. Freeze snapshot prices on all lines
        SnapshotService.verify_and_lock_snapshots(subscription)

        # 4. If discount applied, atomically increment usage count
        if subscription.applied_discount:
            Discount.objects.filter(pk=subscription.applied_discount_id).update(
                used_count=F('used_count') + 1
            )

        # 5. Transition status to Confirmed
        subscription.status = Subscription.Status.CONFIRMED
        subscription.save()

        # 6. Audit Trail
        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='QUOTATION_CONFIRMED',
            old_status=old_status,
            new_status=Subscription.Status.CONFIRMED,
            description=(
                f"Quotation {old_number} accepted & confirmed as Subscription {sub_number}. "
                f"Start Date: {effective_start}, Next Billing: {effective_start}, "
                f"Contract Expiry: {subscription.expiry_date}."
            ),
            performed_by=user_name
        )

        return subscription

    @staticmethod
    @transaction.atomic
    def activate_subscription(
        subscription_id: int,
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Activates a confirmed subscription into recurring billing state.
        Triggered when payment is received or contract is officially activated.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        if subscription.status != Subscription.Status.CONFIRMED:
            raise ValueError(
                f"Cannot activate subscription in '{subscription.status}' status. "
                f"Must be 'Confirmed'."
            )

        old_status = subscription.status
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()

        if not subscription.start_date:
            subscription.start_date = today
        if not subscription.next_billing_date:
            subscription.next_billing_date = subscription.start_date

        subscription.status = Subscription.Status.ACTIVE
        subscription.save(update_fields=['status', 'start_date', 'next_billing_date', 'updated_at'])

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='ACTIVATED',
            old_status=old_status,
            new_status=Subscription.Status.ACTIVE,
            description=f"Subscription activated. Active recurring billing active as of {subscription.start_date}.",
            performed_by=user_name
        )

        return subscription

    @staticmethod
    @transaction.atomic
    def cancel_subscription(
        subscription_id: int,
        reason: str = '',
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Cancels a quotation or active subscription.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        if subscription.status in [Subscription.Status.CLOSED, Subscription.Status.CANCELLED]:
            raise ValueError(f"Subscription is already {subscription.status}.")

        old_status = subscription.status
        subscription.status = Subscription.Status.CANCELLED
        subscription.save(update_fields=['status', 'updated_at'])

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='CANCELLED',
            old_status=old_status,
            new_status=Subscription.Status.CANCELLED,
            description=f"Subscription cancelled. Reason: {reason or 'No reason provided'}.",
            performed_by=user_name
        )
        return subscription

    @staticmethod
    @transaction.atomic
    def close_subscription(
        subscription_id: int,
        reason: str = '',
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Closes an expired or completed subscription that does not auto-renew.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
        old_status = subscription.status
        subscription.status = Subscription.Status.CLOSED
        subscription.save(update_fields=['status', 'updated_at'])

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='CLOSED',
            old_status=old_status,
            new_status=Subscription.Status.CLOSED,
            description=f"Subscription closed/completed. Notes: {reason or 'Term finished'}.",
            performed_by=user_name
        )
        return subscription
