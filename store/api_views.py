"""Buyer-facing marketplace API: catalogue, reviews, cart, checkout and orders."""

import logging

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from operations.config import get_settings, pickup_locations
from userprofile.bank_codes import VALID_BANK_CODES

from . import paystack, services
from .models import Category, Order, Payment, Product, Review
from .pagination import StandardResultsPagination
from .serializers import (
    CategorySerializer,
    CheckoutSerializer,
    ProductSerializer,
    ReviewDetailSerializer,
    ReviewSerializer,
    with_rating_stats,
)

logger = logging.getLogger(__name__)

PRODUCT_ORDERINGS = {
    "newest": "-created_at",
    "oldest": "created_at",
    "price_low": "price",
    "price_high": "-price",
    "rating": "-avg_rating",
    # Legacy values accepted for backwards compatibility.
    "-created_at": "-created_at",
    "created_at": "created_at",
    "price": "price",
    "-price": "-price",
    "-id": "-created_at",
}
BANKS_CACHE_KEY = "paystack:banks:v1"
BANKS_CACHE_SECONDS = 60 * 60 * 12


class BankLookupThrottle(UserRateThrottle):
    scope = "bank_lookup"


def _error(message, http_status, code=None, **extra):
    body = {"error": message, **extra}
    if code:
        body["code"] = code
    return Response(body, status=http_status)


def _product_queryset():
    return with_rating_stats(
        Product.objects.select_related("vendor", "category")
    )


def _paginated_products(request, queryset):
    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(ProductSerializer(page, many=True).data)


# ── Catalogue ───────────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AllowAny])
def categories_list_api(request):
    categories = Category.objects.order_by("title")
    return Response(CategorySerializer(categories, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def products_list_api(request):
    """Paginated in-stock listings.

    Query params: ``search``/``query`` (title, description or store name),
    ``category`` (id or slug), ``vendor`` (id), ``ordering`` and ``page``.
    """
    products = _product_queryset().filter(
        pk__in=Product.objects.purchasable().values("pk")
    )

    term = (request.GET.get("search") or request.GET.get("query") or "").strip()
    if term:
        products = products.filter(
            Q(title__icontains=term)
            | Q(description__icontains=term)
            | Q(vendor__store_name__icontains=term)
        )

    category = (request.GET.get("category") or "").strip()
    if category:
        lookup = {"category_id": category} if category.isdigit() else {"category__slug": category}
        products = products.filter(**lookup)

    vendor_id = (request.GET.get("vendor") or "").strip()
    if vendor_id.isdigit():
        products = products.filter(vendor_id=vendor_id)

    ordering = PRODUCT_ORDERINGS.get(request.GET.get("ordering", ""), "-created_at")
    products = products.order_by("-featured", ordering, "-pk")
    return _paginated_products(request, products)


# ``/api/search/?query=`` is kept for older clients; it is the same listing.
search_api = products_list_api


@api_view(["GET"])
@permission_classes([AllowAny])
def category_detail_api(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = _product_queryset().filter(
        pk__in=Product.objects.purchasable().filter(category=category).values("pk")
    ).order_by("-featured", "-created_at")
    return _paginated_products(request, products)


@api_view(["GET"])
@permission_classes([AllowAny])
def product_detail_api(request, category_slug, slug):
    """A single product. Sold-out products stay viewable so links keep working;
    hidden products are only visible to the vendor who owns them."""
    product = get_object_or_404(
        _product_queryset(), slug=slug, category__slug=category_slug
    )
    vendor = getattr(request.user, "vendor_profile", None) if request.user.is_authenticated else None
    is_owner = vendor is not None and product.vendor_id == vendor.id
    is_visible = Product.objects.visible().filter(pk=product.pk).exists()
    if not is_visible and not is_owner:
        return _error("This product is no longer available.", status.HTTP_404_NOT_FOUND, "unavailable")
    return Response(ProductSerializer(product).data)


# ── Reviews ─────────────────────────────────────────────────────────────────


def _rating_stats(reviews):
    stats = reviews.aggregate(average=Avg("rating"), total=Count("id"))
    counts = {
        int(row["rating"]): row["count"]
        for row in reviews.values("rating").annotate(count=Count("id"))
    }
    return {
        "average_rating": round(stats["average"] or 0, 1),
        "total_reviews": stats["total"],
        "rating_breakdown": {f"{n}_star": counts.get(n, 0) for n in range(5, 0, -1)},
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def get_product_reviews_api(request, pk):
    product = get_object_or_404(Product, pk=pk)
    reviews = Review.objects.filter(product=product, approved_review=True)

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(
        reviews.select_related("author").order_by("-created_date"), request
    )
    response = paginator.get_paginated_response(ReviewDetailSerializer(page, many=True).data)
    response.data["rating_stats"] = _rating_stats(reviews)
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_review_api(request, pk):
    product = get_object_or_404(Product, pk=pk)

    vendor = getattr(request.user, "vendor_profile", None)
    if vendor and product.vendor_id == vendor.id:
        return _error("You can't review your own product.", status.HTTP_403_FORBIDDEN)

    has_purchased = Order.objects.filter(
        created_by=request.user, is_paid=True, items__product=product
    ).exists()
    if not has_purchased:
        return _error(
            "You can review this product after you've bought it.", status.HTTP_403_FORBIDDEN
        )

    if Review.objects.filter(product=product, author=request.user).exists():
        return _error(
            "You've already reviewed this product. You can edit your review instead.",
            status.HTTP_409_CONFLICT,
            "already_reviewed",
        )

    serializer = ReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    review = serializer.save(product=product, author=request.user)
    return Response(ReviewDetailSerializer(review).data, status=status.HTTP_201_CREATED)


@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def edit_review_api(request, review_id):
    review = get_object_or_404(Review, pk=review_id, author=request.user)
    serializer = ReviewSerializer(review, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    review = serializer.save()
    return Response(ReviewDetailSerializer(review).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_review_api(request, review_id):
    review = get_object_or_404(Review, pk=review_id, author=request.user)
    review.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Cart ────────────────────────────────────────────────────────────────────


def _cart_payload(user):
    lines = services.get_cart_lines(user)
    ok_lines = [line for line in lines if not line.issue]
    subtotal = sum(line.line_total for line in ok_lines)
    fee = services.calculate_service_fee(subtotal)
    return {
        "items": [
            {
                "product": {
                    "id": line.product.pk,
                    "title": line.product.title,
                    "slug": line.product.slug,
                    "category_slug": line.product.category.slug,
                    "thumbnail": line.product.get_thumbnail(),
                    "price": line.product.price,
                    "available_quantity": line.available_quantity,
                    "vendor_name": line.product.vendor.store_name,
                },
                "quantity": line.quantity,
                "line_total": line.line_total,
                "issue": line.issue,
            }
            for line in lines
        ],
        "count": sum(line.quantity for line in lines),
        "subtotal": subtotal,
        "service_fee": fee,
        "total": subtotal + fee,
        "can_checkout": bool(lines) and len(ok_lines) == len(lines) and get_settings().accepting_orders,
        "max_quantity_per_item": services.max_quantity_per_item(),
        "pickup_locations": [
            {"value": value, "label": label} for value, label in pickup_locations()
        ],
        "accepting_orders": get_settings().accepting_orders,
    }


def _cart_mutation(request, mutate):
    try:
        mutate()
    except services.CartError as exc:
        return _error(
            exc.message, status.HTTP_400_BAD_REQUEST, exc.code, cart=_cart_payload(request.user)
        )
    return Response(_cart_payload(request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cart_view_api(request):
    return Response(_cart_payload(request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_add_to_cart(request):
    return _cart_mutation(
        request,
        lambda: services.add_to_cart(
            request.user, request.data.get("product_id"), request.data.get("quantity", 1)
        ),
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_change_quantity(request):
    return _cart_mutation(
        request,
        lambda: services.change_cart_quantity(
            request.user, request.data.get("product_id"), request.data.get("action")
        ),
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_set_quantity(request):
    return _cart_mutation(
        request,
        lambda: services.set_cart_quantity(
            request.user, request.data.get("product_id"), request.data.get("quantity")
        ),
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_remove_from_cart(request):
    return _cart_mutation(
        request,
        lambda: services.remove_from_cart(request.user, request.data.get("product_id")),
    )


# ── Checkout & payment ──────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout_api(request):
    serializer = CheckoutSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        result = services.start_checkout(request.user, **serializer.validated_data)
    except services.CheckoutError as exc:
        return _error(
            exc.message,
            status.HTTP_409_CONFLICT if exc.problems else status.HTTP_400_BAD_REQUEST,
            exc.code,
            problems=exc.problems,
            cart=_cart_payload(request.user),
        )
    except paystack.PaystackError as exc:
        return _error(
            f"We couldn't start your payment: {exc.message} You haven't been charged.",
            status.HTTP_502_BAD_GATEWAY,
            "payment_provider_error",
        )
    return Response(result)


def _buyer_order_response(user, order, payment_status):
    orders = list(services.orders_with_items().filter(pk=order.pk))
    reviews = services.reviews_by_product_for(user, orders)
    return {
        "status": payment_status,
        "order": services.order_payload(orders[0], reviews),
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_payment_api(request):
    """Confirm a payment after the buyer returns from Paystack.

    Always answers with ``status`` = ``paid``, ``pending`` or ``failed`` so the
    client can tell the buyer exactly where their money stands.
    """
    reference = (request.data.get("reference") or "").strip()
    if not reference:
        return _error("Payment reference is required.", status.HTTP_400_BAD_REQUEST)

    payment = Payment.objects.filter(ref=reference, user=request.user).select_related("order").first()
    if payment is None:
        return _error("We couldn't find that payment.", status.HTTP_404_NOT_FOUND, "not_found")

    if payment.status != Payment.PAID:
        try:
            payment = services.confirm_order_payment(reference) or payment
        except paystack.PaystackError:
            # Paystack is unreachable; the webhook will still complete the
            # order. Tell the buyer it is pending rather than failed.
            logger.warning("Could not verify payment %s with Paystack", reference)

    return Response(_buyer_order_response(request.user, payment.order, payment.status))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def order_history_api(request):
    orders = services.orders_with_items().filter(
        created_by=request.user, is_paid=True
    ).order_by("-paid_at", "-created_at")

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(orders, request)
    reviews = services.reviews_by_product_for(request.user, page)
    return paginator.get_paginated_response(
        [services.order_payload(order, reviews) for order in page]
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buyer_order_detail_api(request, ref):
    order = get_object_or_404(Order, ref=ref, created_by=request.user)
    payment = order.payments.order_by("-created_at").first()
    payment_status = payment.status if payment else (Payment.PAID if order.is_paid else Payment.PENDING)
    return Response(_buyer_order_response(request.user, order, payment_status))


# ── Banking (vendor onboarding) ─────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AllowAny])
def get_banks_api(request):
    """Nigerian banks supported for vendor payouts (cached; changes rarely)."""
    banks = cache.get(BANKS_CACHE_KEY)
    if banks is None:
        try:
            data = paystack.list_banks()
        except paystack.PaystackError:
            return _error(
                "We couldn't load the list of banks. Please try again shortly.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        banks = sorted(
            (
                {"name": bank["name"], "code": bank["code"]}
                for bank in data
                if bank.get("active", True) and bank.get("code") in VALID_BANK_CODES
            ),
            key=lambda bank: bank["name"],
        )
        cache.set(BANKS_CACHE_KEY, banks, BANKS_CACHE_SECONDS)
    return Response({"data": banks})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([BankLookupThrottle])
def verify_account_api(request):
    """Resolve an account number to the holder's name before vendor signup."""
    account_number = str(request.data.get("account_number", "")).strip()
    bank_code = str(request.data.get("bank_code", "")).strip()

    if not account_number.isdigit() or len(account_number) != 10:
        return _error("Account number must be exactly 10 digits.", status.HTTP_400_BAD_REQUEST)
    if bank_code not in VALID_BANK_CODES:
        return _error("Choose your bank from the list.", status.HTTP_400_BAD_REQUEST)

    try:
        data = paystack.resolve_account(account_number, bank_code)
    except paystack.PaystackError:
        return _error(
            "We couldn't verify this account. Check the number and bank, then try again.",
            status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        {
            "data": {
                "account_number": data.get("account_number", account_number),
                "account_name": data.get("account_name", ""),
            }
        }
    )
