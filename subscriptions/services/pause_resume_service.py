from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from subscriptions.models import Subscription, SubscriptionHistory


class PauseResumeService:
    """
    Implements Pause, Resume, and Date-Shift logic for subscriptions:
    - Pause: Sets paused_at, prevents recurring billing while paused.
    - Resume: Shifts next_billing_date and expiry_date forward by paused_duration_days
              so customers never lose paid days or get billed for pause periods.
    """

    @staticmethod
    @transaction.atomic
    def pause_subscription(
        subscription_id: int,
        pause_date: date = None,
        reason: str = '',
        user_name: str = 'Staff'
    ) -> Subscription:
        """
        Pauses an active subscription.
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        if subscription.status != Subscription.Status.ACTIVE:
            raise ValueError(
                f"Cannot pause subscription in '{subscription.status}' status. "
                f"Only 'Active' subscriptions can be paused."
            )

        if not subscription.plan.allow_pause:
            raise ValueError(f"Plan '{subscription.plan.plan_name}' does not allow pausing.")

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        effective_pause_date = pause_date or today

        old_status = subscription.status
        subscription.status = Subscription.Status.PAUSED
        subscription.paused_at = effective_pause_date
        subscription.save(update_fields=['status', 'paused_at', 'updated_at'])

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='PAUSED',
            old_status=old_status,
            new_status=Subscription.Status.PAUSED,
            description=(
                f"Subscription paused on {effective_pause_date}. "
                f"Billing halted. Reason: {reason or 'Customer request'}."
            ),
            performed_by=user_name
        )
        return subscription

    @staticmethod
    @transaction.atomic
    def resume_subscription(
        subscription_id: int,
        resume_date: date = None,
        user_name: str = 'Staff'
    ) -> dict:
        """
        Resumes a paused subscription and calculates the date-shift math:
        delta_pause = resume_date - paused_at (in days)
        next_billing_date = next_billing_date + delta_pause
        expiry_date = expiry_date + delta_pause
        total_paused_days += delta_pause
        paused_at = None
        status = Active
        """
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        if subscription.status != Subscription.Status.PAUSED:
            raise ValueError(
                f"Cannot resume subscription in '{subscription.status}' status. "
                f"Only 'Paused' subscriptions can be resumed."
            )

        if not subscription.paused_at:
            raise ValueError("Subscription is paused but has no paused_at timestamp recorded.")

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()
        effective_resume_date = resume_date or today

        if effective_resume_date < subscription.paused_at:
            raise ValueError(
                f"Resume date ({effective_resume_date}) cannot be earlier than "
                f"pause date ({subscription.paused_at})."
            )

        paused_days = (effective_resume_date - subscription.paused_at).days
        paused_delta = timedelta(days=paused_days)

        old_next_billing = subscription.next_billing_date
        old_expiry = subscription.expiry_date

        # Shift dates forward by paused_days
        new_next_billing = old_next_billing + paused_delta if old_next_billing else None
        new_expiry = old_expiry + paused_delta if old_expiry else None

        subscription.next_billing_date = new_next_billing
        subscription.expiry_date = new_expiry
        subscription.total_paused_days += paused_days
        subscription.paused_at = None
        subscription.status = Subscription.Status.ACTIVE
        subscription.save(update_fields=[
            'status', 'next_billing_date', 'expiry_date',
            'total_paused_days', 'paused_at', 'updated_at'
        ])

        audit_msg = (
            f"Subscription resumed on {effective_resume_date} after {paused_days} days on pause. "
            f"Next Billing shifted from {old_next_billing} to {new_next_billing}. "
            f"Contract Expiry shifted from {old_expiry} to {new_expiry}."
        )

        SubscriptionHistory.objects.create(
            subscription=subscription,
            action='RESUMED',
            old_status=Subscription.Status.PAUSED,
            new_status=Subscription.Status.ACTIVE,
            description=audit_msg,
            performed_by=user_name
        )

        return {
            'subscription': subscription,
            'paused_days': paused_days,
            'old_next_billing_date': old_next_billing,
            'new_next_billing_date': new_next_billing,
            'old_expiry_date': old_expiry,
            'new_expiry_date': new_expiry,
            'total_paused_days': subscription.total_paused_days,
        }
