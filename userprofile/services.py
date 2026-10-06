"""Vendor subscription and KPI business logic.

Subscription money flows through Paystack in three ways, all handled here:

* **Subscribe** (first time, after a trial, or after lapsing): a transaction
  initialised with a Paystack *plan*, which also creates the recurring
  subscription. ``metadata.type == "subscription"``.
* **Plan upgrade** for a paying vendor: a one-off prorated charge.
  ``metadata.type == "plan_change"``.
* **Renewal**: Paystack charges the saved card each cycle and tells us via the
  webhook. These carry no metadata of ours; the vendor is found by
  subscription code or customer email.

Each payment is applied at most once (keyed by its reference) no matter how
many times the redirect verification and the webhook deliver it.
"""

import logging
import math
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from store import paystack

logger = logging.getLogger(__name__)

SUBSCRIPTION_PERIOD_DAYS = 30
APPLIED_PAYMENT_EVENTS = ("payment_success", "plan_upgraded", "subscription_renewed")


class SubscriptionError(Exception):
    def __init__(self, message, code="subscription_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _isoformat_or_none(value):
    return value.isoformat() if value is not None else None


def _new_reference():
    return uuid.uuid4().hex[:20]


def _billing_callback_url():
    return f"{settings.FRONTEND_URL}/vendor/billing"


def has_recurring_billing(vendor):
    return bool(vendor.paystack_subscription_code) and vendor.subscription_status in (
        "active",
        "grace",
    )


# ── Starting payments ───────────────────────────────────────────────────────


def start_subscription_payment(vendor, plan):
    """Open a Paystack checkout that pays for ``plan`` and starts recurring billing."""
    if not plan.is_active:
        raise SubscriptionError("This plan is no longer available.", "plan_inactive")
    if has_recurring_billing(vendor) and vendor.has_selling_access():
        raise SubscriptionError(
            "You already have an active subscription. Change your plan instead.",
            "already_subscribed",
        )
    if plan.price <= 0:
        raise SubscriptionError("This plan can't be purchased.", "plan_inactive")

    reference = _new_reference()
    data = paystack.initialize_transaction(
        email=vendor.user.email,
        amount_kobo=plan.price * 100,
        reference=reference,
        callback_url=_billing_callback_url(),
        plan=plan.paystack_plan_code or None,
        metadata={"type": "subscription", "vendor_id": vendor.pk, "plan_id": plan.pk},
    )
    vendor.pending_ref = reference
    vendor.save(update_fields=["pending_ref"])
    return {
        "authorization_url": data["authorization_url"],
        "reference": reference,
        "amount": plan.price,
        "payment_status": "payment_required",
    }


def prorated_upgrade_amount(vendor, new_plan):
    """Price difference for the days left in the current paid period (whole naira)."""
    if not vendor.subscription_expiry or not vendor.plan:
        return new_plan.price
    seconds_left = (vendor.subscription_expiry - timezone.now()).total_seconds()
    days_left = max(0, math.ceil(seconds_left / 86400))
    daily_difference = (new_plan.price - vendor.plan.price) / SUBSCRIPTION_PERIOD_DAYS
    return max(0, math.ceil(daily_difference * days_left))


def change_plan(vendor, new_plan):
    """Move a vendor to ``new_plan``.

    * Trial, lapsed or cancelled vendors are simply subscribed to the plan.
    * Upgrades pay the prorated difference now; the recurring charge moves to
      the new plan from the next billing date.
    * Downgrades take effect at the next billing date, so nobody loses time
      they already paid for.
    """
    from .models import SubscriptionHistory

    if not new_plan.is_active:
        raise SubscriptionError("This plan is no longer available.", "plan_inactive")
    if vendor.plan_id == new_plan.pk and not vendor.scheduled_plan_id:
        raise SubscriptionError("You're already on this plan.", "same_plan")

    if not (has_recurring_billing(vendor) and vendor.has_selling_access()):
        return start_subscription_payment(vendor, new_plan)

    current_plan = vendor.plan
    if vendor.plan_id == new_plan.pk:
        # Undo a scheduled downgrade.
        _switch_recurring_plan(vendor, new_plan)
        vendor.scheduled_plan = None
        vendor.save(update_fields=["scheduled_plan"])
        return {"payment_status": "completed", "message": f"You'll stay on {new_plan}."}

    if current_plan and new_plan.price < current_plan.price:
        _switch_recurring_plan(vendor, new_plan)
        vendor.scheduled_plan = new_plan
        vendor.save(update_fields=["scheduled_plan"])
        SubscriptionHistory.log_event(
            vendor=vendor,
            event_type="plan_downgraded",
            previous_plan=current_plan,
            new_plan=new_plan,
            notes=f"Scheduled for {vendor.subscription_expiry:%d %b %Y}",
        )
        return {
            "payment_status": "scheduled",
            "message": (
                f"You'll move to {new_plan} on {vendor.subscription_expiry:%d %b %Y}. "
                f"Until then you keep everything in {current_plan}."
            ),
        }

    amount = prorated_upgrade_amount(vendor, new_plan)
    if amount <= 0:
        _apply_upgrade(vendor, new_plan, reference=None, amount=0)
        return {"payment_status": "completed", "message": f"You're now on {new_plan}."}

    reference = _new_reference()
    data = paystack.initialize_transaction(
        email=vendor.user.email,
        amount_kobo=amount * 100,
        reference=reference,
        callback_url=_billing_callback_url(),
        metadata={
            "type": "plan_change",
            "vendor_id": vendor.pk,
            "old_plan_id": current_plan.pk if current_plan else None,
            "new_plan_id": new_plan.pk,
            "expected_amount": amount,
        },
    )
    vendor.pending_ref = reference
    vendor.save(update_fields=["pending_ref"])
    return {
        "authorization_url": data["authorization_url"],
        "reference": reference,
        "amount": amount,
        "payment_status": "payment_required",
    }


def _switch_recurring_plan(vendor, plan):
    """Point Paystack's recurring billing at ``plan`` from the next billing date.

    Paystack can't edit a subscription's plan, so a new subscription starting
    at the current expiry is created with the saved card and the old one is
    disabled. Failures are logged rather than raised: the vendor's access is
    already correct and renewals always apply the plan actually charged.
    """
    if not (
        plan.paystack_plan_code
        and vendor.paystack_customer_code
        and vendor.paystack_authorization_code
        and vendor.subscription_expiry
    ):
        logger.warning(
            "Cannot move vendor %s recurring billing to %s: missing Paystack details",
            vendor.pk,
            plan,
        )
        return False

    old_code, old_token = vendor.paystack_subscription_code, vendor.subscription_token
    try:
        created = paystack.create_subscription(
            customer=vendor.paystack_customer_code,
            plan=plan.paystack_plan_code,
            authorization=vendor.paystack_authorization_code,
            start_date=vendor.subscription_expiry,
        )
    except paystack.PaystackError:
        logger.exception("Failed to create new subscription for vendor %s", vendor.pk)
        return False

    vendor.paystack_subscription_code = created.get("subscription_code") or old_code
    vendor.subscription_token = created.get("email_token") or old_token
    vendor.save(update_fields=["paystack_subscription_code", "subscription_token"])

    if old_code and old_code != vendor.paystack_subscription_code:
        try:
            token = old_token or paystack.fetch_subscription(old_code).get("email_token")
            paystack.disable_subscription(old_code, token)
        except paystack.PaystackError:
            logger.exception(
                "Vendor %s now has two Paystack subscriptions; disable %s manually",
                vendor.pk,
                old_code,
            )
    return True


# ── Applying payments ───────────────────────────────────────────────────────


def _already_applied(vendor, reference):
    from .models import SubscriptionHistory

    return SubscriptionHistory.objects.filter(
        vendor=vendor, payment_reference=reference, event_type__in=APPLIED_PAYMENT_EVENTS
    ).exists()


def _remember_payment_method(vendor, data):
    authorization = data.get("authorization") or {}
    customer = data.get("customer") or {}
    if authorization.get("reusable") and authorization.get("authorization_code"):
        vendor.paystack_authorization_code = authorization["authorization_code"]
    if customer.get("customer_code"):
        vendor.paystack_customer_code = customer["customer_code"]


def _apply_upgrade(vendor, new_plan, reference, amount, data=None):
    from .models import SubscriptionHistory

    previous_plan = vendor.plan
    vendor.plan = new_plan
    vendor.scheduled_plan = None
    if reference and vendor.pending_ref == reference:
        vendor.pending_ref = None
    vendor.save()
    _switch_recurring_plan(vendor, new_plan)
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="plan_upgraded",
        previous_plan=previous_plan,
        new_plan=new_plan,
        previous_status=vendor.subscription_status,
        new_status=vendor.subscription_status,
        amount=amount,
        payment_reference=reference or "",
        paystack_response=data,
        notes=f"Upgraded from {previous_plan} to {new_plan}",
    )


def _start_paid_period(vendor, plan, reference, amount, data, event_type):
    from .models import SubscriptionHistory

    previous_status = vendor.subscription_status
    period_start = vendor.paid_period_start()
    vendor.plan = plan
    vendor.scheduled_plan = None
    vendor.subscription_status = "active"
    vendor.subscription_expiry = period_start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
    vendor.last_payment_date = timezone.now()
    vendor.failed_payment_count = 0
    if vendor.pending_ref == reference:
        vendor.pending_ref = None
    _remember_payment_method(vendor, data)
    vendor.save()
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type=event_type,
        new_plan=plan,
        previous_status=previous_status,
        new_status="active",
        amount=amount,
        payment_reference=reference,
        paystack_response=data,
        notes=f"Paid through {vendor.subscription_expiry:%d %b %Y}",
    )


def _plan_from_transaction(data):
    from .models import VendorPlan

    plan_info = data.get("plan") or {}
    plan_code = plan_info.get("plan_code") if isinstance(plan_info, dict) else None
    if plan_code:
        return VendorPlan.objects.filter(paystack_plan_code=plan_code).first()
    return None


def apply_subscription_transaction(data):
    """Apply a verified, successful Paystack transaction to the right vendor.

    Returns the vendor it was applied to, or ``None`` if the transaction is not
    a subscription payment we recognise.
    """
    from .models import VendorPlan, VendorProfile

    reference = data.get("reference")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    amount_naira = int(data.get("amount") or 0) // 100
    payment_type = metadata.get("type")

    vendor = None
    if reference:
        vendor = VendorProfile.objects.filter(pending_ref=reference).first()
    if vendor is None and metadata.get("vendor_id"):
        vendor = VendorProfile.objects.filter(pk=metadata["vendor_id"]).first()
    if vendor is None:
        vendor = _vendor_for_renewal(data)
    if vendor is None:
        return None

    with transaction.atomic():
        vendor = VendorProfile.objects.select_for_update().get(pk=vendor.pk)
        if reference and _already_applied(vendor, reference):
            return vendor

        if payment_type == "plan_change":
            new_plan = VendorPlan.objects.filter(pk=metadata.get("new_plan_id")).first()
            expected = int(metadata.get("expected_amount") or 0)
            if new_plan is None or amount_naira < expected:
                logger.critical(
                    "Plan change %s for vendor %s rejected: plan=%s paid=%s expected=%s",
                    reference,
                    vendor.pk,
                    new_plan,
                    amount_naira,
                    expected,
                )
                return vendor
            _remember_payment_method(vendor, data)
            _apply_upgrade(vendor, new_plan, reference, amount_naira, data)
            return vendor

        if payment_type == "subscription":
            plan = VendorPlan.objects.filter(pk=metadata.get("plan_id")).first()
            if plan is None or amount_naira < plan.price:
                logger.critical(
                    "Subscription payment %s for vendor %s rejected: plan=%s paid=%s",
                    reference,
                    vendor.pk,
                    plan,
                    amount_naira,
                )
                return vendor
            _start_paid_period(vendor, plan, reference, amount_naira, data, "payment_success")
            return vendor

        # Recurring renewal charged by Paystack.
        plan = _plan_from_transaction(data) or vendor.scheduled_plan or vendor.plan
        if plan is None:
            logger.error("Renewal %s for vendor %s has no identifiable plan", reference, vendor.pk)
            return vendor
        _start_paid_period(vendor, plan, reference, amount_naira, data, "subscription_renewed")
        return vendor


def _vendor_for_renewal(data):
    from .models import VendorProfile

    subscription = data.get("subscription")
    code = subscription.get("subscription_code") if isinstance(subscription, dict) else subscription
    if code:
        vendor = VendorProfile.objects.filter(paystack_subscription_code=code).first()
        if vendor:
            return vendor

    # charge.success for a renewal carries the plan but not the subscription.
    if _plan_from_transaction(data) is None:
        return None
    email = ((data.get("customer") or {}).get("email") or "").strip()
    if not email:
        return None
    return VendorProfile.objects.filter(user__email__iexact=email).first()


def verify_subscription_payment(vendor, reference):
    """Check a returning vendor's payment with Paystack and apply it.

    Returns ``"paid"``, ``"pending"`` or ``"failed"``.
    """
    from .models import SubscriptionHistory

    if _already_applied(vendor, reference):
        return "paid"
    owns_reference = vendor.pending_ref == reference or SubscriptionHistory.objects.filter(
        vendor=vendor, payment_reference=reference
    ).exists()
    if not owns_reference:
        raise SubscriptionError("We couldn't find that payment.", "not_found")

    data = paystack.verify_transaction(reference)
    metadata = data.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("vendor_id") not in (None, vendor.pk):
        raise SubscriptionError("We couldn't find that payment.", "not_found")

    status = data.get("status")
    if status == "success":
        apply_subscription_transaction(data)
        return "paid" if _already_applied(vendor, reference) else "failed"
    if status in ("failed", "reversed"):
        if vendor.pending_ref == reference:
            vendor.pending_ref = None
            vendor.save(update_fields=["pending_ref"])
        return "failed"
    return "pending"


# ── Cancellation & webhook events ───────────────────────────────────────────


def cancel_subscription(vendor):
    """Stop future charges. The vendor keeps access until the paid period ends."""
    from .models import SubscriptionHistory

    if vendor.subscription_status == "cancelled":
        raise SubscriptionError("Your subscription is already cancelled.", "already_cancelled")
    if vendor.subscription_status == "trial":
        raise SubscriptionError(
            "You're on a free trial, so there's nothing to cancel.", "nothing_to_cancel"
        )

    code = vendor.paystack_subscription_code
    if code:
        token = vendor.subscription_token or paystack.fetch_subscription(code).get("email_token")
        paystack.disable_subscription(code, token)

    previous_status = vendor.subscription_status
    vendor.subscription_status = "cancelled"
    vendor.scheduled_plan = None
    vendor.save(update_fields=["subscription_status", "scheduled_plan"])
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="subscription_cancelled",
        previous_status=previous_status,
        new_status="cancelled",
        notes="Cancelled by vendor",
    )


def handle_subscription_created(data):
    from .models import VendorProfile

    code = data.get("subscription_code")
    email = ((data.get("customer") or {}).get("email") or "").strip()
    if not code or not email:
        return
    vendor = VendorProfile.objects.filter(user__email__iexact=email).first()
    if vendor is None:
        logger.warning("subscription.create for unknown customer")
        return
    vendor.paystack_subscription_code = code
    vendor.subscription_token = data.get("email_token") or vendor.subscription_token
    customer_code = (data.get("customer") or {}).get("customer_code")
    if customer_code:
        vendor.paystack_customer_code = customer_code
    authorization = data.get("authorization") or {}
    if authorization.get("reusable") and authorization.get("authorization_code"):
        vendor.paystack_authorization_code = authorization["authorization_code"]
    vendor.save()


def handle_subscription_disabled(data):
    from .models import SubscriptionHistory, VendorProfile

    vendor = VendorProfile.objects.filter(
        paystack_subscription_code=data.get("subscription_code")
    ).first()
    if vendor is None or vendor.subscription_status == "cancelled":
        return
    previous_status = vendor.subscription_status
    vendor.subscription_status = "cancelled"
    vendor.save(update_fields=["subscription_status"])
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="subscription_cancelled",
        previous_status=previous_status,
        new_status="cancelled",
        notes="Subscription disabled on Paystack",
    )


def handle_invoice_payment_failed(data):
    from .models import SubscriptionHistory, VendorProfile

    subscription = data.get("subscription") or {}
    code = subscription.get("subscription_code") if isinstance(subscription, dict) else None
    vendor = VendorProfile.objects.filter(paystack_subscription_code=code).first() if code else None
    if vendor is None:
        return
    previous_status = vendor.subscription_status
    vendor.failed_payment_count += 1
    vendor.subscription_status = "defaulted" if vendor.failed_payment_count >= 3 else "grace"
    vendor.save(update_fields=["failed_payment_count", "subscription_status"])
    SubscriptionHistory.log_event(
        vendor=vendor,
        event_type="payment_failed",
        previous_status=previous_status,
        new_status=vendor.subscription_status,
        paystack_response=data,
        notes=f"Renewal attempt {vendor.failed_payment_count} failed",
    )


def get_vendor_kpis(vendor):
    """Return a dict of KPI metrics for the given VendorProfile.

    Extracted from vendor_kpis_api so the logic is independently testable.
    """
    from django.db.models import Avg, Count, Sum
    from store.models import Product, OrderItem, Review
    from .models import SubscriptionHistory

    now = timezone.now()

    # ── Ratings ──────────────────────────────────────────────────────────────
    all_reviews = Review.objects.filter(product__vendor=vendor, approved_review=True)
    rating_stats = all_reviews.aggregate(
        average_rating=Avg("rating"), total_reviews=Count("id")
    )
    _counts = {
        row["rating"]: row["count"]
        for row in all_reviews.values("rating").annotate(count=Count("id"))
    }
    rating_breakdown = {f"{n}_star": _counts.get(n, 0) for n in range(5, 0, -1)}

    # ── Sales ─────────────────────────────────────────────────────────────────
    vendor_order_items = OrderItem.objects.filter(
        product__vendor=vendor, order__is_paid=True
    )
    sales_stats = vendor_order_items.aggregate(
        total_orders=Count("order", distinct=True),
        total_revenue=Sum("price"),
        total_products_sold=Sum("quantity"),
    )

    # ── Products ──────────────────────────────────────────────────────────────
    vendor_products = Product.objects.filter(vendor=vendor)
    product_stats = {
        "total_products": vendor_products.count(),
        "active_products": vendor_products.filter(status=Product.ACTIVE).count(),
        "out_of_stock": vendor_products.filter(quantity=0).count(),
        "low_stock": vendor_products.filter(quantity__lte=5, quantity__gt=0).count(),
        "total_inventory": vendor_products.aggregate(Sum("quantity"))["quantity__sum"] or 0,
    }

    # ── Subscription history analytics ───────────────────────────────────────
    history = SubscriptionHistory.objects.filter(vendor=vendor)
    payment_success_count = history.filter(event_type="payment_success").count()
    payment_failed_count = history.filter(event_type="payment_failed").count()
    total_payments = (
        history.filter(event_type="payment_success", amount__isnull=False)
        .aggregate(Sum("amount"))["amount__sum"]
        or 0
    )

    trial_analytics = None
    if vendor.trial_start and vendor.trial_end:
        trial_analytics = {
            "trial_started": vendor.trial_start.isoformat(),
            "trial_ends": vendor.trial_end.isoformat(),
            "trial_days_used": (now - vendor.trial_start).days if now > vendor.trial_start else 0,
            "trial_days_remaining": max(0, (vendor.trial_end - now).days) if vendor.trial_end > now else 0,
        }

    subscription_info = {
        "status": vendor.get_effective_subscription_status(),
        "days_remaining": vendor.get_subscription_days_remaining(),
        "is_in_grace_period": vendor.is_in_grace_period(),
        "plan_name": vendor.plan.name if vendor.plan else None,
        "plan_price": float(vendor.plan.price) if vendor.plan else 0,
        "max_products": vendor.plan.max_products if vendor.plan else 0,
        "expires_at": _isoformat_or_none(vendor.get_effective_subscription_expiry()),
        "raw_status": vendor.subscription_status,
        "raw_expires_at": _isoformat_or_none(vendor.subscription_expiry),
        "trial_start": _isoformat_or_none(vendor.trial_start),
        "trial_end": _isoformat_or_none(vendor.trial_end),
        "last_payment": vendor.last_payment_date.isoformat() if vendor.last_payment_date else None,
        "failed_payment_count": vendor.failed_payment_count,
        "analytics": {
            "successful_payments": payment_success_count,
            "failed_payments": payment_failed_count,
            "total_payments_value": float(total_payments),
            "average_payment": float(total_payments / payment_success_count) if payment_success_count > 0 else 0,
            "subscription_changes": history.filter(
                event_type__in=["plan_upgraded", "plan_downgraded"]
            ).count(),
            "trial_info": trial_analytics,
        },
    }

    return {
        "vendor_id": vendor.id,
        "store_name": vendor.store_name,
        "ratings": {
            "average_rating": round(rating_stats["average_rating"] or 0, 1),
            "total_reviews": rating_stats["total_reviews"] or 0,
            "rating_breakdown": rating_breakdown,
        },
        "sales": {
            "total_orders": sales_stats["total_orders"] or 0,
            "total_revenue": float(sales_stats["total_revenue"] or 0),
            "total_products_sold": sales_stats["total_products_sold"] or 0,
        },
        "products": product_stats,
        "subscription": subscription_info,
    }
