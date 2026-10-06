"""Cart, checkout and order-payment business logic.

Views stay thin: they translate HTTP into calls on these functions and the
exceptions below into error responses. Keeping the rules here means the cart
page, checkout, payment verification and the Paystack webhook all agree on
what can be bought, what it costs and when an order counts as paid.
"""

import logging
import math
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from userprofile.email_utils import send_receipt_email, send_vendor_order_notification

from . import paystack
from .models import CartItem, Order, OrderItem, Payment, Product, Review

logger = logging.getLogger(__name__)

MAX_QUANTITY_PER_ITEM = 50

# Paystack local-card pricing: 1.5% + NGN 100, the NGN 100 waived below
# NGN 2,500, total capped at NGN 2,000. Buyers pay this on top of the item
# prices so vendors receive exactly their listed price.
PAYSTACK_PERCENTAGE = Decimal("0.015")
PAYSTACK_FLAT_FEE = 100
PAYSTACK_FLAT_FEE_THRESHOLD = 2500
PAYSTACK_FEE_CAP = 2000

# Paystack transaction statuses that will never become successful.
FINAL_FAILURE_STATUSES = {"failed", "reversed"}


class CartError(Exception):
    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


class CheckoutError(CartError):
    def __init__(self, message, code="checkout_failed", problems=None):
        super().__init__(message, code)
        self.problems = problems or []


@dataclass
class CartLine:
    item: CartItem
    product: Product
    quantity: int
    available_quantity: int
    issue: Optional[str]

    @property
    def line_total(self):
        return self.product.price * self.quantity


# ── Pricing ─────────────────────────────────────────────────────────────────


def calculate_service_fee(subtotal):
    """Fee in whole naira that makes the net settlement equal ``subtotal``."""
    if subtotal <= 0:
        return 0
    flat = PAYSTACK_FLAT_FEE if subtotal >= PAYSTACK_FLAT_FEE_THRESHOLD else 0
    gross = (Decimal(subtotal) + flat) / (1 - PAYSTACK_PERCENTAGE)
    fee = math.ceil(gross - subtotal)
    return min(fee, PAYSTACK_FEE_CAP)


# ── Cart ────────────────────────────────────────────────────────────────────


def _vendor_of(user):
    return getattr(user, "vendor_profile", None)


def get_cart_lines(user):
    items = (
        CartItem.objects.filter(user=user)
        .select_related("product", "product__vendor", "product__category")
        .order_by("-updated_at")
    )
    visible_ids = set(
        Product.objects.visible()
        .filter(pk__in=[item.product_id for item in items])
        .values_list("pk", flat=True)
    )
    vendor = _vendor_of(user)
    lines = []
    for item in items:
        product = item.product
        if vendor and product.vendor_id == vendor.id:
            issue = "own_product"
        elif product.pk not in visible_ids:
            issue = "unavailable"
        elif product.quantity <= 0:
            issue = "out_of_stock"
        elif item.quantity > product.quantity:
            issue = "insufficient_stock"
        else:
            issue = None
        lines.append(
            CartLine(
                item=item,
                product=product,
                quantity=item.quantity,
                available_quantity=max(product.quantity, 0),
                issue=issue,
            )
        )
    return lines


def _get_purchasable_product(user, product_id):
    try:
        product = Product.objects.select_related("vendor").get(pk=int(product_id))
    except (Product.DoesNotExist, TypeError, ValueError):
        raise CartError("This product no longer exists.", "not_found")

    vendor = _vendor_of(user)
    if vendor and product.vendor_id == vendor.id:
        raise CartError("You can't buy your own product.", "own_product")
    if not Product.objects.visible().filter(pk=product.pk).exists():
        raise CartError("This product is no longer available.", "unavailable")
    if product.quantity <= 0:
        raise CartError("This product is out of stock.", "out_of_stock")
    return product


def _parse_quantity(quantity):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise CartError("Quantity must be a whole number.", "invalid_quantity")
    if quantity < 1:
        raise CartError("Quantity must be at least 1.", "invalid_quantity")
    return quantity


def _cap_message(product):
    return f"Only {product.quantity} of this item left in stock."


def add_to_cart(user, product_id, quantity=1):
    """Add ``quantity`` units, merging with any quantity already in the cart."""
    quantity = _parse_quantity(quantity)
    product = _get_purchasable_product(user, product_id)

    with transaction.atomic():
        item, created = CartItem.objects.select_for_update().get_or_create(
            user=user, product=product, defaults={"quantity": quantity}
        )
        new_quantity = quantity if created else item.quantity + quantity
        limit = min(product.quantity, MAX_QUANTITY_PER_ITEM)
        if new_quantity > limit:
            if created:
                item.delete()
            raise CartError(_cap_message(product), "insufficient_stock")
        if not created:
            item.quantity = new_quantity
            item.save(update_fields=["quantity", "updated_at"])
    return item


def set_cart_quantity(user, product_id, quantity):
    quantity = _parse_quantity(quantity)
    try:
        item = CartItem.objects.select_related("product").get(user=user, product_id=product_id)
    except CartItem.DoesNotExist:
        raise CartError("This item is no longer in your cart.", "not_in_cart")

    product = item.product
    if quantity > item.quantity:
        # Only increases need the product to be purchasable; reducing an
        # unavailable item's quantity is always allowed.
        _get_purchasable_product(user, product.pk)
        if quantity > min(product.quantity, MAX_QUANTITY_PER_ITEM):
            raise CartError(_cap_message(product), "insufficient_stock")
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def change_cart_quantity(user, product_id, action):
    if action not in ("increase", "decrease"):
        raise CartError("Action must be 'increase' or 'decrease'.", "invalid_action")
    try:
        item = CartItem.objects.get(user=user, product_id=product_id)
    except (CartItem.DoesNotExist, ValueError):
        raise CartError("This item is no longer in your cart.", "not_in_cart")

    if action == "decrease" and item.quantity <= 1:
        item.delete()
        return None
    delta = 1 if action == "increase" else -1
    return set_cart_quantity(user, product_id, item.quantity + delta)


def remove_from_cart(user, product_id):
    CartItem.objects.filter(user=user, product_id=product_id).delete()


def cart_count(user):
    return sum(CartItem.objects.filter(user=user).values_list("quantity", flat=True))


# ── Checkout ────────────────────────────────────────────────────────────────

ISSUE_MESSAGES = {
    "own_product": "is your own product",
    "unavailable": "is no longer available",
    "out_of_stock": "is out of stock",
    "insufficient_stock": "doesn't have enough stock",
}


def _build_split(order_lines, fee):
    """Flat split: each vendor gets their item total, the platform gets the fee
    plus anything owed to vendors without a settlement account."""
    vendor_totals = {}
    unsplit_kobo = 0
    for product, quantity in order_lines:
        line_kobo = product.price * quantity * 100
        code = (product.vendor.subaccount_code or "").strip()
        if code.startswith("ACCT_"):
            vendor_totals[code] = vendor_totals.get(code, 0) + line_kobo
        else:
            unsplit_kobo += line_kobo
            logger.warning(
                "Vendor %s has no Paystack subaccount; NGN %s will settle to the platform",
                product.vendor_id,
                line_kobo / 100,
            )

    admin_subaccount = (getattr(settings, "ADMIN_SUBACCOUNT_CODE", "") or "").strip()
    if admin_subaccount and not admin_subaccount.startswith("ACCT_"):
        logger.error("ADMIN_SUBACCOUNT_CODE is misconfigured; ignoring it")
        admin_subaccount = ""

    shares = [{"subaccount": code, "share": share} for code, share in vendor_totals.items()]
    if admin_subaccount:
        shares.append(
            {"subaccount": admin_subaccount, "share": fee * 100 + unsplit_kobo}
        )
    if not shares:
        return None

    split = {"type": "flat", "bearer_type": "account", "subaccounts": shares}
    if admin_subaccount:
        split["bearer_type"] = "subaccount"
        split["bearer_subaccount"] = admin_subaccount
    return split


def start_checkout(user, *, first_name, last_name, phone, pickup_location):
    """Create a pending order for the user's cart and open a Paystack payment.

    The order is persisted *before* contacting Paystack so a webhook can never
    arrive for a payment we have no record of.
    """
    lines = get_cart_lines(user)
    if not lines:
        raise CheckoutError("Your cart is empty.", "empty_cart")

    problems = [
        {
            "product_id": line.product.pk,
            "title": line.product.title,
            "issue": line.issue,
            "available_quantity": line.available_quantity,
        }
        for line in lines
        if line.issue
    ]
    if problems:
        first = problems[0]
        raise CheckoutError(
            f"“{first['title']}” {ISSUE_MESSAGES[first['issue']]}. "
            "Update your cart to continue.",
            "cart_needs_attention",
            problems,
        )

    subtotal = sum(line.line_total for line in lines)
    fee = calculate_service_fee(subtotal)
    reference = uuid.uuid4().hex[:20]

    with transaction.atomic():
        order = Order.objects.create(
            created_by=user,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            pickup_location=pickup_location,
            total_cost=subtotal,
            service_fee=fee,
            ref=reference,
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=line.product,
                    quantity=line.quantity,
                    price=line.line_total,
                )
                for line in lines
            ]
        )
        payment = Payment.objects.create(
            user=user,
            order=order,
            ref=reference,
            amount=Decimal(subtotal + fee),
            status=Payment.PENDING,
        )

    try:
        data = paystack.initialize_transaction(
            email=user.email,
            amount_kobo=(subtotal + fee) * 100,
            reference=reference,
            callback_url=f"{settings.FRONTEND_URL}/success",
            metadata={"type": "order", "order_ref": reference},
            split=_build_split([(line.product, line.quantity) for line in lines], fee),
        )
    except paystack.PaystackError:
        payment.status = Payment.FAILED
        payment.save(update_fields=["status"])
        raise

    payment.paystack_response = {"initialize": data}
    payment.save(update_fields=["paystack_response"])
    logger.info("Checkout %s started: subtotal=%s fee=%s", reference, subtotal, fee)
    return {
        "authorization_url": data["authorization_url"],
        "access_code": data.get("access_code"),
        "reference": reference,
        "subtotal": subtotal,
        "service_fee": fee,
        "total": subtotal + fee,
    }


# ── Payment confirmation ────────────────────────────────────────────────────


def _send_order_emails(order_id):
    order = Order.objects.get(pk=order_id)
    if not send_receipt_email(order):
        logger.error("Receipt email failed for order %s", order.ref)
    if not send_vendor_order_notification(order):
        logger.error("Vendor notification failed for order %s", order.ref)


def confirm_order_payment(reference, transaction_data=None):
    """Apply a Paystack transaction outcome to its order exactly once.

    Safe to call from the buyer's redirect and the webhook concurrently: the
    payment row is locked, already-paid payments are returned untouched, and
    the charged amount must match what we asked for.

    Returns the ``Payment`` (refreshed) or ``None`` if the reference is not an
    order payment.
    """
    if transaction_data is None:
        transaction_data = paystack.verify_transaction(reference)

    with transaction.atomic():
        try:
            payment = (
                Payment.objects.select_for_update()
                .select_related("order")
                .get(ref=reference)
            )
        except Payment.DoesNotExist:
            return None

        if payment.status == Payment.PAID:
            return payment

        order = payment.order
        status = transaction_data.get("status")
        if status == "success":
            expected_kobo = order.amount_due * 100
            paid_kobo = int(transaction_data.get("amount") or 0)
            currency = transaction_data.get("currency", "NGN")
            if paid_kobo != expected_kobo or currency != "NGN":
                logger.critical(
                    "Payment %s amount mismatch: expected %s kobo NGN, got %s kobo %s",
                    reference,
                    expected_kobo,
                    paid_kobo,
                    currency,
                )
                payment.status = Payment.FAILED
                payment.paystack_response = {
                    **(payment.paystack_response or {}),
                    "verify": transaction_data,
                }
                payment.save(update_fields=["status", "paystack_response"])
                return payment

            # Claim the payment with a conditional UPDATE: of two concurrent
            # confirmations (redirect + webhook) exactly one sees a row
            # change, on every database backend including SQLite.
            claimed = (
                Payment.objects.filter(pk=payment.pk)
                .exclude(status=Payment.PAID)
                .update(
                    status=Payment.PAID,
                    paystack_response={
                        **(payment.paystack_response or {}),
                        "verify": transaction_data,
                    },
                )
            )
            if not claimed:
                payment.refresh_from_db()
                return payment
            payment.refresh_from_db()

            order.is_paid = True
            order.paid_at = timezone.now()
            order.save(update_fields=["is_paid", "paid_at"])

            items = list(order.items.select_related("product"))
            for item in items:
                if not item.product.reduce_stock(item.quantity):
                    # Someone else bought the remaining stock between checkout
                    # and payment. The buyer has paid, so keep the order and
                    # flag it for the vendor/support to resolve.
                    logger.error(
                        "Order %s oversold product %s (wanted %s)",
                        reference,
                        item.product_id,
                        item.quantity,
                    )
                    item.product.reduce_stock(item.product.quantity)

            CartItem.objects.filter(
                user=payment.user_id, product_id__in=[item.product_id for item in items]
            ).delete()
            transaction.on_commit(lambda: _send_order_emails(order.pk))
            logger.info("Order %s paid", reference)
        elif status in FINAL_FAILURE_STATUSES:
            payment.status = Payment.FAILED
            payment.save(update_fields=["status"])
        # Any other status (abandoned, ongoing, pending) may still succeed;
        # leave the payment pending so a later webhook can complete it.
        return payment


# ── Serialisation helpers shared by order endpoints ─────────────────────────


def order_payload(order, reviews_by_product=None):
    reviews_by_product = reviews_by_product or {}
    items = []
    for item in order.items.all():
        product = item.product
        review = reviews_by_product.get(product.pk)
        items.append(
            {
                "id": item.pk,
                "product": {
                    "id": product.pk,
                    "title": product.title,
                    "slug": product.slug,
                    "category_slug": product.category.slug,
                    "thumbnail": product.get_thumbnail(),
                    "unit_price": item.price // item.quantity if item.quantity else item.price,
                },
                "quantity": item.quantity,
                "price": item.price,
                "fulfilled": item.fulfilled,
                "vendor": {"id": product.vendor_id, "store_name": product.vendor.store_name},
                "my_review": (
                    {
                        "id": review.pk,
                        "rating": review.rating,
                        "text": review.text,
                        "created_date": review.created_date.isoformat(),
                    }
                    if review
                    else None
                ),
            }
        )
    return {
        "ref": order.ref,
        "subtotal": order.total_cost or 0,
        "service_fee": order.service_fee,
        "total": order.amount_due,
        "is_paid": order.is_paid,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "created_at": order.created_at.isoformat(),
        "pickup_location": order.pickup_location,
        "pickup_location_display": order.get_pickup_location_display(),
        "fulfilled": bool(items) and all(item["fulfilled"] for item in items),
        "items": items,
    }


def orders_with_items():
    return Order.objects.prefetch_related(
        Prefetch(
            "items",
            queryset=OrderItem.objects.select_related(
                "product", "product__vendor", "product__category"
            ),
        )
    )


def reviews_by_product_for(user, orders):
    product_ids = {item.product_id for order in orders for item in order.items.all()}
    return {
        review.product_id: review
        for review in Review.objects.filter(author=user, product_id__in=product_ids)
    }
