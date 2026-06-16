"""Subscription business logic extracted from VendorProfile.

Keep model methods as thin wrappers so existing call sites do not change.
"""

import uuid
import logging

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = settings.PAYSTACK_BASE_URL
_PAYSTACK_HEADERS = lambda: {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json",
}


def update_paystack_subscription(vendor, new_plan):
    """Push a plan change to Paystack for a vendor with an active subscription.

    Raises an exception if the Paystack API call fails — callers should catch
    and decide whether the failure is blocking or advisory.
    """
    if not vendor.paystack_subscription_code or not new_plan.paystack_plan_code:
        return

    response = requests.put(
        f"{PAYSTACK_BASE_URL}/subscription/{vendor.paystack_subscription_code}",
        json={"plan": new_plan.paystack_plan_code},
        headers=_PAYSTACK_HEADERS(),
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(
            f"Failed to update Paystack subscription: {response.text}"
        )


def change_plan_with_payment(vendor, new_plan, immediate=False, request=None):
    """Initiate or apply a subscription plan change for a vendor.

    If the change requires a payment (upgrade from trial, or mid-cycle upgrade
    with a positive prorated amount), a Paystack transaction is initialised and
    the caller receives an authorization URL to redirect the user to.

    If no payment is needed the plan is updated immediately in the database and
    the Paystack subscription record is updated in the background.

    Returns a dict with at minimum:
        success (bool)
        error (str)            — only present when success is False
        payment_status (str)   — "completed" | "payment_required"
        authorization_url (str) — only present when payment_required
    """
    from .models import SubscriptionHistory  # avoid circular import at module level

    if not new_plan or new_plan == vendor.plan:
        return {"success": False, "error": "Invalid plan or already on this plan."}

    old_plan = vendor.plan
    is_upgrade = new_plan.price > (old_plan.price if old_plan else 0)

    prorated_amount = 0
    requires_payment = False

    if vendor.subscription_status == "trial" and is_upgrade and new_plan.price > 0:
        prorated_amount = new_plan.price
        requires_payment = True
    elif vendor.subscription_status == "trial" and not is_upgrade:
        prorated_amount = 0
        requires_payment = False
    elif vendor.subscription_expiry and not immediate:
        days_remaining = vendor.get_subscription_days_remaining()
        if days_remaining > 0:
            daily_old_rate = (old_plan.price if old_plan else 0) / 30
            daily_new_rate = new_plan.price / 30
            prorated_amount = (daily_new_rate - daily_old_rate) * days_remaining
            requires_payment = is_upgrade and prorated_amount > 0

    if requires_payment and request:
        try:
            ref = str(uuid.uuid4()).replace("-", "")[:20]
            callback_url = (
                f"{request.scheme}://{request.get_host()}"
                f"{reverse('paystack_callback')}"
            )

            payload = {
                "email": vendor.user.email,
                "amount": int(prorated_amount * 100),  # kobo
                "reference": ref,
                "callback_url": callback_url,
                "metadata": {
                    "type": "plan_change",
                    "vendor_id": vendor.id,
                    "old_plan_id": old_plan.id if old_plan else None,
                    "new_plan_id": new_plan.id,
                    "prorated_amount": prorated_amount,
                    "is_trial_upgrade": vendor.subscription_status == "trial",
                },
            }

            response = requests.post(
                f"{PAYSTACK_BASE_URL}/transaction/initialize",
                json=payload,
                headers=_PAYSTACK_HEADERS(),
                timeout=30,
            )

            if response.status_code != 200:
                raise Exception("Failed to initialize payment with Paystack")

            response_data = response.json()
            if not response_data.get("status"):
                raise Exception(
                    response_data.get("message", "Payment initialization failed")
                )

            vendor.pending_ref = ref
            vendor.save()

            SubscriptionHistory.log_event(
                vendor=vendor,
                event_type="plan_upgraded" if is_upgrade else "plan_downgraded",
                previous_plan=old_plan,
                new_plan=new_plan,
                amount=prorated_amount,
                payment_reference=ref,
                notes=(
                    f"Plan change initiated from "
                    f"{old_plan.name if old_plan else 'None'} to {new_plan.name}"
                    " - Payment pending"
                ),
            )

            return {
                "success": True,
                "prorated_amount": prorated_amount,
                "is_upgrade": is_upgrade,
                "old_plan": old_plan.name if old_plan else None,
                "new_plan": new_plan.name,
                "authorization_url": response_data["data"]["authorization_url"],
                "payment_status": "payment_required",
            }

        except requests.Timeout:
            raise Exception("Payment service timeout. Please try again.")
        except requests.RequestException as e:
            raise Exception(f"Payment service error: {str(e)}")

    # No payment required — apply immediately.
    if vendor.paystack_subscription_code and new_plan.paystack_plan_code:
        try:
            update_paystack_subscription(vendor, new_plan)
        except Exception as e:
            logger.error(
                f"Failed to update Paystack subscription for vendor {vendor.id}: {e}"
            )

    vendor.plan = new_plan
    vendor.save()

    event_type = "plan_upgraded" if is_upgrade else "plan_downgraded"
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type=event_type,
        previous_plan=old_plan,
        new_plan=new_plan,
        amount=prorated_amount,
        notes=(
            f"Plan changed from {old_plan.name if old_plan else 'None'} to {new_plan.name}"
        ),
    )

    return {
        "success": True,
        "prorated_amount": prorated_amount,
        "is_upgrade": is_upgrade,
        "old_plan": old_plan.name if old_plan else None,
        "new_plan": new_plan.name,
        "payment_status": "completed",
    }
