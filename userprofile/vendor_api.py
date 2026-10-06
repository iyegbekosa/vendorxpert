"""Vendor endpoints: onboarding, public storefronts, store management,
listings, orders, reviews, plans and KPIs."""

import logging

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from store.models import OrderItem, Product, Review
from store.pagination import StandardResultsPagination
from store.serializers import ProductSerializer, ProductWriteSerializer, with_rating_stats

from .email_utils import send_vendor_welcome_email
from .models import VendorPlan, VendorProfile, selling_access_q
from .permissions import CanSell, IsVendor, can_create_product
from .serializers import (
    VendorListSerializer,
    VendorPlanSerializer,
    VendorRegisterSerializer,
    VendorUpdateSerializer,
    store_details_payload,
    vendor_subscription_payload,
)
from .services import get_vendor_kpis

logger = logging.getLogger(__name__)


def _error(message, http_status, code=None):
    body = {"error": message}
    if code:
        body["code"] = code
    return Response(body, status=http_status)


def _review_payload(review, include_author_id=False):
    author = review.author
    author_data = {"name": (author.first_name or "").strip() or author.user_name}
    if include_author_id:
        author_data["id"] = author.pk
    return {
        "id": review.pk,
        "product": {
            "id": review.product.pk,
            "title": review.product.title,
            "slug": review.product.slug,
        },
        "author": author_data,
        "rating": review.rating,
        "text": review.text,
        "created_at": review.created_date,
    }


def _rating_summary(reviews):
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


# ── Onboarding ──────────────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def register_vendor_api(request):
    """Turn the signed-in buyer into a vendor with a 30-day free trial."""
    existing = getattr(request.user, "vendor_profile", None)
    if existing is not None:
        if existing.subaccount_code:
            return _error("You're already a vendor.", status.HTTP_409_CONFLICT, "already_vendor")
        # A previous attempt failed half-way (Paystack rejected the bank
        # details). Clear it so the user can retry with corrected details.
        with transaction.atomic():
            existing.delete()
            request.user.is_vendor = False
            request.user.save(update_fields=["is_vendor"])
        request.user._state.fields_cache.pop("vendor_profile", None)

    serializer = VendorRegisterSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    vendor = serializer.save()

    if not send_vendor_welcome_email(vendor):
        logger.error("Vendor welcome email failed for vendor %s", vendor.pk)

    return Response(
        {
            "vendor_id": vendor.pk,
            "is_vendor": True,
            "store_details": store_details_payload(vendor),
            "message": "Your store is ready. Your 30-day free trial has started.",
        },
        status=status.HTTP_201_CREATED,
    )


# ── Public storefronts ──────────────────────────────────────────────────────


def _vendors_with_stats():
    approved = Q(product__comments__approved_review=True)
    listed = Q(product__in=Product.objects.purchasable())
    return VendorProfile.objects.annotate(
        listed_product_count=Count("product", filter=listed, distinct=True),
        avg_rating=Avg("product__comments__rating", filter=approved),
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def vendors_list_api(request):
    """Vendors currently selling, with optional ``search``."""
    vendors = _vendors_with_stats().filter(selling_access_q())
    term = (request.GET.get("search") or "").strip()
    if term:
        vendors = vendors.filter(
            Q(store_name__icontains=term) | Q(store_description__icontains=term)
        )
    vendors = vendors.select_related("user").order_by("-listed_product_count", "-id")

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(vendors, request)
    return paginator.get_paginated_response(VendorListSerializer(page, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def vendor_detail_api(request, pk):
    """A vendor's public storefront: profile, rating and in-stock listings."""
    vendor = get_object_or_404(_vendors_with_stats().select_related("user"), pk=pk)
    is_selling = vendor.has_selling_access()

    products = (
        with_rating_stats(
            Product.objects.purchasable().filter(vendor=vendor).select_related("vendor", "category")
        ).order_by("-featured", "-created_at")
        if is_selling
        else Product.objects.none()
    )
    reviews = Review.objects.filter(product__vendor=vendor, approved_review=True)

    data = VendorListSerializer(vendor).data
    data.update(
        {
            "is_selling": is_selling,
            "member_since": vendor.subscription_start,
            "rating": _rating_summary(reviews),
            "products": ProductSerializer(products, many=True).data,
        }
    )
    return Response(data)


@api_view(["GET"])
@permission_classes([AllowAny])
def vendor_reviews_public_api(request, vendor_id):
    vendor = get_object_or_404(VendorProfile, pk=vendor_id)
    reviews = (
        Review.objects.filter(product__vendor=vendor, approved_review=True)
        .select_related("product", "author")
        .order_by("-created_date")
    )
    rating = request.GET.get("rating", "")
    if rating.isdigit() and 1 <= int(rating) <= 5:
        reviews = reviews.filter(rating=int(rating))

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(reviews, request)
    return paginator.get_paginated_response([_review_payload(review) for review in page])


@api_view(["GET"])
@permission_classes([AllowAny])
def vendor_plans_api(request):
    plans = VendorPlan.objects.filter(is_active=True).order_by("price")
    return Response(VendorPlanSerializer(plans, many=True).data)


# ── Store management ────────────────────────────────────────────────────────


def _my_store_payload(vendor):
    reviews = Review.objects.filter(product__vendor=vendor, approved_review=True)
    stats = reviews.aggregate(average=Avg("rating"), total=Count("id"))
    user = vendor.user
    return {
        "vendor_id": vendor.pk,
        "vendor_name": f"{user.first_name} {user.last_name}".strip() or user.user_name,
        **store_details_payload(vendor),
        "store_logo": vendor.store_logo.url if vendor.store_logo else None,
        "average_rating": round(stats["average"] or 0, 1),
        "total_reviews": stats["total"],
        "product_count": Product.objects.filter(vendor=vendor).exclude(status=Product.DELETED).count(),
    }


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated, IsVendor])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def my_store_api(request):
    vendor = request.user.vendor_profile
    if request.method in ("PUT", "PATCH"):
        serializer = VendorUpdateSerializer(vendor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        vendor.refresh_from_db()
    return Response(_my_store_payload(vendor))


# Older clients call this path; it behaves like PATCH /api/my-store/.
update_vendor_api = my_store_api


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def my_subscription_status_api(request):
    vendor = request.user.vendor_profile
    plan = vendor.plan
    product_count = Product.objects.filter(vendor=vendor).exclude(status=Product.DELETED).count()
    max_allowed = plan.max_products if plan else None
    return Response(
        {
            **vendor_subscription_payload(vendor),
            "subscription_start": vendor.subscription_start,
            "is_active": vendor.has_selling_access(),
            "days_remaining": vendor.get_subscription_days_remaining(),
            "in_grace_period": vendor.is_in_grace_period(),
            "has_recurring_billing": bool(vendor.paystack_subscription_code)
            and vendor.subscription_status in ("active", "grace"),
            "pending_payment_reference": vendor.pending_ref,
            "plan": VendorPlanSerializer(plan).data if plan else None,
            "scheduled_plan": (
                VendorPlanSerializer(vendor.scheduled_plan).data if vendor.scheduled_plan else None
            ),
            "product_usage": {
                "current_count": product_count,
                "max_allowed": max_allowed,
                "remaining": None if max_allowed is None else max(0, max_allowed - product_count),
            },
        }
    )


# ── Listings ────────────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def my_products_api(request):
    """All of the vendor's own listings, including sold-out ones, so they can restock."""
    vendor = request.user.vendor_profile
    products = (
        with_rating_stats(
            Product.objects.filter(vendor=vendor)
            .exclude(status=Product.DELETED)
            .select_related("vendor", "category")
        )
        .order_by("-created_at")
    )
    status_filter = request.GET.get("stock")
    if status_filter == "out":
        products = products.filter(quantity=0)
    elif status_filter == "in":
        products = products.filter(quantity__gt=0)

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(products, request)
    return paginator.get_paginated_response(ProductSerializer(page, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, CanSell])
@parser_classes([MultiPartParser, FormParser])
def add_product_api(request):
    vendor = request.user.vendor_profile
    if not can_create_product(vendor):
        limit = vendor.plan.max_products if vendor.plan else 0
        return _error(
            f"Your plan allows {limit} listings. Upgrade your plan or remove a listing to add more.",
            status.HTTP_403_FORBIDDEN,
            "product_limit_reached",
        )
    serializer = ProductWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    product = serializer.save(vendor=vendor)
    return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated, CanSell])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def edit_product_api(request, pk):
    product = get_object_or_404(
        Product.objects.exclude(status=Product.DELETED),
        pk=pk,
        vendor=request.user.vendor_profile,
    )
    serializer = ProductWriteSerializer(product, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    product = serializer.save()
    return Response(ProductSerializer(product).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsVendor])
def delete_product_api(request, pk):
    """Soft-delete: the listing disappears but past orders keep their history."""
    product = get_object_or_404(
        Product.objects.exclude(status=Product.DELETED),
        pk=pk,
        vendor=request.user.vendor_profile,
    )
    Product.objects.filter(pk=product.pk).update(status=Product.DELETED)
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Orders ──────────────────────────────────────────────────────────────────


def _vendor_order_item_payload(item):
    order = item.order
    return {
        "id": item.pk,
        "order_ref": order.ref,
        "product_id": item.product_id,
        "product_title": item.product.title,
        "product_thumbnail": item.product.get_thumbnail(),
        "quantity": item.quantity,
        "price": item.price,
        "fulfilled": item.fulfilled,
        "customer_name": f"{order.first_name} {order.last_name}".strip(),
        "phone": str(order.phone),
        "pickup_location": order.pickup_location,
        "pickup_location_display": order.get_pickup_location_display(),
        "paid_at": order.paid_at or order.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def vendor_order_list_api(request):
    """Paid order lines for this vendor. Unpaid checkouts are never shown, so
    vendors can't hand over goods for orders that were not paid for."""
    vendor = request.user.vendor_profile
    items = OrderItem.objects.filter(product__vendor=vendor, order__is_paid=True)

    kpis = items.aggregate(
        total_orders=Count("id"),
        pending_orders=Count("id", filter=Q(fulfilled=False)),
        completed_orders=Count("id", filter=Q(fulfilled=True)),
        total_revenue=Sum("price"),
    )
    total = kpis["total_orders"] or 0

    status_filter = request.GET.get("status")
    if status_filter == "pending":
        items = items.filter(fulfilled=False)
    elif status_filter == "fulfilled":
        items = items.filter(fulfilled=True)

    term = (request.GET.get("search") or "").strip()
    if term:
        items = items.filter(
            Q(order__ref__icontains=term)
            | Q(product__title__icontains=term)
            | Q(order__first_name__icontains=term)
            | Q(order__last_name__icontains=term)
        )

    items = items.select_related("order", "product").order_by("fulfilled", "-order__paid_at", "-pk")
    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(items, request)
    response = paginator.get_paginated_response(
        [_vendor_order_item_payload(item) for item in page]
    )
    response.data["kpis"] = {
        "total_orders": total,
        "pending_orders": kpis["pending_orders"] or 0,
        "completed_orders": kpis["completed_orders"] or 0,
        "total_revenue": kpis["total_revenue"] or 0,
        "completion_rate": round((kpis["completed_orders"] or 0) / total * 100, 1) if total else 0,
    }
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def order_detail_api(request, pk):
    vendor = request.user.vendor_profile
    items = list(
        OrderItem.objects.filter(order_id=pk, order__is_paid=True, product__vendor=vendor)
        .select_related("order", "product")
    )
    if not items:
        return _error("Order not found.", status.HTTP_404_NOT_FOUND)
    order = items[0].order
    return Response(
        {
            "order_id": order.pk,
            "ref": order.ref,
            "customer_name": f"{order.first_name} {order.last_name}".strip(),
            "phone": str(order.phone),
            "pickup_location": order.pickup_location,
            "pickup_location_display": order.get_pickup_location_display(),
            "paid_at": order.paid_at or order.created_at,
            "items": [_vendor_order_item_payload(item) for item in items],
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsVendor])
def toggle_fulfillment_api(request, pk):
    """Mark one paid order line as handed over (or not).

    Send ``{"fulfilled": true|false}`` to set the state explicitly; without a
    body the state is toggled (legacy behaviour).
    """
    item = get_object_or_404(
        OrderItem.objects.select_related("order", "product"),
        pk=pk,
        product__vendor=request.user.vendor_profile,
        order__is_paid=True,
    )
    requested = request.data.get("fulfilled")
    if isinstance(requested, bool):
        item.fulfilled = requested
    else:
        item.fulfilled = not item.fulfilled
    item.save(update_fields=["fulfilled"])
    return Response(_vendor_order_item_payload(item))


# ── Reviews & KPIs ──────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def vendor_reviews_api(request):
    vendor = request.user.vendor_profile
    all_reviews = Review.objects.filter(product__vendor=vendor, approved_review=True)
    reviews = all_reviews.select_related("product", "author").order_by("-created_date")

    rating = request.GET.get("rating", "")
    if rating.isdigit() and 1 <= int(rating) <= 5:
        reviews = reviews.filter(rating=int(rating))

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(reviews, request)
    response = paginator.get_paginated_response(
        [_review_payload(review) for review in page]
    )
    response.data["rating_stats"] = _rating_summary(all_reviews)
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def vendor_kpis_api(request):
    return Response(get_vendor_kpis(request.user.vendor_profile))
