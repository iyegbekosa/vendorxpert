from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
import requests
import uuid
import logging
from datetime import timedelta
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .serializers import (
    SubscriptionInitiateSerializer,
    ChangePlanSerializer,
)
from .models import VendorProfile, VendorPlan
from store.pagination import StandardResultsPagination
from .permissions import VendorFeatureAccess
from .auth_api import SUBSCRIPTION_RENEWAL_DAYS

logger = logging.getLogger(__name__)


@swagger_auto_schema(
    method="post",
    operation_summary="Initialize/Renew Subscription",
    operation_description="Initialize a new subscription or renew/upgrade existing subscription. Returns Paystack payment URL.",
    request_body=SubscriptionInitiateSerializer,
    responses={
        200: openapi.Response(
            description="Payment initialization successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "authorization_url": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Paystack payment URL"
                    ),
                    "access_code": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Paystack access code"
                    ),
                    "reference": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Payment reference"
                    ),
                },
            ),
        ),
        400: openapi.Response(
            description="Bad request - Invalid plan or missing data",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "error": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Error message"
                    )
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        404: openapi.Response(description="Plan not found"),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resubscribe_api(request):
    """
    Initialize or renew a vendor subscription.

    This endpoint handles subscription initiation and renewal by:
    1. Validating the selected plan
    2. Creating a Paystack payment session
    3. Returning payment URL for completion
    """
    user = request.user

    try:
        vendor = user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    # Validate request data using serializer
    serializer = SubscriptionInitiateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    plan_id = serializer.validated_data["plan_id"]

    try:
        selected_plan = VendorPlan.objects.get(id=plan_id, is_active=True)
    except VendorPlan.DoesNotExist:
        return Response({"error": "Invalid or inactive plan."}, status=status.HTTP_404_NOT_FOUND)

    # Handle free plans
    if selected_plan.price == 0:
        vendor.plan = selected_plan
        vendor.subscription_status = "active"
        vendor.subscription_start = timezone.now()
        vendor.subscription_expiry = timezone.now() + timedelta(days=SUBSCRIPTION_RENEWAL_DAYS)
        vendor.save()
        return Response(
            {
                "message": "Successfully subscribed to free plan",
                "plan": selected_plan.name,
                "expiry": vendor.subscription_expiry.isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    # Handle paid plans
    ref = str(uuid.uuid4()).replace("-", "")[:20]

    callback_url = (
        f"{request.scheme}://{request.get_host()}{reverse('paystack_callback')}"
    )

    payload = {
        "email": user.email,
        "plan": selected_plan.paystack_plan_code,
        "reference": ref,
        "callback_url": callback_url,
    }

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"{settings.PAYSTACK_BASE_URL}/transaction/initialize", json=payload, headers=headers
    )

    try:
        res_data = response.json()
    except ValueError:
        return Response({"error": "Invalid response from Paystack"}, status=502)

    if response.status_code == 200 and res_data.get("status"):
        vendor.pending_ref = ref
        vendor.plan = selected_plan
        vendor.save()

        return Response(
            {
                "authorization_url": res_data["data"]["authorization_url"],
                "access_code": res_data["data"]["access_code"],
                "reference": res_data["data"]["reference"],
            },
            status=status.HTTP_200_OK,
        )
    else:
        return Response(
            {"error": res_data.get("message", "Paystack error")}, status=status.HTTP_400_BAD_REQUEST
        )


@swagger_auto_schema(
    method="post",
    operation_summary="Cancel Subscription",
    operation_description="Cancel the vendor's active subscription. The subscription will remain active until the current billing period ends.",
    responses={
        200: openapi.Response(
            description="Subscription cancelled successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Success message"
                    )
                },
            ),
        ),
        400: openapi.Response(
            description="Subscription already cancelled or other error",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Error message"
                    )
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        502: openapi.Response(description="Failed to cancel subscription on Paystack"),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_subscription_api(request):
    user = request.user

    try:
        vendor = user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    if vendor.subscription_status == "cancelled":
        return Response({"error": "Subscription already cancelled."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    subscription_code = getattr(vendor, "paystack_subscription_code", None)
    if subscription_code:
        url = f"{settings.PAYSTACK_BASE_URL}/subscription/disable"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"code": subscription_code, "token": vendor.user.email}

        res = requests.post(url, json=payload, headers=headers)
        if res.status_code != 200:
            return Response(
                {"error": "Failed to cancel subscription on Paystack"}, status=502
            )

    # Update vendor status
    vendor.subscription_status = "cancelled"
    vendor.save()

    return Response({"message": "Subscription cancelled successfully."}, status=status.HTTP_200_OK)


@swagger_auto_schema(
    method="post",
    operation_summary="Pause Subscription",
    operation_description="Temporarily pause the vendor's subscription. Vendor maintains access during pause.",
    security=[{"Bearer": []}],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "reason": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Optional reason for pausing subscription",
            )
        },
    ),
    responses={
        200: openapi.Response(
            description="Subscription paused successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "status": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Cannot pause subscription in current state"),
        403: openapi.Response(description="User is not a vendor"),
    },
    tags=["Vendor Subscription"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def pause_subscription_api(request):
    """Pause the vendor's subscription temporarily"""
    try:
        vendor = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    reason = request.data.get("reason", "")

    if vendor.pause_subscription(reason):
        return Response(
            {
                "message": "Subscription paused successfully.",
                "status": vendor.subscription_status,
                "reason": reason,
            },
            status=status.HTTP_200_OK,
        )
    else:
        return Response(
            {
                "error": f"Cannot pause subscription. Current status: {vendor.subscription_status}"
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@swagger_auto_schema(
    method="post",
    operation_summary="Resume Subscription",
    operation_description="Resume a paused subscription and return to active status.",
    security=[{"Bearer": []}],
    responses={
        200: openapi.Response(
            description="Subscription resumed successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "status": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(
            description="Cannot resume subscription in current state"
        ),
        403: openapi.Response(description="User is not a vendor"),
    },
    tags=["Vendor Subscription"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def resume_subscription_api(request):
    """Resume a paused subscription"""
    try:
        vendor = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    if vendor.resume_subscription():
        return Response(
            {
                "message": "Subscription resumed successfully.",
                "status": vendor.subscription_status,
            },
            status=status.HTTP_200_OK,
        )
    else:
        return Response(
            {
                "error": f"Cannot resume subscription. Current status: {vendor.subscription_status}"
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@swagger_auto_schema(
    method="post",
    operation_summary="Change Subscription Plan",
    operation_description="Upgrade or downgrade subscription plan with prorated billing and automatic payment processing.",
    security=[{"Bearer": []}],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "plan_id": openapi.Schema(
                type=openapi.TYPE_INTEGER, description="ID of the new plan to switch to"
            ),
            "immediate": openapi.Schema(
                type=openapi.TYPE_BOOLEAN,
                description="Whether to apply change immediately (true) or at next billing cycle (false)",
                default=False,
            ),
        },
        required=["plan_id"],
    ),
    responses={
        200: openapi.Response(
            description="Plan changed successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "old_plan": openapi.Schema(type=openapi.TYPE_STRING),
                    "new_plan": openapi.Schema(type=openapi.TYPE_STRING),
                    "prorated_amount": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "is_upgrade": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "payment_status": openapi.Schema(type=openapi.TYPE_STRING),
                    "authorization_url": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Payment URL (for upgrades requiring additional payment)",
                    ),
                },
            ),
        ),
        400: openapi.Response(description="Invalid plan or cannot change plan"),
        403: openapi.Response(description="User is not a vendor"),
        404: openapi.Response(description="Plan not found"),
        502: openapi.Response(description="Payment processing error"),
    },
    tags=["Vendor Subscription"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
@transaction.atomic
def change_plan_api(request):
    """Change subscription plan with prorated billing and payment processing"""

    try:
        vendor = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    serializer = ChangePlanSerializer(data=request.data, context={"vendor": vendor})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated_data = serializer.validated_data
    plan_id = validated_data["plan_id"]
    immediate = validated_data["immediate"]

    try:
        new_plan = VendorPlan.objects.get(id=plan_id, is_active=True)
    except VendorPlan.DoesNotExist:
        return Response({"error": "Plan not found or inactive."}, status=status.HTTP_404_NOT_FOUND)

    try:
        result = vendor.change_plan_with_payment(
            new_plan, immediate=immediate, request=request
        )

        if result and result.get("success"):
            response_data = {
                "message": f"Plan {'upgraded' if result['is_upgrade'] else 'downgraded'} successfully.",
                "old_plan": result["old_plan"],
                "new_plan": result["new_plan"],
                "prorated_amount": result["prorated_amount"],
                "is_upgrade": result["is_upgrade"],
                "payment_status": result.get("payment_status", "completed"),
            }

            if result.get("authorization_url"):
                response_data["authorization_url"] = result["authorization_url"]
                response_data["payment_status"] = "payment_required"

            return Response(response_data, status=status.HTTP_200_OK)
        else:
            error_message = (
                result.get("error", "Failed to change plan.")
                if result
                else "Failed to change plan."
            )
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Unexpected error during plan change for vendor {vendor.id}: {e}", exc_info=True)
        return Response(
            {"error": "An unexpected error occurred. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@swagger_auto_schema(
    method="get",
    operation_summary="Get Subscription History",
    operation_description="Get detailed history of all subscription events for the vendor.",
    security=[{"Bearer": []}],
    responses={
        200: openapi.Response(
            description="Subscription history retrieved successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
    },
    tags=["Vendor Subscription"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def subscription_history_api(request):
    """Get vendor's subscription history"""
    try:
        vendor = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    from .models import SubscriptionHistory
    from .serializers import SubscriptionHistorySerializer

    history = SubscriptionHistory.objects.filter(vendor=vendor).order_by("-created_at")

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(history, request)

    serializer = SubscriptionHistorySerializer(result_page, many=True)
    return paginator.get_paginated_response(serializer.data)
