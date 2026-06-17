"""Authentication, signup, password reset, JWT, and profile endpoints."""
from rest_framework.decorators import api_view, permission_classes, parser_classes, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import login
from .serializers import (
    SignupSerializer,
    UserProfileSerializer,
    ProfileUpdateSerializer,
    ProfilePictureUploadSerializer,
)
from .models import EmailVerification, UserProfile
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from datetime import timedelta
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .email_utils import (
    send_welcome_email,
    send_verification_email,
    send_password_reset_email,
)
from django.contrib.auth.hashers import make_password
import random
import hmac
import logging
import jwt
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from .throttles import SignupRateThrottle, LoginRateThrottle, PasswordResetRateThrottle

# ── Module-level constants ──────────────────────────────────────────────────
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 15
SUBSCRIPTION_RENEWAL_DAYS = 30

logger = logging.getLogger(__name__)

INVALID_REFRESH_TOKEN_DETAIL = {"detail": "Refresh token expired or invalid."}


def _blacklist_all_refresh_tokens_for_user(user_id):
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for outstanding_token in OutstandingToken.objects.filter(user_id=user_id):
        BlacklistedToken.objects.get_or_create(token=outstanding_token)


def _decode_signed_refresh_payload(refresh_token):
    options = {"verify_exp": False}
    decode_kwargs = {
        "algorithms": [jwt_api_settings.ALGORITHM],
        "options": options,
    }

    if jwt_api_settings.AUDIENCE is not None:
        decode_kwargs["audience"] = jwt_api_settings.AUDIENCE
    else:
        options["verify_aud"] = False

    if jwt_api_settings.ISSUER is not None:
        decode_kwargs["issuer"] = jwt_api_settings.ISSUER
    else:
        options["verify_iss"] = False

    signing_key = (
        getattr(jwt_api_settings, "VERIFYING_KEY", None) or jwt_api_settings.SIGNING_KEY
    )
    return jwt.decode(refresh_token, signing_key, **decode_kwargs)


def _revoke_user_tokens_if_refresh_reused(refresh_token):
    try:
        payload = _decode_signed_refresh_payload(refresh_token)
    except jwt.PyJWTError:
        return

    if payload.get(jwt_api_settings.TOKEN_TYPE_CLAIM) != "refresh":
        return

    jti = payload.get(jwt_api_settings.JTI_CLAIM)
    user_id = payload.get(jwt_api_settings.USER_ID_CLAIM)
    if not jti or not user_id:
        return

    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

    if BlacklistedToken.objects.filter(token__jti=jti).exists():
        _blacklist_all_refresh_tokens_for_user(user_id)


from .services import _isoformat_or_none  # noqa: E402 — after local helpers


def _vendor_subscription_payload(vendor):
    return {
        "subscription_status": vendor.get_effective_subscription_status(),
        "subscription_expiry": _isoformat_or_none(
            vendor.get_effective_subscription_expiry()
        ),
        "raw_subscription_status": vendor.subscription_status,
        "raw_subscription_expiry": _isoformat_or_none(vendor.subscription_expiry),
        "trial_start": _isoformat_or_none(vendor.trial_start),
        "trial_end": _isoformat_or_none(vendor.trial_end),
    }


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
@throttle_classes([SignupRateThrottle])
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

        code = "".join(random.choices("0123456789", k=OTP_LENGTH))

        # Store hashed password in payload so we don't keep plaintext
        hashed = make_password(data.get("password"))

        expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

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
            status=status.HTTP_200_OK,
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
    except Exception as e:
        logger.warning(f"Auto-login after email verification failed for {email}: {e}")

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

    new_code = "".join(random.choices("0123456789", k=OTP_LENGTH))

    ev.code = new_code
    ev.expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
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
        status=status.HTTP_200_OK,
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
@throttle_classes([PasswordResetRateThrottle])
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
            status=status.HTTP_200_OK,
        )

    code = "".join(random.choices("0123456789", k=OTP_LENGTH))
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

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
        status=status.HTTP_200_OK,
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

    # Delete any previous verified-but-unused reset records for this email so
    # we don't hit the unique_together (email, type, is_used) constraint below.
    EmailVerification.objects.filter(
        email=email, verification_type="password_reset", is_used=True
    ).delete()

    # Mark the OTP as consumed so it cannot be used a second time to obtain
    # another reset_token, then store the new token in the payload.
    ev.payload = {
        "reset_token": reset_token,
        "verified_at": timezone.now().isoformat(),
    }
    ev.is_used = True
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

    # Validate password strength using Django's configured validators.
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        validate_password(new_password)
    except DjangoValidationError as e:
        return Response(
            {"error": list(e.messages)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find the verified (OTP already consumed) reset record.
    # is_used=True because verify_reset_code_api marks it consumed when the OTP is verified.
    try:
        ev = EmailVerification.objects.get(
            email=email, verification_type="password_reset", is_used=True
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

    # Verify the reset token using constant-time comparison to prevent timing attacks.
    stored_token = ev.payload.get("reset_token")
    if not stored_token or not hmac.compare_digest(stored_token, reset_token):
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

    # Delete the record so this reset_token cannot be replayed.
    ev.delete()

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
    operation_description="Rotate a refresh token and return a new access/refresh token pair",
    security=[],
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["refresh_token"],
        properties={
            "refresh_token": openapi.Schema(
                type=openapi.TYPE_STRING, description="Current refresh token"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Token refresh successful",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "access_token": openapi.Schema(type=openapi.TYPE_STRING),
                    "refresh_token": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        401: openapi.Response(description="Refresh token expired or invalid"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token_api(request):
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        refresh = RefreshToken(refresh_token)
        user_id = refresh.payload.get(jwt_api_settings.USER_ID_CLAIM)
        if not user_id:
            raise TokenError("Token contained no recognizable user identification")

        user = UserProfile.objects.get(**{jwt_api_settings.USER_ID_FIELD: user_id})
        if not jwt_api_settings.USER_AUTHENTICATION_RULE(user):
            raise TokenError("User is inactive or deleted")

        refresh.blacklist()
        new_refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access_token": str(new_refresh.access_token),
                "refresh_token": str(new_refresh),
            },
            status=status.HTTP_200_OK,
        )
    except UserProfile.DoesNotExist:
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )
    except TokenError:
        _revoke_user_tokens_if_refresh_reused(refresh_token)
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )


@swagger_auto_schema(
    method="post",
    operation_description="Revoke the authenticated user's refresh tokens",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["refresh_token"],
        properties={
            "refresh_token": openapi.Schema(
                type=openapi.TYPE_STRING, description="Refresh token to revoke"
            ),
        },
    ),
    responses={
        200: openapi.Response(description="Logged out successfully"),
        401: openapi.Response(description="Authentication required or token invalid"),
    },
    tags=["Authentication"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_api(request):
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        refresh = RefreshToken(refresh_token)
    except TokenError:
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )

    token_user_id = refresh.payload.get(jwt_api_settings.USER_ID_CLAIM)
    request_user_id = getattr(request.user, jwt_api_settings.USER_ID_FIELD)
    if str(token_user_id) != str(request_user_id):
        return Response(
            INVALID_REFRESH_TOKEN_DETAIL, status=status.HTTP_401_UNAUTHORIZED
        )

    refresh.blacklist()
    _blacklist_all_refresh_tokens_for_user(request_user_id)

    return Response(
        {"detail": "Logged out successfully."}, status=status.HTTP_200_OK
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
@throttle_classes([LoginRateThrottle])
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
                **_vendor_subscription_payload(vendor),
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
        serializer.save()
        request.user.refresh_from_db()
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
