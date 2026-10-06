"""Privileged operations performed by staff from the admin.

Each function enforces its own business rules and writes the audit trail, so
the outcome is the same however the action is triggered. Permission checks
happen in the admin layer (and are repeated there per object).
"""

import logging

from django.db import transaction
from django.utils import timezone

from store import paystack
from store.models import Order, Payment, Product, Review
from store.services import confirm_order_payment
from userprofile.models import UserProfile, VendorProfile

from .audit import record

logger = logging.getLogger(__name__)


class OperationError(Exception):
    """A business rule stopped the action; ``message`` is shown to staff."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _require_reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise OperationError("A reason is required.")
    return reason


# ── Accounts ────────────────────────────────────────────────────────────────


def suspend_user(user, *, actor, reason, request=None):
    """Block sign-in and end every session. A vendor's store stops selling too."""
    reason = _require_reason(reason)
    if user.is_superuser:
        raise OperationError("Superuser accounts can't be suspended here.")
    if user.pk == actor.pk:
        raise OperationError("You can't suspend your own account.")
    if not user.is_active:
        raise OperationError(f"{user.email} is already suspended.")

    from userprofile.auth_api import _blacklist_all_refresh_tokens_for_user

    with transaction.atomic():
        UserProfile.objects.filter(pk=user.pk).update(is_active=False)
        _blacklist_all_refresh_tokens_for_user(user.pk)
        record(actor=actor, action="user.suspend", target=user, reason=reason,
               changes={"is_active": [True, False]}, request=request)


def restore_user(user, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if user.is_active:
        raise OperationError(f"{user.email} is not suspended.")
    with transaction.atomic():
        UserProfile.objects.filter(pk=user.pk).update(is_active=True)
        record(actor=actor, action="user.restore", target=user, reason=reason,
               changes={"is_active": [False, True]}, request=request)


def suspend_vendor(vendor, *, actor, reason, request=None):
    """Hide the store and stop new orders. Paid orders can still be fulfilled
    and the vendor keeps access to their dashboard."""
    reason = _require_reason(reason)
    if vendor.is_suspended:
        raise OperationError(f"{vendor.store_name} is already suspended.")
    with transaction.atomic():
        VendorProfile.objects.filter(pk=vendor.pk).update(is_suspended=True, suspension_reason=reason[:255])
        record(actor=actor, action="vendor.suspend", target=vendor, reason=reason,
               changes={"is_suspended": [False, True]}, request=request)


def restore_vendor(vendor, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if not vendor.is_suspended:
        raise OperationError(f"{vendor.store_name} is not suspended.")
    with transaction.atomic():
        VendorProfile.objects.filter(pk=vendor.pk).update(is_suspended=False, suspension_reason="")
        record(actor=actor, action="vendor.restore", target=vendor, reason=reason,
               changes={"is_suspended": [True, False]}, request=request)


# ── Listings & reviews ──────────────────────────────────────────────────────


def hide_product(product, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if product.status == Product.HIDDEN:
        raise OperationError(f"“{product.title}” is already hidden.")
    if product.status == Product.DELETED:
        raise OperationError(f"“{product.title}” was deleted by the vendor.")
    previous = product.status
    with transaction.atomic():
        Product.objects.filter(pk=product.pk).update(
            status=Product.HIDDEN, moderation_note=reason[:255], featured=False
        )
        record(actor=actor, action="product.hide", target=product, reason=reason,
               changes={"status": [previous, Product.HIDDEN]}, request=request)


def restore_product(product, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if product.status != Product.HIDDEN:
        raise OperationError(f"“{product.title}” isn't hidden.")
    with transaction.atomic():
        Product.objects.filter(pk=product.pk).update(status=Product.ACTIVE, moderation_note="")
        record(actor=actor, action="product.restore", target=product, reason=reason,
               changes={"status": [Product.HIDDEN, Product.ACTIVE]}, request=request)


def set_featured(product, featured, *, actor, request=None):
    if product.status != Product.ACTIVE and featured:
        raise OperationError(f"“{product.title}” isn't live, so it can't be featured.")
    if product.featured == featured:
        return
    with transaction.atomic():
        Product.objects.filter(pk=product.pk).update(featured=featured)
        record(actor=actor, action="product.feature" if featured else "product.unfeature",
               target=product, changes={"featured": [not featured, featured]}, request=request)


def hide_review(review, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if not review.approved_review:
        raise OperationError("This review is already hidden.")
    with transaction.atomic():
        Review.objects.filter(pk=review.pk).update(approved_review=False)
        record(actor=actor, action="review.hide", target=review, reason=reason,
               changes={"approved_review": [True, False], "rating": review.rating, "text": review.text},
               request=request)


def restore_review(review, *, actor, reason, request=None):
    reason = _require_reason(reason)
    if review.approved_review:
        raise OperationError("This review is already visible.")
    with transaction.atomic():
        Review.objects.filter(pk=review.pk).update(approved_review=True)
        record(actor=actor, action="review.restore", target=review, reason=reason,
               changes={"approved_review": [False, True]}, request=request)


# ── Orders & payments ───────────────────────────────────────────────────────


def recheck_payment(payment, *, actor, request=None):
    """Ask Paystack for the authoritative state of a payment and apply it."""
    if payment.status == Payment.PAID:
        raise OperationError(f"{payment.ref} is already paid.")
    previous = payment.status
    try:
        updated = confirm_order_payment(payment.ref)
    except paystack.PaystackError as exc:
        raise OperationError(f"Paystack couldn't be reached: {exc.message}")
    record(actor=actor, action="payment.recheck", target=payment,
           changes={"status": [previous, updated.status]}, request=request)
    return updated.status


def refund_order(order, *, actor, reason, restock=False, request=None):
    """Request a full Paystack refund. The order is marked refunded when
    Paystack confirms (``refund.processed`` webhook)."""
    reason = _require_reason(reason)
    if not order.is_paid:
        raise OperationError(f"Order {order.ref} was never paid, so there's nothing to refund.")
    if order.refund_status in (Order.REFUND_PENDING, Order.REFUND_PROCESSED):
        raise OperationError(f"Order {order.ref} already has a refund {order.get_refund_status_display().lower()}.")

    try:
        paystack.refund_transaction(order.ref, merchant_note=reason)
    except paystack.PaystackError as exc:
        raise OperationError(f"Paystack rejected the refund: {exc.message}")

    with transaction.atomic():
        Order.objects.filter(pk=order.pk).update(
            refund_status=Order.REFUND_PENDING, refund_requested_at=timezone.now()
        )
        if restock:
            for item in order.items.select_related("product"):
                Product.objects.filter(pk=item.product_id).update(
                    quantity=item.product.quantity + item.quantity, stock=Product.IN_STOCK
                )
        record(actor=actor, action="order.refund", target=order, reason=reason,
               changes={"refund_status": [order.refund_status, Order.REFUND_PENDING],
                        "amount": order.amount_due, "restocked": restock},
               request=request)


def apply_refund_event(data, processed):
    """Webhook: Paystack finished (or failed) a refund."""
    reference = data.get("transaction_reference") or (data.get("transaction") or {}).get("reference")
    if not reference:
        return
    order = Order.objects.filter(ref=reference).first()
    if order is None:
        return
    if processed:
        Order.objects.filter(pk=order.pk).update(refund_status=Order.REFUND_PROCESSED, refunded_at=timezone.now())
    else:
        Order.objects.filter(pk=order.pk).update(refund_status=Order.REFUND_FAILED)
        logger.error("Paystack refund failed for order %s", reference)
