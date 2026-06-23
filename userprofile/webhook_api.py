import hmac
import hashlib
import json
import logging
import requests
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import VendorProfile
from .auth_api import SUBSCRIPTION_RENEWAL_DAYS

logger = logging.getLogger(__name__)


@csrf_exempt
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        return HttpResponse(status=400)

    payload = request.body
    computed_hash = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), payload, hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, signature):
        logger.warning("Invalid Paystack signature")
        return HttpResponse(status=403)

    try:
        event_data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Webhook JSON error: {e}")
        return HttpResponse(status=400)

    event = event_data.get("event")
    data = event_data.get("data", {})

    # Handle successful payments
    if event in ["charge.success", "invoice.payment_success"]:
        return handle_successful_payment(data)

    # Handle failed payments
    elif event in ["charge.failed", "invoice.payment_failed"]:
        return handle_failed_payment(data)

    # Handle subscription events
    elif event == "subscription.create":
        return handle_subscription_created(data)

    elif event == "subscription.disable":
        return handle_subscription_disabled(data)

    # Log unhandled events
    else:
        logger.info(f"Unhandled webhook event: {event}")
        return HttpResponse(status=200)


def handle_successful_payment(data):
    """Handle successful payment webhook for both subscriptions and plan changes"""
    from .models import SubscriptionHistory

    reference = data.get("reference")
    subscription_code = data.get("subscription")
    amount = data.get("amount", 0) / 100  # Convert from kobo to naira
    metadata = data.get("metadata", {})

    if not reference:
        logger.warning("Missing reference in successful payment webhook.")
        return HttpResponse(status=400)

    try:
        vendor = VendorProfile.objects.get(pending_ref=reference)
    except VendorProfile.DoesNotExist:
        logger.warning(f"No vendor with ref: {reference}")
        return HttpResponse(status=404)

    now = timezone.now()

    # Check if this is a plan change payment
    if metadata.get("type") == "plan_change":
        return handle_plan_change_payment(vendor, data, metadata, amount, reference)

    # Handle regular subscription payment
    # Check if subscription is already active and newer
    if vendor.subscription_expiry and vendor.subscription_expiry > now:
        logger.info(f"Subscription for vendor {vendor.id} already active, skipping.")
        return HttpResponse(status=200)

    # Update vendor subscription
    old_status = vendor.subscription_status
    vendor.paystack_subscription_code = (
        subscription_code or vendor.paystack_subscription_code
    )
    vendor.subscription_status = "active"
    vendor.subscription_expiry = now + timedelta(days=SUBSCRIPTION_RENEWAL_DAYS)
    vendor.last_payment_date = now
    vendor.failed_payment_count = 0  # Reset failed payment count
    vendor.pending_ref = None
    vendor.save()

    # Log the payment success
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="payment_success",
        previous_status=old_status,
        new_status="active",
        amount=amount,
        payment_reference=reference,
        paystack_response=data,
        notes=f"Payment successful, subscription renewed until {vendor.subscription_expiry}",
    )

    logger.info(
        f"Payment successful for vendor: {vendor.id} | Amount: NGN {amount} | New expiry: {vendor.subscription_expiry}"
    )
    return HttpResponse(status=200)


def handle_plan_change_payment(vendor, data, metadata, amount, reference):
    """Handle successful payment for plan changes"""
    from .models import SubscriptionHistory, VendorPlan

    try:
        # Get plan details from metadata
        new_plan_id = metadata.get("new_plan_id")
        old_plan_id = metadata.get("old_plan_id")
        prorated_amount = metadata.get("prorated_amount", 0)
        is_trial_upgrade = metadata.get("is_trial_upgrade", False)

        if not new_plan_id:
            logger.error(f"Missing new_plan_id in plan change payment metadata: {metadata}")
            return HttpResponse(status=400)

        new_plan = VendorPlan.objects.get(id=new_plan_id, is_active=True)
        old_plan = VendorPlan.objects.get(id=old_plan_id) if old_plan_id else None

        # Update vendor plan
        old_vendor_plan = vendor.plan
        vendor.plan = new_plan
        vendor.pending_ref = None
        vendor.last_payment_date = timezone.now()
        vendor.failed_payment_count = 0

        # Special handling for trial-to-paid conversions
        if vendor.subscription_status == "trial" or is_trial_upgrade:
            vendor.subscription_status = "active"
            vendor.subscription_expiry = timezone.now() + timedelta(days=SUBSCRIPTION_RENEWAL_DAYS)
            vendor.trial_start = None
            vendor.trial_end = None

        # Update Paystack subscription if vendor has one
        if vendor.paystack_subscription_code and new_plan.paystack_plan_code:
            try:
                from .services import update_paystack_subscription
                update_paystack_subscription(vendor, new_plan)
            except requests.RequestException as e:
                logger.warning(
                    f"Failed to update Paystack subscription for vendor {vendor.id}: {e}"
                )

        vendor.save()

        # Log the successful plan change
        is_upgrade = new_plan.price > (old_plan.price if old_plan else 0)
        event_type = "plan_upgraded" if is_upgrade else "plan_downgraded"

        notes = f"Plan change completed from {old_plan.name if old_plan else 'None'} to {new_plan.name}. "
        if is_trial_upgrade:
            notes += f"Trial converted to paid subscription. "
        notes += f"Amount paid: NGN {amount}"

        SubscriptionHistory.log_event(
            vendor=vendor,
            event_type=event_type,
            previous_plan=old_plan,
            new_plan=new_plan,
            amount=amount,
            payment_reference=reference,
            paystack_response=data,
            notes=notes,
        )

        logger.info(
            f"Plan change payment successful for vendor {vendor.id}: "
            f"{old_plan.name if old_plan else 'None'} -> {new_plan.name} | NGN {amount}"
        )
        return HttpResponse(status=200)

    except VendorPlan.DoesNotExist:
        logger.error(f"Plan not found during plan change payment processing: {metadata}")
        return HttpResponse(status=404)
    except Exception as e:
        logger.error(f"Error processing plan change payment: {e}", exc_info=True)
        return HttpResponse(status=500)


def handle_failed_payment(data):
    """Handle failed payment webhook for both subscriptions and plan changes"""
    from .models import SubscriptionHistory

    reference = data.get("reference")
    amount = data.get("amount", 0) / 100  # Convert from kobo to naira
    failure_reason = data.get("gateway_response", "Payment failed")
    metadata = data.get("metadata", {})

    if not reference:
        logger.warning("Missing reference in failed payment webhook.")
        return HttpResponse(status=400)

    try:
        vendor = VendorProfile.objects.get(pending_ref=reference)
    except VendorProfile.DoesNotExist:
        logger.warning(f"No vendor with ref: {reference}")
        return HttpResponse(status=404)

    # Check if this is a plan change payment
    if metadata.get("type") == "plan_change":
        return handle_plan_change_payment_failure(
            vendor, data, metadata, amount, reference, failure_reason
        )

    # Handle regular subscription payment failure
    # Increment failed payment count
    vendor.failed_payment_count += 1
    old_status = vendor.subscription_status

    # Set status based on failed payment count
    if vendor.failed_payment_count >= 3:
        vendor.subscription_status = "defaulted"
        notes = f"Payment failed (attempt {vendor.failed_payment_count}). Subscription defaulted."
    else:
        vendor.subscription_status = "grace"
        notes = f"Payment failed (attempt {vendor.failed_payment_count}). Subscription in grace period."

    vendor.save()

    # Log the payment failure
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="payment_failed",
        previous_status=old_status,
        new_status=vendor.subscription_status,
        amount=amount,
        payment_reference=reference,
        paystack_response=data,
        notes=f"{notes} Reason: {failure_reason}",
    )

    logger.warning(
        f"Payment failed for vendor: {vendor.id} | Amount: NGN {amount} | Attempt: {vendor.failed_payment_count} | Reason: {failure_reason}"
    )
    return HttpResponse(status=200)


def handle_plan_change_payment_failure(
    vendor, data, metadata, amount, reference, failure_reason
):
    """Handle failed payment for plan changes"""
    from .models import SubscriptionHistory, VendorPlan

    try:
        # Get plan details from metadata
        new_plan_id = metadata.get("new_plan_id")
        old_plan_id = metadata.get("old_plan_id")

        new_plan = VendorPlan.objects.get(id=new_plan_id) if new_plan_id else None
        old_plan = VendorPlan.objects.get(id=old_plan_id) if old_plan_id else None

        # Clear the pending reference since the payment failed
        vendor.pending_ref = None
        vendor.save()

        # Log the failed plan change
        SubscriptionHistory.log_event(
            vendor=vendor,
            event_type="payment_failed",
            previous_plan=old_plan,
            new_plan=new_plan,
            amount=amount,
            payment_reference=reference,
            paystack_response=data,
            notes=f"Plan change payment failed from {old_plan.name if old_plan else 'None'} to {new_plan.name if new_plan else 'Unknown'}. Reason: {failure_reason}",
        )

        logger.warning(
            f"Plan change payment failed for vendor: {vendor.id} | "
            f"Attempted change from {old_plan.name if old_plan else 'None'} to {new_plan.name if new_plan else 'Unknown'} | "
            f"Amount: NGN {amount} | Reason: {failure_reason}"
        )
        return HttpResponse(status=200)

    except Exception as e:
        logger.error(f"Error processing plan change payment failure: {str(e)}")
        return HttpResponse(status=500)


def handle_subscription_created(data):
    """Handle subscription creation webhook"""
    subscription_code = data.get("subscription_code")
    customer_email = data.get("customer", {}).get("email")

    if not subscription_code or not customer_email:
        logger.warning("Missing subscription code or customer email in webhook.")
        return HttpResponse(status=400)

    try:
        vendor = VendorProfile.objects.get(user__email=customer_email)
        vendor.paystack_subscription_code = subscription_code
        vendor.save()
        logger.info(f"Subscription code updated for vendor: {vendor.id}")
    except VendorProfile.DoesNotExist:
        logger.warning(f"No vendor found with email: {customer_email}")
        return HttpResponse(status=404)

    return HttpResponse(status=200)


def handle_subscription_disabled(data):
    """Handle subscription disabled webhook"""
    from .models import SubscriptionHistory

    subscription_code = data.get("subscription_code")

    if not subscription_code:
        logger.warning("Missing subscription code in disable webhook.")
        return HttpResponse(status=400)

    try:
        vendor = VendorProfile.objects.get(paystack_subscription_code=subscription_code)
        old_status = vendor.subscription_status
        vendor.subscription_status = "cancelled"
        vendor.save()

        # Log the cancellation
        SubscriptionHistory.log_event(
            vendor=vendor,
            event_type="subscription_cancelled",
            previous_status=old_status,
            new_status="cancelled",
            paystack_response=data,
            notes="Subscription disabled via Paystack webhook",
        )

        logger.info(f"Subscription disabled for vendor: {vendor.id}")
    except VendorProfile.DoesNotExist:
        logger.warning(f"No vendor found with subscription code: {subscription_code}")
        return HttpResponse(status=404)

    return HttpResponse(status=200)
