"""Vendor subscription endpoints: subscribe, change plan, verify, cancel, history."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from store import paystack
from store.pagination import StandardResultsPagination

from . import services
from .models import SubscriptionHistory, VendorPlan
from .permissions import IsVendor
from .serializers import SubscriptionHistorySerializer, SubscriptionInitiateSerializer

logger = logging.getLogger(__name__)


def _error(message, http_status, code=None):
    body = {"error": message}
    if code:
        body["code"] = code
    return Response(body, status=http_status)


def _selected_plan(request):
    serializer = SubscriptionInitiateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return VendorPlan.objects.get(pk=serializer.validated_data["plan_id"], is_active=True)


def _run(action):
    try:
        return Response(action())
    except services.SubscriptionError as exc:
        return _error(exc.message, status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code)
    except paystack.PaystackError as exc:
        return _error(
            f"{exc.message} You haven't been charged.",
            status.HTTP_502_BAD_GATEWAY,
            "payment_provider_error",
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsVendor])
def resubscribe_api(request):
    """Pay for a plan (first subscription, after a trial, or after lapsing)."""
    plan = _selected_plan(request)
    return _run(lambda: services.start_subscription_payment(request.user.vendor_profile, plan))


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsVendor])
def change_plan_api(request):
    plan = _selected_plan(request)
    return _run(lambda: services.change_plan(request.user.vendor_profile, plan))


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsVendor])
def verify_subscription_payment_api(request):
    """Confirm a subscription payment when the vendor returns from Paystack."""
    reference = (request.data.get("reference") or "").strip()
    if not reference:
        return _error("Payment reference is required.", status.HTTP_400_BAD_REQUEST)
    vendor = request.user.vendor_profile
    try:
        payment_status = services.verify_subscription_payment(vendor, reference)
    except services.SubscriptionError as exc:
        return _error(exc.message, status.HTTP_404_NOT_FOUND, exc.code)
    except paystack.PaystackError:
        payment_status = "pending"
    return Response({"status": payment_status})


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsVendor])
def cancel_subscription_api(request):
    vendor = request.user.vendor_profile

    def cancel():
        services.cancel_subscription(vendor)
        expiry = vendor.subscription_expiry
        return {
            "message": (
                f"Your subscription won't renew. You keep full access until {expiry:%d %b %Y}."
                if expiry
                else "Your subscription won't renew."
            )
        }

    return _run(cancel)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsVendor])
def subscription_history_api(request):
    history = SubscriptionHistory.objects.filter(
        vendor=request.user.vendor_profile
    ).select_related("previous_plan", "new_plan", "vendor")

    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(history.order_by("-created_at"), request)
    return paginator.get_paginated_response(SubscriptionHistorySerializer(page, many=True).data)
