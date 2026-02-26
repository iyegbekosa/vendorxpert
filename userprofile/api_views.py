from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import login
from .serializers import (
    SignupSerializer,
    UserProfileSerializer,
    ProfileUpdateSerializer,
    ProfilePictureUploadSerializer,
    VendorRegisterSerializer,
    VendorProfileSerializer,
    VendorUpdateSerializer,
    VendorListSerializer,
    Product,
    ProductSerializer,
    ProductCreateSerializer,
    VendorOrderDetailSerializer,
    VendorOrderItemSerializer,
    VendorPlanSerializer,
    SubscriptionInitiateSerializer,
    ChangePlanSerializer,
)
from .models import VendorProfile, VendorPlan
from store.utils import create_paystack_subaccount
from django.db import transaction
from django.db.models import Count, Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from store.models import OrderItem, Order, Payment, Review
from .views import get_object_or_404
from store.pagination import StandardResultsPagination
from .permissions import can_create_product, HasActiveSubscription, VendorFeatureAccess
import requests
from django.conf import settings
import uuid
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
import json
import hmac
import hashlib
import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .email_utils import (
    send_welcome_email,
    send_vendor_welcome_email,
    send_verification_email,
    send_password_reset_email,
)
from .models import EmailVerification, UserProfile
from django.contrib.auth.hashers import make_password
import random


@swagger_auto_schema(
    method="post",
    operation_description="Register a new user account",
    security=[],  # No authentication required
    request_body=SignupSerializer,
    responses={
        201: openapi.Response(
            description="User successfully created",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        ),
        400: openapi.Response(description="Validation errors"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def signup_api(request):
    """
    Register a new user account.

    Creates a new user account with required fields: username, email, first_name, last_name, and password.
    Automatically logs the user in upon successful registration and sends a welcome email.
    """
    # New flow: validate input, create a verification record and email a 6-digit code.
    serializer = SignupSerializer(data=request.data)
    if serializer.is_valid():
        data = serializer.validated_data
        email = data.get("email")

        # If a user already exists with this email, reject
        if UserProfile.objects.filter(email=email).exists():
            return Response(
                {"error": "Email is already registered."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate 6-digit code
        code = "".join(random.choices("0123456789", k=6))

        # Store hashed password in payload so we don't keep plaintext
        hashed = make_password(data.get("password"))

        expires_at = timezone.now() + timedelta(minutes=15)

        payload = {
            "user_name": data.get("user_name"),
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "password_hashed": hashed,
        }

        # Create or update verification record
        EmailVerification.objects.update_or_create(
            email=email,
            verification_type="signup",
            is_used=False,
            defaults={
                "code": code,
                "payload": payload,
                "expires_at": expires_at,
            },
        )

        # Send the verification code
        try:
            send_verification_email(email, code, expires_at=expires_at)
        except Exception as e:
            logger.error(f"Failed to send verification email to {email}: {str(e)}")

        return Response(
            {
                "success": True,
                "message": "Verification code sent to your email. Use it to complete registration.",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="post",
    operation_description="Verify email with 6-digit code and create the user account",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "code"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING),
            "code": openapi.Schema(type=openapi.TYPE_STRING),
        },
    ),
    responses={
        201: openapi.Response(description="User successfully created"),
        400: openapi.Response(description="Invalid code or expired"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def verify_signup_api(request):
    email = request.data.get("email")
    code = request.data.get("code")

    if not email or not code:
        return Response(
            {"error": "email and code are required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        ev = EmailVerification.objects.get(
            email=email, verification_type="signup", is_used=False
        )
    except EmailVerification.DoesNotExist:
        return Response(
            {"error": "No pending verification found for this email."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if ev.is_expired():
        return Response(
            {"error": "Verification code has expired."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if ev.code != code:
        return Response(
            {"error": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST
        )

    # Create the user now
    payload = ev.payload
    if UserProfile.objects.filter(email=email).exists():
        ev.mark_used()
        return Response(
            {"error": "Email already registered."}, status=status.HTTP_400_BAD_REQUEST
        )

    user = UserProfile(
        user_name=payload.get("user_name"),
        email=email,
        first_name=payload.get("first_name", ""),
        last_name=payload.get("last_name", ""),
    )
    # Set hashed password directly
    user.password = payload.get("password_hashed")
    user.save()

    # mark verification used
    ev.mark_used()

    # Log the user in and send welcome email
    try:
        login(request, user)
    except Exception:
        pass

    try:
        send_welcome_email(user)
    except Exception as e:
        logger.error(
            f"Failed to send welcome email after verification to {email}: {str(e)}"
        )

    return Response(
        {
            "success": True,
            "user_id": user.id,
            "message": "Account created successfully.",
        },
        status=status.HTTP_201_CREATED,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Resend verification code for email signup",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING, description="User email"),
        },
    ),
    responses={
        202: openapi.Response(
            description="Verification code resent",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Invalid email or no pending verification"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def resend_verification_api(request):
    """
    Resend verification code for email signup.

    Generates a new 6-digit verification code and sends it to the user's email
    if there's a pending signup verification record.
    """
    email = request.data.get("email")

    if not email:
        return Response(
            {"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Find existing pending verification for signup
        ev = EmailVerification.objects.get(
            email=email, verification_type="signup", is_used=False
        )
    except EmailVerification.DoesNotExist:
        return Response(
            {"error": "No pending verification found for this email."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Generate new 6-digit code
    new_code = "".join(random.choices("0123456789", k=6))

    # Update existing record with new code and extended expiration
    ev.code = new_code
    ev.expires_at = timezone.now() + timedelta(minutes=15)
    ev.save()

    # Send the new verification code
    try:
        send_verification_email(email, new_code, expires_at=ev.expires_at)
    except Exception as e:
        logger.error(f"Failed to resend verification email to {email}: {str(e)}")
        return Response(
            {"error": "Failed to send verification email. Please try again later."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {
            "success": True,
            "message": "Verification code has been resent to your email.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Request password reset code via email",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING, description="User email"),
        },
    ),
    responses={
        202: openapi.Response(
            description="Password reset code sent",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Invalid email or user not found"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def forgot_password_api(request):
    """
    Request a password reset code via email.

    Sends a 6-digit code to the user's email if the account exists.
    """
    email = request.data.get("email")

    if not email:
        return Response(
            {"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    # Check if user exists
    try:
        user = UserProfile.objects.get(email=email)
    except UserProfile.DoesNotExist:
        # Don't reveal whether email exists for security
        return Response(
            {
                "success": True,
                "message": "If an account with this email exists, a password reset code has been sent.",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    # Generate 6-digit code
    code = "".join(random.choices("0123456789", k=6))
    expires_at = timezone.now() + timedelta(minutes=15)

    # Create verification record for password reset
    EmailVerification.objects.update_or_create(
        email=email,
        verification_type="password_reset",
        is_used=False,
        defaults={
            "code": code,
            "payload": {},  # Empty payload for password resets
            "expires_at": expires_at,
        },
    )

    # Send password reset email
    try:
        send_password_reset_email(email, code, expires_at=expires_at)
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {str(e)}")

    return Response(
        {
            "success": True,
            "message": "If an account with this email exists, a password reset code has been sent.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Verify password reset code without changing password",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "code"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING, description="User email"),
            "code": openapi.Schema(
                type=openapi.TYPE_STRING, description="6-digit reset code"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Code verified successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "reset_token": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Temporary token for password reset",
                    ),
                },
            ),
        ),
        400: openapi.Response(description="Invalid code, expired, or other errors"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def verify_reset_code_api(request):
    """
    Verify the password reset code without changing the password.
    Returns a temporary token that can be used for the actual password reset.
    """
    email = request.data.get("email")
    code = request.data.get("code")

    if not email or not code:
        return Response(
            {"error": "email and code are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find verification record
    try:
        ev = EmailVerification.objects.get(
            email=email, verification_type="password_reset", is_used=False
        )
    except EmailVerification.DoesNotExist:
        return Response(
            {"error": "No valid password reset request found for this email"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if ev.is_expired():
        return Response(
            {"error": "Password reset code has expired"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if ev.code != code:
        return Response(
            {"error": "Invalid password reset code"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify user exists
    try:
        user = UserProfile.objects.get(email=email)
    except UserProfile.DoesNotExist:
        return Response(
            {"error": "User account not found"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Generate a temporary reset token (valid for 10 minutes)
    import secrets

    reset_token = secrets.token_urlsafe(32)

    # Store the reset token in the verification payload
    ev.payload = {
        "reset_token": reset_token,
        "verified_at": timezone.now().isoformat(),
    }
    ev.save()

    logger.info(f"Password reset code verified for user {email}")

    return Response(
        {
            "success": True,
            "message": "Reset code verified successfully. You can now set a new password.",
            "reset_token": reset_token,
        },
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Reset password using verified reset token",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "reset_token", "new_password"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING, description="User email"),
            "reset_token": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Reset token from verification step",
            ),
            "new_password": openapi.Schema(
                type=openapi.TYPE_STRING, description="New password"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Password reset successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Invalid token, expired, or other errors"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def reset_password_api(request):
    """
    Reset password using the verified reset token.
    This endpoint should be called after verify_reset_code_api.
    """
    email = request.data.get("email")
    reset_token = request.data.get("reset_token")
    new_password = request.data.get("new_password")

    if not email or not reset_token or not new_password:
        return Response(
            {"error": "email, reset_token, and new_password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate password strength
    if len(new_password) < 6:
        return Response(
            {"error": "Password must be at least 6 characters long"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find verification record with the reset token
    try:
        ev = EmailVerification.objects.get(
            email=email, verification_type="password_reset", is_used=False
        )
    except EmailVerification.DoesNotExist:
        return Response(
            {"error": "No valid password reset request found for this email"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if ev.is_expired():
        return Response(
            {"error": "Password reset session has expired"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify the reset token
    stored_token = ev.payload.get("reset_token")
    if not stored_token or stored_token != reset_token:
        return Response(
            {"error": "Invalid or expired reset token"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check if token was verified recently (within 10 minutes)
    verified_at_str = ev.payload.get("verified_at")
    if verified_at_str:
        from datetime import datetime

        verified_at = datetime.fromisoformat(verified_at_str.replace("Z", "+00:00"))
        if (
            timezone.now() - verified_at.replace(tzinfo=timezone.utc)
        ).total_seconds() > 600:  # 10 minutes
            return Response(
                {"error": "Reset token has expired. Please request a new reset code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        return Response(
            {"error": "Reset token not properly verified"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find and update user password
    try:
        user = UserProfile.objects.get(email=email)
    except UserProfile.DoesNotExist:
        return Response(
            {"error": "User account not found"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Update password
    user.set_password(new_password)
    user.save()

    # Mark verification as used
    ev.mark_used()

    logger.info(f"Password reset completed successfully for user {email}")

    return Response(
        {
            "success": True,
            "message": "Password has been reset successfully. You can now login with your new password.",
        },
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Login user and return authentication token",
    security=[],  # No authentication required - this is how you GET tokens!
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["email", "password"],
        properties={
            "email": openapi.Schema(type=openapi.TYPE_STRING, description="User email"),
            "password": openapi.Schema(
                type=openapi.TYPE_STRING, description="User password"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Login successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "user_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "email": openapi.Schema(type=openapi.TYPE_STRING),
                    "is_vendor": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "vendor_id": openapi.Schema(
                        type=openapi.TYPE_INTEGER,
                        description="Vendor ID (only present if is_vendor is true)",
                    ),
                    "refresh": openapi.Schema(
                        type=openapi.TYPE_STRING, description="JWT refresh token"
                    ),
                    "access": openapi.Schema(
                        type=openapi.TYPE_STRING, description="JWT access token"
                    ),
                },
            ),
        ),
        400: openapi.Response(description="Invalid credentials"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
def login_api(request):
    """
    Login user with email and password.

    Authenticates user and returns user information with JWT tokens.
    """
    from django.contrib.auth import authenticate
    from rest_framework_simplejwt.tokens import RefreshToken

    email = request.data.get("email")
    password = request.data.get("password")

    if not email or not password:
        return Response(
            {"error": "Email and password are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = authenticate(request, username=email, password=password)

    if user is not None:
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token

        is_vendor = hasattr(user, "vendor_profile")

        response_data = {
            "success": True,
            "user_id": user.id,
            "email": user.email,
            "is_vendor": is_vendor,
            "refresh": str(refresh),
            "access": str(access_token),
        }

        # Include vendor details if user is a vendor
        if is_vendor:
            vendor = user.vendor_profile
            response_data["vendor_id"] = vendor.id
            response_data["store_details"] = {
                "store_name": vendor.store_name,
                "store_logo_url": vendor.store_logo.url if vendor.store_logo else None,
                "store_description": vendor.store_description,
                "phone_number": (
                    str(vendor.phone_number) if vendor.phone_number else None
                ),
                "whatsapp_number": (
                    str(vendor.whatsapp_number) if vendor.whatsapp_number else None
                ),
                "instagram_handle": vendor.instagram_handle,
                "tiktok_handle": vendor.tiktok_handle,
                "is_verified": vendor.is_verified,
                "subscription_status": vendor.subscription_status,
                "subscription_expiry": (
                    vendor.subscription_expiry.isoformat()
                    if vendor.subscription_expiry
                    else None
                ),
            }

        return Response(response_data, status=status.HTTP_200_OK)
    else:
        return Response(
            {"error": "Invalid email or password"}, status=status.HTTP_400_BAD_REQUEST
        )


@swagger_auto_schema(
    methods=["get"],
    operation_description="Get current user's profile details",
    operation_summary="Get user profile",
    responses={
        200: openapi.Response(
            description="Profile retrieved successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "user_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "email": openapi.Schema(type=openapi.TYPE_STRING),
                    "first_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "last_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "hostel": openapi.Schema(type=openapi.TYPE_STRING),
                    "profile_picture": openapi.Schema(type=openapi.TYPE_STRING),
                    "start_date": openapi.Schema(type=openapi.TYPE_STRING),
                    "is_vendor": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "vendor_info": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        description="Vendor details if user is a vendor, null otherwise",
                    ),
                },
            ),
        ),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Profile"],
)
@swagger_auto_schema(
    methods=["put"],
    operation_description="Update current user's profile (excluding profile picture)",
    operation_summary="Update user profile",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "first_name": openapi.Schema(
                type=openapi.TYPE_STRING, description="User's first name"
            ),
            "last_name": openapi.Schema(
                type=openapi.TYPE_STRING, description="User's last name"
            ),
            "hostel": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Hostel selection (hall_1 to hall_8)",
                enum=[
                    "hall_1",
                    "hall_2",
                    "hall_3",
                    "hall_4",
                    "hall_5",
                    "hall_6",
                    "hall_7",
                    "hall_8",
                ],
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Profile updated successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "profile": openapi.Schema(type=openapi.TYPE_OBJECT),
                },
            ),
        ),
        400: openapi.Response(description="Invalid data provided"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Profile"],
)
@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def profile_api(request):
    """
    Get or update current user's profile details (excluding profile picture).

    GET: Returns comprehensive profile information including vendor details if applicable.
    PUT: Updates profile information (name, hostel) - use separate endpoint for profile picture.
    """
    if request.method == "GET":
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == "PUT":
        serializer = ProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            # Return updated profile using the full profile serializer
            updated_profile = UserProfileSerializer(request.user)
            return Response(
                {
                    "message": "Profile updated successfully",
                    "profile": updated_profile.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="post",
    operation_description="Upload or update user's profile picture. Accepts either 'picture' or 'profile_picture' field name.",
    operation_summary="Upload profile picture",
    manual_parameters=[
        openapi.Parameter(
            "profile_picture",
            openapi.IN_FORM,
            description="Profile picture image file (max 5MB, JPG/PNG/GIF/SVG)",
            type=openapi.TYPE_FILE,
            required=False,
        ),
        openapi.Parameter(
            "picture",
            openapi.IN_FORM,
            description="Alternative field name for profile picture (same as profile_picture, max 5MB, JPG/PNG/GIF/SVG)",
            type=openapi.TYPE_FILE,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Profile picture uploaded successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "profile_picture_url": openapi.Schema(type=openapi.TYPE_STRING),
                    "profile": openapi.Schema(type=openapi.TYPE_OBJECT),
                },
            ),
        ),
        400: openapi.Response(description="Invalid file or validation error"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Profile"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_profile_picture_api(request):
    """
    Upload or update the authenticated user's profile picture.

    Supports image files with validation for file size (max 5MB) and format (JPG, PNG, GIF, SVG).
    Replaces any existing profile picture.
    """
    # Handle both 'picture' and 'profile_picture' field names for file uploads
    upload_data = {}

    # Check for file in request.FILES (which preserves file objects)
    if "picture" in request.FILES:
        upload_data["profile_picture"] = request.FILES["picture"]
    elif "profile_picture" in request.FILES:
        upload_data["profile_picture"] = request.FILES["profile_picture"]
    else:
        # Also check request.data for backward compatibility
        if "picture" in request.data:
            upload_data["profile_picture"] = request.data["picture"]
        elif "profile_picture" in request.data:
            upload_data["profile_picture"] = request.data["profile_picture"]

    serializer = ProfilePictureUploadSerializer(
        request.user, data=upload_data, partial=True
    )

    if serializer.is_valid():
        # Debug: Check what data is being passed
        print(f"DEBUG: Request FILES: {request.FILES}")
        print(f"DEBUG: Request data: {request.data}")
        print(f"DEBUG: Upload data: {upload_data}")
        print(f"DEBUG: Serializer validated data: {serializer.validated_data}")

        # Note: Cloudinary automatically handles old image replacement
        # No need to manually delete old files

        # Save new profile picture
        serializer.save()

        # Debug: Check after save
        print(f"DEBUG: User profile picture after save: {request.user.profile_picture}")

        # Refresh user instance from database to get updated profile picture
        request.user.refresh_from_db()

        # Debug: Check after refresh
        print(
            f"DEBUG: User profile picture after refresh: {request.user.profile_picture}"
        )

        # Return updated profile information
        updated_profile = UserProfileSerializer(request.user)

        return Response(
            {
                "message": "Profile picture uploaded successfully",
                "profile_picture_url": (
                    request.user.profile_picture.url
                    if request.user.profile_picture
                    else None
                ),
                "profile": updated_profile.data,
            },
            status=status.HTTP_200_OK,
        )

    print(f"DEBUG: Serializer errors: {serializer.errors}")
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="delete",
    operation_description="Remove user's profile picture",
    operation_summary="Remove profile picture",
    responses={
        200: openapi.Response(
            description="Profile picture removed successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "profile": openapi.Schema(type=openapi.TYPE_OBJECT),
                },
            ),
        ),
        404: openapi.Response(description="No profile picture to remove"),
        401: openapi.Response(description="Authentication required"),
    },
    tags=["Profile"],
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_profile_picture_api(request):
    """
    Remove the authenticated user's profile picture.

    Sets the profile_picture field to None. Cloudinary automatically handles file cleanup.
    """
    if not request.user.profile_picture:
        return Response(
            {"message": "No profile picture to remove"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Clear the profile picture field
    # Note: Cloudinary automatically handles file cleanup when the field is cleared
    request.user.profile_picture = None
    request.user.save()

    # Return updated profile information
    updated_profile = UserProfileSerializer(request.user)

    return Response(
        {
            "message": "Profile picture removed successfully",
            "profile": updated_profile.data,
        },
        status=status.HTTP_200_OK,
    )


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
                    "vendor_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "store_name": openapi.Schema(type=openapi.TYPE_STRING),
                    "subscription_expiry": openapi.Schema(
                        type=openapi.TYPE_STRING, format="date-time"
                    ),
                    "subscription_status": openapi.Schema(type=openapi.TYPE_STRING),
                    "warning": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Warning message if payment setup is incomplete",
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
@transaction.atomic
def register_vendor_api(request):
    """
    Register the authenticated user as a vendor.

    Requires authentication. Creates a vendor profile for the current user
    with store details and bank account information for payment processing.
    """
    # Check if user is already a vendor
    if hasattr(request.user, "vendor_profile"):
        return Response(
            {"error": "User is already registered as a vendor"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = VendorRegisterSerializer(
        data=request.data, context={"request": request}
    )

    if serializer.is_valid():
        try:
            vendor = serializer.save()

            # Send vendor welcome email in the background
            try:
                send_vendor_welcome_email(vendor)
                email_message = "Vendor welcome email sent successfully!"
            except Exception as e:
                # Log the error but don't fail the registration
                logger.error(
                    f"Failed to send vendor welcome email to {vendor.user.email}: {str(e)}"
                )
                email_message = "Vendor account created successfully (welcome email failed to send)."

            # Prepare response data
            response_data = {
                "success": True,
                "vendor_id": vendor.id,
                "message": f"Vendor account created successfully! {email_message}",
                "store_name": vendor.store_name,
                "store_logo_url": (
                    vendor.store_logo.url
                    if getattr(vendor, "store_logo", None)
                    else None
                ),
                "subscription_expiry": (
                    vendor.subscription_expiry.isoformat()
                    if vendor.subscription_expiry
                    else None
                ),
                "subscription_status": vendor.subscription_status,
            }

            # Add warning if Paystack setup might have failed
            if not vendor.subaccount_code:
                response_data["warning"] = (
                    "Vendor account created but payment setup may be incomplete. Please contact support if needed."
                )

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Log the error
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Vendor registration failed for user {request.user.id}: {str(e)}"
            )

            return Response(
                {"error": "Failed to create vendor account. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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
        return Response({"error": "User is not a vendor."}, status=403)

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
        "subscription_status": vendor_profile.subscription_status,
        "subscription_expiry": (
            vendor_profile.subscription_expiry.isoformat()
            if vendor_profile.subscription_expiry
            else None
        ),
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
        return Response({"error": "User is not a vendor."}, status=403)

    # Use partial=True for PATCH, False for PUT
    serializer = VendorUpdateSerializer(
        vendor, data=request.data, partial=(request.method == "PATCH")
    )

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=200)
    else:
        return Response(serializer.errors, status=400)


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
            {"is_vendor": False, "message": "User is not registered as a vendor"},
            status=403,
        )

    # Calculate subscription details
    now = timezone.now()
    is_active = vendor.is_subscription_active()

    # Calculate days remaining
    days_remaining = 0
    in_grace_period = False
    if vendor.subscription_expiry:
        time_diff = vendor.subscription_expiry - now
        days_remaining = time_diff.days

        # Check if in grace period (expired but within 7 days)
        if days_remaining < 0:
            grace_period_end = vendor.subscription_expiry + timedelta(days=7)
            in_grace_period = now <= grace_period_end

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
            "subscription_status": vendor.subscription_status,
            "subscription_start": (
                vendor.subscription_start.isoformat()
                if vendor.subscription_start
                else None
            ),
            "subscription_expiry": (
                vendor.subscription_expiry.isoformat()
                if vendor.subscription_expiry
                else None
            ),
            "is_active": is_active,
            "days_remaining": days_remaining,
            "in_grace_period": in_grace_period,
            "plan": plan_info,
            "product_usage": product_usage,
        },
        status=200,
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
        return Response({"detail": "Product limit reached for your plan."}, status=403)
    serializer = ProductCreateSerializer(data=request.data)
    if serializer.is_valid():
        product = serializer.save(vendor=request.user.vendor_profile)
        return Response({"success": True, "product_id": product.id})
    return Response(serializer.errors, status=400)


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
@parser_classes([MultiPartParser, FormParser])
def edit_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response(
            {"error": "Product not found or unauthorized"},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ProductCreateSerializer(product, data=request.data, partial=True)
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
            {"detail": "Only vendors can access this endpoint."},
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
            {"detail": "Only vendors can access this view."},
            status=status.HTTP_403_FORBIDDEN,
        )

    vendor = request.user.vendor_profile

    if not order.items.filter(product__vendor=vendor).exists():
        return Response(
            {"detail": "You are not authorized to view this order."},
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
            {"detail": "Order item not found or unauthorized."},
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
            {"detail": "Only vendors can access this endpoint."},
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

    # Get rating breakdown (count for each star rating)
    rating_breakdown = {
        "5_star": all_reviews.filter(rating=5).count(),
        "4_star": all_reviews.filter(rating=4).count(),
        "3_star": all_reviews.filter(rating=3).count(),
        "2_star": all_reviews.filter(rating=2).count(),
        "1_star": all_reviews.filter(rating=1).count(),
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
            {"detail": "Vendor not found."},
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
    return Response(serializer.data, status=200)


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

    # Get all vendor's products
    vendor_products = Product.objects.filter(vendor=vendor)

    # Rating and Review Statistics
    from django.db.models import Avg, Count, Sum

    all_reviews = Review.objects.filter(product__vendor=vendor, approved_review=True)
    rating_stats = all_reviews.aggregate(
        average_rating=Avg("rating"), total_reviews=Count("id")
    )

    # Rating breakdown
    rating_breakdown = {
        "5_star": all_reviews.filter(rating=5).count(),
        "4_star": all_reviews.filter(rating=4).count(),
        "3_star": all_reviews.filter(rating=3).count(),
        "2_star": all_reviews.filter(rating=2).count(),
        "1_star": all_reviews.filter(rating=1).count(),
    }

    # Sales Statistics
    vendor_order_items = OrderItem.objects.filter(
        product__vendor=vendor, order__is_paid=True
    )

    sales_stats = vendor_order_items.aggregate(
        total_orders=Count("order", distinct=True),
        total_revenue=Sum("price"),
        total_products_sold=Sum("quantity"),
    )

    # Product Statistics
    product_stats = {
        "total_products": vendor_products.count(),
        "active_products": vendor_products.filter(status=Product.ACTIVE).count(),
        "out_of_stock": vendor_products.filter(quantity=0).count(),
        "low_stock": vendor_products.filter(quantity__lte=5, quantity__gt=0).count(),
        "total_inventory": vendor_products.aggregate(Sum("quantity"))["quantity__sum"]
        or 0,
    }

    # Subscription Information with Enhanced Analytics
    now = timezone.now()
    days_remaining = vendor.get_subscription_days_remaining()
    is_in_grace = vendor.is_in_grace_period()

    # Get subscription history analytics
    from .models import SubscriptionHistory

    subscription_history = SubscriptionHistory.objects.filter(vendor=vendor)

    # Payment analytics
    payment_success_count = subscription_history.filter(
        event_type="payment_success"
    ).count()
    payment_failed_count = subscription_history.filter(
        event_type="payment_failed"
    ).count()
    total_payments = (
        subscription_history.filter(
            event_type="payment_success", amount__isnull=False
        ).aggregate(Sum("amount"))["amount__sum"]
        or 0
    )

    # Trial and subscription analytics
    trial_analytics = {}
    if vendor.trial_start and vendor.trial_end:
        trial_analytics = {
            "trial_started": vendor.trial_start.isoformat(),
            "trial_ends": vendor.trial_end.isoformat(),
            "trial_days_used": (
                (now - vendor.trial_start).days if now > vendor.trial_start else 0
            ),
            "trial_days_remaining": (
                max(0, (vendor.trial_end - now).days) if vendor.trial_end > now else 0
            ),
        }

    subscription_info = {
        "status": vendor.subscription_status,
        "days_remaining": days_remaining,
        "is_in_grace_period": is_in_grace,
        "plan_name": vendor.plan.name if vendor.plan else None,
        "plan_price": float(vendor.plan.price) if vendor.plan else 0,
        "max_products": vendor.plan.max_products if vendor.plan else 0,
        "expires_at": (
            vendor.subscription_expiry.isoformat()
            if vendor.subscription_expiry
            else None
        ),
        "last_payment": (
            vendor.last_payment_date.isoformat() if vendor.last_payment_date else None
        ),
        "failed_payment_count": vendor.failed_payment_count,
        "analytics": {
            "successful_payments": payment_success_count,
            "failed_payments": payment_failed_count,
            "total_payments_value": float(total_payments),
            "average_payment": (
                float(total_payments / payment_success_count)
                if payment_success_count > 0
                else 0
            ),
            "subscription_changes": subscription_history.filter(
                event_type__in=["plan_upgraded", "plan_downgraded"]
            ).count(),
            "trial_info": trial_analytics if trial_analytics else None,
        },
    }

    # Response data
    kpis_data = {
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

    return Response(kpis_data, status=status.HTTP_200_OK)


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
        return Response({"error": "User is not a vendor."}, status=400)

    # Validate request data using serializer
    serializer = SubscriptionInitiateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    plan_id = serializer.validated_data["plan_id"]

    try:
        selected_plan = VendorPlan.objects.get(id=plan_id, is_active=True)
    except VendorPlan.DoesNotExist:
        return Response({"error": "Invalid or inactive plan."}, status=404)

    # Handle free plans
    if selected_plan.price == 0:
        vendor.plan = selected_plan
        vendor.subscription_status = "active"
        vendor.subscription_start = timezone.now()
        vendor.subscription_expiry = timezone.now() + timedelta(days=30)
        vendor.save()
        return Response(
            {
                "message": "Successfully subscribed to free plan",
                "plan": selected_plan.name,
                "expiry": vendor.subscription_expiry.isoformat(),
            },
            status=200,
        )

    # Handle paid plans
    # if not selected_plan.paystack_plan_code:
    #     return Response(
    #         {"error": "Selected plan is not available for subscription at this time."},
    #         status=400,
    #     )

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
        "https://api.paystack.co/transaction/initialize", json=payload, headers=headers
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
            status=200,
        )
    else:
        return Response(
            {"error": res_data.get("message", "Paystack error")}, status=400
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
        return Response({"error": "User is not a vendor."}, status=403)

    if vendor.subscription_status == "cancelled":
        return Response({"message": "Subscription already cancelled."}, status=400)

    subscription_code = getattr(vendor, "paystack_subscription_code", None)
    if subscription_code:
        url = f"https://api.paystack.co/subscription/disable"
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

    return Response({"message": "Subscription cancelled successfully."}, status=200)


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
        return Response({"error": "User is not a vendor."}, status=403)

    reason = request.data.get("reason", "")

    if vendor.pause_subscription(reason):
        return Response(
            {
                "message": "Subscription paused successfully.",
                "status": vendor.subscription_status,
                "reason": reason,
            },
            status=200,
        )
    else:
        return Response(
            {
                "error": f"Cannot pause subscription. Current status: {vendor.subscription_status}"
            },
            status=400,
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
        return Response({"error": "User is not a vendor."}, status=403)

    if vendor.resume_subscription():
        return Response(
            {
                "message": "Subscription resumed successfully.",
                "status": vendor.subscription_status,
            },
            status=200,
        )
    else:
        return Response(
            {
                "error": f"Cannot resume subscription. Current status: {vendor.subscription_status}"
            },
            status=400,
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

    print(f"[CHANGE_PLAN] Change plan request initiated by user: {request.user.id}")
    print(f"[CHANGE_PLAN] Request data: {request.data}")

    try:
        vendor = request.user.vendor_profile
        print(f"[VENDOR] Vendor found: {vendor.id} - {vendor.store_name}")
        print(
            f"[VENDOR] Current vendor plan: {vendor.plan.name if vendor.plan else 'None'}"
        )
        print(f"[VENDOR] Current subscription status: {vendor.subscription_status}")
    except VendorProfile.DoesNotExist:
        print(f"[ERROR] User {request.user.id} is not a vendor")
        return Response({"error": "User is not a vendor."}, status=403)

    # Use serializer for validation
    print("[VALIDATION] Starting request validation with ChangePlanSerializer")
    serializer = ChangePlanSerializer(data=request.data, context={"vendor": vendor})
    if not serializer.is_valid():
        print(f"[ERROR] Validation failed: {serializer.errors}")
        return Response(serializer.errors, status=400)

    validated_data = serializer.validated_data
    plan_id = validated_data["plan_id"]
    immediate = validated_data["immediate"]

    print(f"[SUCCESS] Validation passed - Plan ID: {plan_id}, Immediate: {immediate}")

    try:
        new_plan = VendorPlan.objects.get(id=plan_id, is_active=True)
        print(f"[PLAN] Target plan found: {new_plan.name} (NGN {new_plan.price}/month)")
    except VendorPlan.DoesNotExist:
        print(f"[ERROR] Plan not found or inactive: {plan_id}")
        return Response({"error": "Plan not found or inactive."}, status=404)

    # Log plan change attempt details
    old_plan_name = vendor.plan.name if vendor.plan else "None"
    print(f"[CHANGE_PLAN] Attempting plan change: {old_plan_name} -> {new_plan.name}")

    if vendor.subscription_expiry:
        days_remaining = vendor.get_subscription_days_remaining()
        print(f"[SUBSCRIPTION] Subscription expiry: {vendor.subscription_expiry}")
        print(f"[SUBSCRIPTION] Days remaining: {days_remaining}")
    else:
        print("[SUBSCRIPTION] No subscription expiry set")

    # Use transaction for atomic operation
    try:
        print("[PAYMENT] Calling change_plan_with_payment method")
        result = vendor.change_plan_with_payment(
            new_plan, immediate=immediate, request=request
        )

        print(f"[PAYMENT] Change plan result: {result}")

        if result and result.get("success"):
            print("[SUCCESS] Plan change successful!")
            print(f"[PAYMENT] Prorated amount: NGN {result.get('prorated_amount', 0)}")
            print(f"[PLAN] Is upgrade: {result.get('is_upgrade', False)}")
            print(
                f"[PAYMENT] Payment status: {result.get('payment_status', 'completed')}"
            )

            response_data = {
                "message": f"Plan {'upgraded' if result['is_upgrade'] else 'downgraded'} successfully.",
                "old_plan": result["old_plan"],
                "new_plan": result["new_plan"],
                "prorated_amount": result["prorated_amount"],
                "is_upgrade": result["is_upgrade"],
                "payment_status": result.get("payment_status", "completed"),
            }

            # Add payment URL if payment is required
            if result.get("authorization_url"):
                response_data["authorization_url"] = result["authorization_url"]
                response_data["payment_status"] = "payment_required"
                print(
                    f"[PAYMENT] Payment required - Authorization URL generated: {result['authorization_url'][:50]}..."
                )

            print(f"[RESPONSE] Sending successful response: {response_data}")
            return Response(response_data, status=200)
        else:
            error_message = (
                result.get("error", "Failed to change plan.")
                if result
                else "Failed to change plan."
            )
            print(f"[ERROR] Plan change failed: {error_message}")
            return Response({"error": error_message}, status=400)

    except PaymentProcessingError as e:
        print(f"[ERROR] Payment processing error during plan change: {str(e)}")
        return Response({"error": f"Payment processing failed: {str(e)}"}, status=502)
    except Exception as e:
        print(f"[ERROR] Unexpected error during plan change: {str(e)}")
        import traceback

        traceback.print_exc()
        return Response(
            {"error": "An unexpected error occurred. Please try again."}, status=500
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
        return Response({"error": "User is not a vendor."}, status=403)

    from .models import SubscriptionHistory
    from .serializers import SubscriptionHistorySerializer

    history = SubscriptionHistory.objects.filter(vendor=vendor).order_by("-created_at")

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(history, request)

    serializer = SubscriptionHistorySerializer(result_page, many=True)
    return paginator.get_paginated_response(serializer.data)


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
        return HttpResponse(status=401)

    try:
        event_data = json.loads(payload.decode("utf-8"))
    except Exception as e:
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
    vendor.subscription_expiry = now + timezone.timedelta(days=30)
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
    from django.utils import timezone
    from datetime import timedelta

    try:
        # Get plan details from metadata
        new_plan_id = metadata.get("new_plan_id")
        old_plan_id = metadata.get("old_plan_id")
        prorated_amount = metadata.get("prorated_amount", 0)
        is_trial_upgrade = metadata.get("is_trial_upgrade", False)

        if not new_plan_id:
            print(
                f"[ERROR] Missing new_plan_id in plan change payment metadata: {metadata}"
            )
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
            print(f"[WEBHOOK] Converting trial user to active paid subscription")
            vendor.subscription_status = "active"
            vendor.subscription_expiry = timezone.now() + timedelta(days=30)
            vendor.trial_start = None
            vendor.trial_end = None
            print(f"[WEBHOOK] New subscription expiry: {vendor.subscription_expiry}")

        # Update Paystack subscription if vendor has one
        if vendor.paystack_subscription_code and new_plan.paystack_plan_code:
            try:
                vendor._update_paystack_subscription(new_plan)
                print("[SUCCESS] [Webhook] Paystack subscription updated successfully")
            except Exception as e:
                print(
                    f"[WARNING] [Webhook] Failed to update Paystack subscription for vendor {vendor.id}: {str(e)}"
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

        print(
            f"[SUCCESS] Plan change payment successful for vendor: {vendor.id} | "
            f"Changed from {old_plan.name if old_plan else 'None'} to {new_plan.name} | "
            f"Amount: NGN {amount} | Trial upgrade: {is_trial_upgrade}"
        )
        return HttpResponse(status=200)

    except VendorPlan.DoesNotExist:
        print(
            f"[ERROR] Plan not found during plan change payment processing: {metadata}"
        )
        return HttpResponse(status=404)
    except Exception as e:
        print(f"[ERROR] Error processing plan change payment: {str(e)}")
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
