from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.db.models import Count, Q
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
    VendorRegisterSerializer,
    VendorProfileSerializer,
    VendorUpdateSerializer,
    VendorListSerializer,
    Product,
    ProductCreateSerializer,
    VendorOrderDetailSerializer,
    VendorOrderItemSerializer,
    VendorPlanSerializer,
    SubscriptionInitiateSerializer,
    ChangePlanSerializer,
)
from .models import VendorProfile, VendorPlan
from store.models import OrderItem, Order, Review
from .views import get_object_or_404
from store.pagination import StandardResultsPagination
from .permissions import can_create_product, HasActiveSubscription, VendorFeatureAccess
from .email_utils import send_vendor_welcome_email
from .auth_api import _vendor_subscription_payload, _isoformat_or_none, SUBSCRIPTION_RENEWAL_DAYS

logger = logging.getLogger(__name__)


@swagger_auto_schema(
    method="post",
    operation_description="Register the authenticated user as a vendor",
    operation_summary="Register as vendor",
    request_body=VendorRegisterSerializer,
    responses={
        201: openapi.Response(
            description="Vendor successfully registered",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "email": openapi.Schema(type=openapi.TYPE_STRING),
                    "is_vendor": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "refresh": openapi.Schema(type=openapi.TYPE_STRING),
                    "access": openapi.Schema(type=openapi.TYPE_STRING),
                    "vendor_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "store_details": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "store_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "store_logo_url": openapi.Schema(
                                type=openapi.TYPE_STRING, nullable=True
                            ),
                            "store_description": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                            "phone_number": openapi.Schema(
                                type=openapi.TYPE_STRING, nullable=True
                            ),
                            "whatsapp_number": openapi.Schema(
                                type=openapi.TYPE_STRING, nullable=True
                            ),
                            "instagram_handle": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                            "tiktok_handle": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                            "is_verified": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            "subscription_status": openapi.Schema(
                                type=openapi.TYPE_STRING
                            ),
                            "subscription_expiry": openapi.Schema(
                                type=openapi.TYPE_STRING,
                                format="date-time",
                                nullable=True,
                            ),
                        },
                    ),
                },
            ),
        ),
        400: openapi.Response(
            description="Validation errors or user already registered as vendor",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "error": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        401: openapi.Response(description="Authentication required"),
        500: openapi.Response(
            description="Internal server error",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "error": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
    },
    tags=["Vendor Management"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def register_vendor_api(request):
    """
    Register the authenticated user as a vendor.

    Requires authentication. Creates a vendor profile for the current user
    with store details and bank account information for payment processing.
    """
    if hasattr(request.user, "vendor_profile"):
        vendor = request.user.vendor_profile
        if vendor.subaccount_code:
            # Fully registered vendor with a working Paystack subaccount.
            return Response(
                {"error": "User is already registered as a vendor"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Incomplete registration (Paystack setup previously failed and cleanup
        # didn't finish). Clear the orphaned profile so the user can retry.
        logger.info(
            f"Cleaning up incomplete vendor profile {vendor.pk} for user {request.user.id} before retry."
        )
        vendor.delete()
        request.user.is_vendor = False
        request.user.save()
        # Clear Django 4.x's fields_cache for the reverse OneToOne so the
        # serializer's hasattr(request.user, "vendor_profile") does a fresh
        # DB look-up and sees the deletion.
        request.user._state.fields_cache.pop("vendor_profile", None)

    serializer = VendorRegisterSerializer(
        data=request.data, context={"request": request}
    )

    if serializer.is_valid():
        from rest_framework.exceptions import ValidationError as DRFValidationError
        try:
            vendor = serializer.save()
        except DRFValidationError as e:
            return Response(
                {"error": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(
                f"Vendor registration failed for user {request.user.id}: {str(e)}"
            )
            return Response(
                {"error": "Failed to create vendor account. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(request.user)
        access_token = refresh.access_token

        try:
            send_vendor_welcome_email(vendor)
            email_message = "Vendor welcome email sent successfully!"
        except Exception as e:
            logger.error(
                f"Failed to send vendor welcome email to {vendor.user.email}: {str(e)}"
            )
            email_message = "Vendor account created successfully (welcome email failed to send)."

        response_data = {
            "success": True,
            "user_id": request.user.id,
            "email": request.user.email,
            "is_vendor": True,
            "refresh": str(refresh),
            "access": str(access_token),
            "vendor_id": vendor.id,
            "message": f"Vendor account created successfully! {email_message}",
            "store_details": {
                "store_name": vendor.store_name,
                "store_logo_url": (
                    vendor.store_logo.url if getattr(vendor, "store_logo", None) else None
                ),
                "store_description": vendor.store_description,
                "phone_number": str(vendor.phone_number) if vendor.phone_number else None,
                "whatsapp_number": (
                    str(vendor.whatsapp_number) if vendor.whatsapp_number else None
                ),
                "instagram_handle": vendor.instagram_handle,
                "tiktok_handle": vendor.tiktok_handle,
                "is_verified": vendor.is_verified,
                **_vendor_subscription_payload(vendor),
            },
        }

        return Response(response_data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def vendor_detail_api(request, pk):
    try:
        vendor = VendorProfile.objects.get(pk=pk)
    except VendorProfile.DoesNotExist:
        return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = VendorProfileSerializer(vendor)
    return Response(serializer.data)


@swagger_auto_schema(
    method="get",
    operation_description="Get all vendor profiles with pagination",
    security=[],  # Public endpoint - no authentication required
    manual_parameters=[
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "subscription_status",
            openapi.IN_QUERY,
            description="Filter by subscription status (active, expired, grace)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Paginated list of all vendor profiles",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                },
            ),
        )
    },
    tags=["Vendors"],
)
@api_view(["GET"])
def vendors_list_api(request):
    """
    Get all vendor profiles with pagination and optional filtering.

    Returns a paginated list of all vendor profiles.
    Can be filtered by subscription status.
    """
    vendors = VendorProfile.objects.all()

    # Filter by subscription status if provided
    subscription_status = request.GET.get("subscription_status")
    if subscription_status:
        vendors = vendors.filter(subscription_status=subscription_status)

    # Order by newest first
    vendors = vendors.order_by("-id")

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(vendors, request)

    serializer = VendorListSerializer(result_page, many=True)

    return paginator.get_paginated_response(serializer.data)


@swagger_auto_schema(
    method="get",
    operation_description="Get vendor's own store information including store details, average rating, and product count",
    security=[{"Bearer": []}],
    responses={
        200: openapi.Response(
            description="Vendor's store information retrieved successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "vendor_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "vendor_name": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Vendor's full name"
                    ),
                    "store_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "store_description": openapi.Schema(type=openapi.TYPE_STRING),
                    "store_logo": openapi.Schema(
                        type=openapi.TYPE_STRING, nullable=True
                    ),
                    "phone_number": openapi.Schema(
                        type=openapi.TYPE_STRING, nullable=True
                    ),
                    "whatsapp_number": openapi.Schema(
                        type=openapi.TYPE_STRING, nullable=True
                    ),
                    "instagram_handle": openapi.Schema(type=openapi.TYPE_STRING),
                    "tiktok_handle": openapi.Schema(type=openapi.TYPE_STRING),
                    "is_verified": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "average_rating": openapi.Schema(
                        type=openapi.TYPE_NUMBER, description="Average rating (0.0-5.0)"
                    ),
                    "total_reviews": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "product_count": openapi.Schema(
                        type=openapi.TYPE_INTEGER, description="Total active products"
                    ),
                    "subscription_status": openapi.Schema(type=openapi.TYPE_STRING),
                    "subscription_expiry": openapi.Schema(
                        type=openapi.TYPE_STRING, format="date-time", nullable=True
                    ),
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Products"],
)
@swagger_auto_schema(
    method="put",
    operation_description="Update vendor store details like name, description, contact information",
    security=[{"Bearer": []}],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "store_name": openapi.Schema(
                type=openapi.TYPE_STRING, description="Store name"
            ),
            "store_description": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Store description (max 500 chars)",
            ),
            "phone_number": openapi.Schema(
                type=openapi.TYPE_STRING, description="Contact phone number"
            ),
            "whatsapp_number": openapi.Schema(
                type=openapi.TYPE_STRING, description="WhatsApp number"
            ),
            "instagram_handle": openapi.Schema(
                type=openapi.TYPE_STRING, description="Instagram handle"
            ),
            "tiktok_handle": openapi.Schema(
                type=openapi.TYPE_STRING, description="TikTok handle"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Store details updated successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "store": openapi.Schema(
                        type=openapi.TYPE_OBJECT, description="Updated store details"
                    ),
                },
            ),
        ),
        400: openapi.Response(description="Invalid data provided"),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Products"],
)
@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def my_store_api(request):
    """
    Get or update vendor's own store information.

    GET: Returns comprehensive store details including:
    - Store information (name, description, logo, contact details)
    - Average rating and total reviews
    - Product count (active products only)
    - Subscription status

    PUT: Updates vendor store details like name, description, contact info.
    Does NOT return individual products - use separate endpoint for product listing.
    """
    try:
        vendor_profile = request.user.vendor_profile
    except AttributeError:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "PUT":
        serializer = VendorUpdateSerializer(
            vendor_profile, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Store details updated successfully",
                    "store": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Get product count (excluding deleted products)
    product_count = (
        Product.objects.filter(vendor=vendor_profile)
        .exclude(status=Product.DELETED)
        .count()
    )

    # Calculate average rating and total reviews
    from django.db.models import Avg, Count

    reviews_stats = Review.objects.filter(
        product__vendor=vendor_profile, approved_review=True
    ).aggregate(average_rating=Avg("rating"), total_reviews=Count("id"))

    average_rating = reviews_stats["average_rating"] or 0.0
    total_reviews = reviews_stats["total_reviews"] or 0

    # Get vendor's full name
    vendor_name = f"{request.user.first_name} {request.user.last_name}".strip()
    if not vendor_name:
        vendor_name = request.user.user_name

    # Prepare store information response
    store_data = {
        "vendor_id": vendor_profile.id,
        "vendor_name": vendor_name,
        "store_name": vendor_profile.store_name,
        "store_description": vendor_profile.store_description,
        "store_logo": (
            vendor_profile.store_logo.url if vendor_profile.store_logo else None
        ),
        "phone_number": (
            str(vendor_profile.phone_number) if vendor_profile.phone_number else None
        ),
        "whatsapp_number": (
            str(vendor_profile.whatsapp_number)
            if vendor_profile.whatsapp_number
            else None
        ),
        "instagram_handle": vendor_profile.instagram_handle,
        "tiktok_handle": vendor_profile.tiktok_handle,
        "is_verified": vendor_profile.is_verified,
        "average_rating": round(average_rating, 1),
        "total_reviews": total_reviews,
        "product_count": product_count,
        **_vendor_subscription_payload(vendor_profile),
    }

    return Response(store_data, status=status.HTTP_200_OK)


@swagger_auto_schema(
    method="put",
    operation_summary="Update Vendor Store Details",
    operation_description="Update vendor store information including name, description, contact details and social media handles",
    request_body=VendorUpdateSerializer,
    responses={
        200: openapi.Response(
            description="Vendor details updated successfully",
            schema=VendorUpdateSerializer,
        ),
        400: openapi.Response(description="Invalid data provided"),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Management"],
)
@swagger_auto_schema(
    method="patch",
    operation_summary="Partially Update Vendor Store Details",
    operation_description="Partially update vendor store information. Only provided fields will be updated.",
    request_body=VendorUpdateSerializer,
    responses={
        200: openapi.Response(
            description="Vendor details updated successfully",
            schema=VendorUpdateSerializer,
        ),
        400: openapi.Response(description="Invalid data provided"),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Management"],
)
@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def update_vendor_api(request):
    """
    Update vendor store details via PUT (full update) or PATCH (partial update)

    Allows vendors to update their store information including:
    - Store name and description
    - Store logo
    - Contact information (phone, WhatsApp)
    - Social media handles (Instagram, TikTok)
    """
    try:
        vendor = request.user.vendor_profile
    except AttributeError:
        return Response({"error": "User is not a vendor."}, status=status.HTTP_403_FORBIDDEN)

    # Use partial=True for PATCH, False for PUT
    serializer = VendorUpdateSerializer(
        vendor, data=request.data, partial=(request.method == "PATCH")
    )

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="get",
    operation_summary="Get My Subscription Status",
    operation_description="Get the current user's subscription status and details",
    responses={
        200: openapi.Response(
            description="Current user's subscription details",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "is_vendor": openapi.Schema(
                        type=openapi.TYPE_BOOLEAN,
                        description="Whether user is a vendor",
                    ),
                    "subscription_status": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Current subscription status",
                    ),
                    "subscription_start": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        format="date-time",
                        description="Subscription start date",
                    ),
                    "subscription_expiry": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        format="date-time",
                        description="Subscription expiry date",
                    ),
                    "is_active": openapi.Schema(
                        type=openapi.TYPE_BOOLEAN,
                        description="Whether subscription is currently active (including grace period)",
                    ),
                    "days_remaining": openapi.Schema(
                        type=openapi.TYPE_INTEGER,
                        description="Days until expiry (negative if expired)",
                    ),
                    "in_grace_period": openapi.Schema(
                        type=openapi.TYPE_BOOLEAN,
                        description="Whether in 7-day grace period",
                    ),
                    "plan": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(
                                type=openapi.TYPE_INTEGER, description="Plan ID"
                            ),
                            "name": openapi.Schema(
                                type=openapi.TYPE_STRING, description="Plan name"
                            ),
                            "price": openapi.Schema(
                                type=openapi.TYPE_NUMBER, description="Monthly price"
                            ),
                            "max_products": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="Maximum products allowed",
                            ),
                        },
                        nullable=True,
                    ),
                    "product_usage": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "current_count": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="Current number of active products",
                            ),
                            "max_allowed": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="Maximum products allowed by plan",
                            ),
                            "remaining": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="Remaining product slots",
                            ),
                        },
                    ),
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_subscription_status_api(request):
    """
    Get the current user's subscription status and details.

    Returns comprehensive subscription information including:
    - Current subscription status and dates
    - Plan details and limits
    - Product usage statistics
    - Grace period information
    """
    try:
        vendor = request.user.vendor_profile
    except AttributeError:
        return Response(
            {"error": "User is not registered as a vendor"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Calculate subscription details
    now = timezone.now()
    is_active = vendor.is_subscription_active()

    # Calculate days remaining
    days_remaining = vendor.get_subscription_days_remaining()
    in_grace_period = vendor.is_in_grace_period()

    # Plan information
    plan_info = None
    if vendor.plan:
        plan_info = {
            "id": vendor.plan.pk,
            "name": vendor.plan.name,
            "price": float(vendor.plan.price),
            "max_products": vendor.plan.max_products,
        }

    # Product usage statistics
    current_product_count = Product.objects.filter(
        vendor=vendor, status=Product.ACTIVE
    ).count()

    max_allowed = vendor.plan.max_products if vendor.plan else 0
    remaining = max(0, max_allowed - current_product_count)

    product_usage = {
        "current_count": current_product_count,
        "max_allowed": max_allowed,
        "remaining": remaining,
    }

    return Response(
        {
            "is_vendor": True,
            **_vendor_subscription_payload(vendor),
            "subscription_start": (
                vendor.subscription_start.isoformat()
                if vendor.subscription_start
                else None
            ),
            "is_active": is_active,
            "days_remaining": days_remaining,
            "in_grace_period": in_grace_period,
            "plan": plan_info,
            "product_usage": product_usage,
        },
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Add a new product to vendor's store",
    security=[{"Bearer": []}],
    manual_parameters=[
        openapi.Parameter(
            "title",
            openapi.IN_FORM,
            description="Product title/name",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "description",
            openapi.IN_FORM,
            description="Product description",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "price",
            openapi.IN_FORM,
            description="Product price in kobo/cents (e.g., 1000 = NGN 10.00)",
            type=openapi.TYPE_INTEGER,
            required=True,
        ),
        openapi.Parameter(
            "category",
            openapi.IN_FORM,
            description="Category ID (get from /api/categories/)",
            type=openapi.TYPE_INTEGER,
            required=True,
        ),
        openapi.Parameter(
            "status",
            openapi.IN_FORM,
            description="Product status",
            type=openapi.TYPE_STRING,
            enum=["draft", "waiting approval", "active", "deleted"],
            default="active",
            required=False,
        ),
        openapi.Parameter(
            "stock",
            openapi.IN_FORM,
            description="Stock status",
            type=openapi.TYPE_STRING,
            enum=["in stock", "out of stock"],
            default="in stock",
            required=False,
        ),
        openapi.Parameter(
            "featured",
            openapi.IN_FORM,
            description="Whether product is featured",
            type=openapi.TYPE_BOOLEAN,
            default=False,
            required=False,
        ),
        openapi.Parameter(
            "product_image",
            openapi.IN_FORM,
            description="Product image file",
            type=openapi.TYPE_FILE,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Product successfully created",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "product_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        ),
        400: openapi.Response(description="Validation errors"),
        403: openapi.Response(description="Product limit reached for your plan"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Products"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
@parser_classes([MultiPartParser, FormParser])
def add_product_api(request):
    if not can_create_product(request.user):
        return Response({"error": "Product limit reached for your plan."}, status=status.HTTP_403_FORBIDDEN)
    serializer = ProductCreateSerializer(data=request.data)
    if serializer.is_valid():
        product = serializer.save(vendor=request.user.vendor_profile)
        return Response({"success": True, "product_id": product.id})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="put",
    operation_description="Edit an existing product in vendor's store",
    manual_parameters=[
        openapi.Parameter(
            "title",
            openapi.IN_FORM,
            description="Product title/name",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "description",
            openapi.IN_FORM,
            description="Product description",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "price",
            openapi.IN_FORM,
            description="Product price in kobo/cents (e.g., 1000 = NGN 10.00)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "category",
            openapi.IN_FORM,
            description="Category ID (get from /api/categories/)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "status",
            openapi.IN_FORM,
            description="Product status",
            type=openapi.TYPE_STRING,
            enum=["draft", "waiting approval", "active", "deleted"],
            required=False,
        ),
        openapi.Parameter(
            "stock",
            openapi.IN_FORM,
            description="Stock status",
            type=openapi.TYPE_STRING,
            enum=["in stock", "out of stock"],
            required=False,
        ),
        openapi.Parameter(
            "featured",
            openapi.IN_FORM,
            description="Whether product is featured",
            type=openapi.TYPE_BOOLEAN,
            required=False,
        ),
        openapi.Parameter(
            "product_image",
            openapi.IN_FORM,
            description="Product image file",
            type=openapi.TYPE_FILE,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Product successfully updated",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Validation errors"),
        404: openapi.Response(description="Product not found or unauthorized"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Products"],
)
@api_view(["PUT"])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def edit_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response(
            {"error": "Product not found or unauthorized"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Handle empty product_image object from JSON requests
    data = request.data.copy()
    if "product_image" in data and data["product_image"] == {}:
        data.pop("product_image")

    serializer = ProductCreateSerializer(product, data=data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({"success": True, "message": "Product updated successfully"})

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
def delete_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response(
            {"error": "Product not found or unauthorized"},
            status=status.HTTP_404_NOT_FOUND,
        )

    product.status = Product.DELETED
    product.save()
    return Response(
        {"success": True, "message": f"{product.title} was deleted successfully"},
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="get",
    operation_description="Get all orders for a vendor with KPIs",
    security=[{"Bearer": []}],
    manual_parameters=[
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Vendor orders retrieved successfully with KPIs",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                    "kpis": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "total_orders": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "pending_orders": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "completed_orders": openapi.Schema(
                                type=openapi.TYPE_INTEGER
                            ),
                            "cancelled_orders": openapi.Schema(
                                type=openapi.TYPE_INTEGER
                            ),
                            "total_revenue": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "completion_rate": openapi.Schema(type=openapi.TYPE_NUMBER),
                        },
                    ),
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor Orders"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def vendor_order_list_api(request):
    if not hasattr(request.user, "vendor_profile"):
        return Response(
            {"error": "Only vendors can access this endpoint."},
            status=status.HTTP_403_FORBIDDEN,
        )

    vendor = request.user.vendor_profile
    order_items = (
        OrderItem.objects.filter(product__vendor=vendor)
        .select_related("order", "product")
        .order_by("-order__created_at")
    )

    # Calculate KPIs
    total_orders = order_items.count()
    pending_orders = order_items.filter(fulfilled=False).count()
    completed_orders = order_items.filter(fulfilled=True).count()

    # Get unique orders for this vendor and calculate cancelled orders
    vendor_orders = Order.objects.filter(items__product__vendor=vendor).distinct()

    # Cancelled orders are those with failed payments or no payments
    cancelled_orders = (
        vendor_orders.filter(
            Q(payments__status="failed") | Q(payments__isnull=True, is_paid=False)
        )
        .distinct()
        .count()
    )

    # Total revenue from completed orders
    total_revenue = sum(item.price for item in order_items.filter(fulfilled=True))

    # Paginate order items
    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(order_items, request)

    serializer = VendorOrderItemSerializer(result_page, many=True)

    # Create response with KPIs
    kpis = {
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
        "total_revenue": total_revenue,
        "completion_rate": round(
            (completed_orders / total_orders * 100) if total_orders > 0 else 0, 2
        ),
    }

    # Create custom response data
    response_data = {
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": serializer.data,
        "kpis": kpis,
    }

    return Response(response_data)


@api_view(["GET"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def order_detail_api(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if not hasattr(request.user, "vendor_profile"):
        return Response(
            {"error": "Only vendors can access this view."},
            status=status.HTTP_403_FORBIDDEN,
        )

    vendor = request.user.vendor_profile

    if not order.items.filter(product__vendor=vendor).exists():
        return Response(
            {"error": "You are not authorized to view this order."},
            status=status.HTTP_403_FORBIDDEN,
        )

    vendor_items = order.items.filter(product__vendor=vendor)

    serializer = VendorOrderDetailSerializer({"order": order, "items": vendor_items})

    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def toggle_fulfillment_api(request, pk):
    try:
        order_item = OrderItem.objects.get(
            pk=pk, product__vendor=request.user.vendor_profile
        )
    except OrderItem.DoesNotExist:
        return Response(
            {"error": "Order item not found or unauthorized."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if order_item.order.is_paid:
        order_item.fulfilled = not order_item.fulfilled
        order_item.save()
        return Response(
            {"success": True, "fulfilled": order_item.fulfilled},
            status=status.HTTP_200_OK,
        )

    return Response(
        {"success": False, "message": "Order not paid."},
        status=status.HTTP_400_BAD_REQUEST,
    )


@swagger_auto_schema(
    method="get",
    operation_description="Get all reviews for a vendor's products",
    security=[{"Bearer": []}],  # Requires JWT authentication
    manual_parameters=[
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "rating",
            openapi.IN_QUERY,
            description="Filter by rating (1-5)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Paginated list of reviews for vendor's products with rating statistics",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                    "rating_stats": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "average_rating": openapi.Schema(
                                type=openapi.TYPE_NUMBER,
                                description="Average rating (0.0-5.0)",
                            ),
                            "total_reviews": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="Total number of reviews",
                            ),
                            "rating_breakdown": openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    "5_star": openapi.Schema(
                                        type=openapi.TYPE_INTEGER,
                                        description="Number of 5-star reviews",
                                    ),
                                    "4_star": openapi.Schema(
                                        type=openapi.TYPE_INTEGER,
                                        description="Number of 4-star reviews",
                                    ),
                                    "3_star": openapi.Schema(
                                        type=openapi.TYPE_INTEGER,
                                        description="Number of 3-star reviews",
                                    ),
                                    "2_star": openapi.Schema(
                                        type=openapi.TYPE_INTEGER,
                                        description="Number of 2-star reviews",
                                    ),
                                    "1_star": openapi.Schema(
                                        type=openapi.TYPE_INTEGER,
                                        description="Number of 1-star reviews",
                                    ),
                                },
                            ),
                        },
                    ),
                },
            ),
        ),
        401: openapi.Response(description="Authentication required"),
        403: openapi.Response(description="Only vendors can access this endpoint"),
    },
    tags=["Vendors"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def vendor_reviews_api(request):
    """
    Get all reviews for a vendor's products.

    Returns a paginated list of all reviews for products belonging to the authenticated vendor.
    Can be filtered by rating. Also includes rating statistics.
    """
    if not hasattr(request.user, "vendor_profile"):
        return Response(
            {"error": "Only vendors can access this endpoint."},
            status=status.HTTP_403_FORBIDDEN,
        )

    vendor = request.user.vendor_profile

    # Get all reviews for this vendor's products
    from store.models import Review
    from django.db.models import Avg, Count

    all_reviews = Review.objects.filter(product__vendor=vendor).select_related(
        "product", "author"
    )

    # Calculate rating statistics
    rating_stats = all_reviews.aggregate(
        average_rating=Avg("rating"), total_reviews=Count("id")
    )

    # Get rating breakdown in a single query, then unpack.
    counts_by_rating = {
        row["rating"]: row["count"]
        for row in all_reviews.values("rating").annotate(count=Count("id"))
    }
    rating_breakdown = {
        f"{n}_star": counts_by_rating.get(n, 0) for n in range(5, 0, -1)
    }

    # Get reviews for pagination (after calculating stats)
    reviews = all_reviews.order_by("-created_date")

    # Filter by rating if provided
    rating = request.GET.get("rating")
    if rating:
        try:
            rating = int(rating)
            if 1 <= rating <= 5:
                reviews = reviews.filter(rating=rating)
        except (ValueError, TypeError):
            pass  # Invalid rating, ignore filter

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(reviews, request)

    # Create custom serialized data
    serialized_reviews = []
    if result_page is not None:
        for review in result_page:
            serialized_reviews.append(
                {
                    "id": review.id,
                    "product": {
                        "id": review.product.id,
                        "title": review.product.title,
                        "slug": review.product.slug,
                    },
                    "author": {
                        "id": review.author.id,
                        "name": f"{review.author.first_name} {review.author.last_name}".strip()
                        or review.author.user_name,
                    },
                    "rating": review.rating,
                    "text": review.text,
                    "created_at": review.created_date,
                }
            )

    # Prepare response data with statistics
    response_data = {
        "count": paginator.page.paginator.count if result_page is not None else 0,
        "next": paginator.get_next_link() if result_page is not None else None,
        "previous": paginator.get_previous_link() if result_page is not None else None,
        "results": serialized_reviews,
        "rating_stats": {
            "average_rating": (
                round(rating_stats["average_rating"], 1)
                if rating_stats["average_rating"]
                else 0.0
            ),
            "total_reviews": rating_stats["total_reviews"],
            "rating_breakdown": rating_breakdown,
        },
    }

    return Response(response_data, status=status.HTTP_200_OK)


@swagger_auto_schema(
    method="get",
    operation_description="Get all reviews for a specific vendor's products (public)",
    security=[],  # Public endpoint - no authentication required
    manual_parameters=[
        openapi.Parameter(
            "vendor_id",
            openapi.IN_PATH,
            description="Vendor ID",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "rating",
            openapi.IN_QUERY,
            description="Filter by rating (1-5)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Paginated list of reviews for vendor's products",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                },
            ),
        ),
        404: openapi.Response(description="Vendor not found"),
    },
    tags=["Vendors"],
)
@api_view(["GET"])
def vendor_reviews_public_api(request, vendor_id):
    """
    Get all reviews for a specific vendor's products (public endpoint).

    Returns a paginated list of all reviews for products belonging to the specified vendor.
    This is a public endpoint that doesn't require authentication.
    """
    try:
        vendor = VendorProfile.objects.get(id=vendor_id)
    except VendorProfile.DoesNotExist:
        return Response(
            {"error": "Vendor not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get all reviews for this vendor's products
    from store.models import Review

    reviews = (
        Review.objects.filter(product__vendor=vendor)
        .select_related("product", "author")
        .order_by("-created_date")
    )

    # Filter by rating if provided
    rating = request.GET.get("rating")
    if rating:
        try:
            rating = int(rating)
            if 1 <= rating <= 5:
                reviews = reviews.filter(rating=rating)
        except (ValueError, TypeError):
            pass  # Invalid rating, ignore filter

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(reviews, request)

    # Create custom serialized data
    serialized_reviews = []
    if result_page is not None:
        for review in result_page:
            serialized_reviews.append(
                {
                    "id": review.id,
                    "product": {
                        "id": review.product.id,
                        "title": review.product.title,
                        "slug": review.product.slug,
                    },
                    "author": {
                        "name": f"{review.author.first_name} {review.author.last_name}".strip()
                        or review.author.user_name,
                    },
                    "rating": review.rating,
                    "text": review.text,
                    "created_at": review.created_date,
                }
            )

    return paginator.get_paginated_response(serialized_reviews)


@swagger_auto_schema(
    method="get",
    operation_summary="List Vendor Plans",
    operation_description="Get all available vendor subscription plans",
    responses={
        200: openapi.Response(
            description="List of available vendor plans",
            schema=openapi.Schema(
                type=openapi.TYPE_ARRAY,
                items=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "id": openapi.Schema(
                            type=openapi.TYPE_INTEGER, description="Plan ID"
                        ),
                        "name": openapi.Schema(
                            type=openapi.TYPE_STRING, description="Plan name"
                        ),
                        "price": openapi.Schema(
                            type=openapi.TYPE_NUMBER,
                            description="Monthly price in Naira",
                        ),
                        "max_products": openapi.Schema(
                            type=openapi.TYPE_INTEGER,
                            description="Maximum products allowed",
                        ),
                        "is_active": openapi.Schema(
                            type=openapi.TYPE_BOOLEAN,
                            description="Plan availability status",
                        ),
                    },
                ),
            ),
        )
    },
)
@api_view(["GET"])
def vendor_plans_api(request):
    """
    List all available vendor subscription plans.
    """
    plans = VendorPlan.objects.filter(is_active=True).order_by("price")
    serializer = VendorPlanSerializer(plans, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@swagger_auto_schema(
    method="get",
    operation_summary="Get Vendor KPIs",
    operation_description="Get key performance indicators for the authenticated vendor including ratings, sales, reviews, and subscription details.",
    security=[{"Bearer": []}],
    responses={
        200: openapi.Response(
            description="Vendor KPIs retrieved successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "vendor_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "store_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "ratings": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "average_rating": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "total_reviews": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "rating_breakdown": openapi.Schema(
                                type=openapi.TYPE_OBJECT
                            ),
                        },
                    ),
                    "sales": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "total_orders": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "total_revenue": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "total_products_sold": openapi.Schema(
                                type=openapi.TYPE_INTEGER
                            ),
                        },
                    ),
                    "products": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "total_products": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "active_products": openapi.Schema(
                                type=openapi.TYPE_INTEGER
                            ),
                            "out_of_stock": openapi.Schema(type=openapi.TYPE_INTEGER),
                        },
                    ),
                    "subscription": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "status": openapi.Schema(type=openapi.TYPE_STRING),
                            "days_remaining": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "plan_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "expires_at": openapi.Schema(type=openapi.TYPE_STRING),
                        },
                    ),
                },
            ),
        ),
        403: openapi.Response(description="User is not a vendor"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Vendor KPIs"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def vendor_kpis_api(request):
    """
    Get comprehensive KPIs for the authenticated vendor.

    Returns key metrics including:
    - Average rating and review statistics
    - Sales data (orders, revenue, products sold)
    - Product statistics
    - Subscription details and days remaining
    """
    try:
        vendor = request.user.vendor_profile
    except AttributeError:
        return Response(
            {"error": "User is not a vendor"}, status=status.HTTP_403_FORBIDDEN
        )

    from .services import get_vendor_kpis
    return Response(get_vendor_kpis(vendor), status=status.HTTP_200_OK)
