"""Authentication, signup, password reset, JWT, and profile endpoints."""

import hmac
import logging
import secrets
from datetime import datetime, timedelta

import jwt
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .email_utils import send_password_reset_email, send_verification_email, send_welcome_email
from .models import EmailVerification, UserProfile, normalize_email_address
from .serializers import (
    ProfilePictureUploadSerializer,
    ProfileUpdateSerializer,
    SignupSerializer,
    UserProfileSerializer,
    store_details_payload,
)
from .throttles import (
    LoginRateThrottle,
    OTPResendRateThrottle,
    OTPVerifyRateThrottle,
    PasswordResetRateThrottle,
    SignupRateThrottle,
)

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 15
RESET_TOKEN_TTL_SECONDS = 10 * 60

logger = logging.getLogger(__name__)

INVALID_REFRESH_TOKEN = {"error": "Your session has expired. Please sign in again."}
GENERIC_RESET_MESSAGE = (
    "If an account exists for this email, we've sent a reset code to it."
)


def _error(message, http_status=status.HTTP_400_BAD_REQUEST, code=None):
    body = {"error": message}
    if code:
        body["code"] = code
    return Response(body, status=http_status)


def _generate_otp():
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def _check_code(verification, submitted_code):
    """Validate a submitted OTP, counting failures. Returns an error Response or None."""
    if verification.is_locked():
        return _error(
            "Too many incorrect attempts. Request a new code.", code="code_locked"
        )
    if verification.is_expired():
        return _error("This code has expired. Request a new one.", code="code_expired")
    if not hmac.compare_digest(verification.code, str(submitted_code or "").strip()):
        EmailVerification.objects.filter(pk=verification.pk).update(
            attempts=verification.attempts + 1
        )
        remaining = verification.MAX_ATTEMPTS - verification.attempts - 1
        if remaining <= 0:
            return _error(
                "Too many incorrect attempts. Request a new code.", code="code_locked"
            )
        return _error(
            f"That code isn't right. {remaining} attempt{'s' if remaining != 1 else ''} left.",
            code="code_invalid",
        )
    return None


def _session_payload(user):
    """Tokens plus the user summary the frontend keeps in its session cookie."""
    refresh = RefreshToken.for_user(user)
    vendor = getattr(user, "vendor_profile", None)
    payload = {
        "user_id": user.pk,
        "email": user.email,
        "is_vendor": vendor is not None,
        "vendor_id": vendor.pk if vendor else None,
        "store_details": store_details_payload(vendor) if vendor else None,
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }
    return payload


# ── Refresh-token hygiene ───────────────────────────────────────────────────


def _blacklist_all_refresh_tokens_for_user(user_id):
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for outstanding_token in OutstandingToken.objects.filter(user_id=user_id):
        BlacklistedToken.objects.get_or_create(token=outstanding_token)


def _decode_signed_refresh_payload(refresh_token):
    options = {"verify_exp": False}
    decode_kwargs = {"algorithms": [jwt_api_settings.ALGORITHM], "options": options}
    if jwt_api_settings.AUDIENCE is not None:
        decode_kwargs["audience"] = jwt_api_settings.AUDIENCE
    else:
        options["verify_aud"] = False
    if jwt_api_settings.ISSUER is not None:
        decode_kwargs["issuer"] = jwt_api_settings.ISSUER
    else:
        options["verify_iss"] = False
    signing_key = getattr(jwt_api_settings, "VERIFYING_KEY", None) or jwt_api_settings.SIGNING_KEY
    return jwt.decode(refresh_token, signing_key, **decode_kwargs)


def _revoke_user_tokens_if_refresh_reused(refresh_token):
    """A blacklisted refresh token being presented again means it was stolen;
    revoke every session for that user."""
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
        logger.warning("Refresh token reuse detected for user %s; revoking sessions", user_id)
        _blacklist_all_refresh_tokens_for_user(user_id)


# ── Signup ──────────────────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SignupRateThrottle])
def signup_api(request):
    """Validate signup details and email a verification code.

    The account is only created once the code is confirmed, so nobody can
    register an email address they don't control.
    """
    serializer = SignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    email = data["email"]

    code = _generate_otp()
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    EmailVerification.objects.update_or_create(
        email=email,
        verification_type="signup",
        is_used=False,
        defaults={
            "code": code,
            "attempts": 0,
            "expires_at": expires_at,
            "payload": {
                "user_name": data["user_name"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "password_hashed": make_password(data["password"]),
            },
        },
    )

    if not send_verification_email(email, code, expires_at=expires_at):
        return _error(
            "We couldn't send your verification email. Please try again in a moment.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "email_failed",
        )
    return Response({"message": "We've sent a 6-digit code to your email.", "email": email})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([OTPVerifyRateThrottle])
def verify_signup_api(request):
    """Confirm the emailed code, create the account and sign the user in."""
    email = normalize_email_address(request.data.get("email"))
    code = request.data.get("code")
    if not email or not code:
        return _error("Enter the code we emailed you.")

    verification = EmailVerification.objects.filter(
        email=email, verification_type="signup", is_used=False
    ).first()
    if verification is None:
        return _error(
            "We couldn't find a pending signup for this email. Please sign up again.",
            code="no_pending_signup",
        )

    error = _check_code(verification, code)
    if error:
        return error

    payload = verification.payload
    try:
        with transaction.atomic():
            user = UserProfile(
                email=email,
                user_name=payload.get("user_name"),
                first_name=payload.get("first_name", ""),
                last_name=payload.get("last_name", ""),
                password=payload.get("password_hashed"),
            )
            user.save()
            verification.delete()
    except IntegrityError:
        return _error(
            "This email or username was registered while you were verifying. "
            "Try signing in, or sign up with a different username.",
            status.HTTP_409_CONFLICT,
            "account_exists",
        )

    if not send_welcome_email(user):
        logger.warning("Welcome email failed for user %s", user.pk)

    return Response(
        {"message": "Your account is ready.", **_session_payload(user)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([OTPResendRateThrottle])
def resend_verification_api(request):
    email = normalize_email_address(request.data.get("email"))
    if not email:
        return _error("Email is required.")

    verification = EmailVerification.objects.filter(
        email=email, verification_type="signup", is_used=False
    ).first()
    if verification is None:
        return _error(
            "We couldn't find a pending signup for this email. Please sign up again.",
            code="no_pending_signup",
        )

    verification.code = _generate_otp()
    verification.attempts = 0
    verification.expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    verification.save(update_fields=["code", "attempts", "expires_at"])

    if not send_verification_email(email, verification.code, expires_at=verification.expires_at):
        return _error(
            "We couldn't send the email. Please try again in a moment.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "email_failed",
        )
    return Response({"message": "We've sent you a new code."})


# ── Password reset ──────────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([PasswordResetRateThrottle])
def forgot_password_api(request):
    """Email a reset code. The response never reveals whether the email exists."""
    email = normalize_email_address(request.data.get("email"))
    if not email:
        return _error("Email is required.")

    user = UserProfile.objects.filter(email__iexact=email, is_active=True).first()
    if user is not None:
        code = _generate_otp()
        expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        EmailVerification.objects.update_or_create(
            email=email,
            verification_type="password_reset",
            is_used=False,
            defaults={"code": code, "attempts": 0, "payload": {}, "expires_at": expires_at},
        )
        if not send_password_reset_email(user.email, code, expires_at=expires_at):
            logger.error("Password reset email failed for user %s", user.pk)

    return Response({"message": GENERIC_RESET_MESSAGE})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([OTPVerifyRateThrottle])
def verify_reset_code_api(request):
    """Exchange a correct reset code for a short-lived, single-use reset token."""
    email = normalize_email_address(request.data.get("email"))
    code = request.data.get("code")
    if not email or not code:
        return _error("Enter the code we emailed you.")

    verification = EmailVerification.objects.filter(
        email=email, verification_type="password_reset", is_used=False
    ).first()
    if verification is None:
        return _error(
            "This code is no longer valid. Request a new one.", code="no_pending_reset"
        )

    error = _check_code(verification, code)
    if error:
        return error

    reset_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        EmailVerification.objects.filter(
            email=email, verification_type="password_reset", is_used=True
        ).delete()
        verification.payload = {
            "reset_token": reset_token,
            "verified_at": timezone.now().isoformat(),
        }
        verification.is_used = True
        verification.save(update_fields=["payload", "is_used"])

    return Response({"message": "Code confirmed. Choose a new password.", "reset_token": reset_token})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([OTPVerifyRateThrottle])
def reset_password_api(request):
    email = normalize_email_address(request.data.get("email"))
    reset_token = str(request.data.get("reset_token") or "")
    new_password = request.data.get("new_password") or ""
    if not email or not reset_token or not new_password:
        return _error("Email, reset token and new password are required.")

    verification = EmailVerification.objects.filter(
        email=email, verification_type="password_reset", is_used=True
    ).first()
    stored_token = (verification.payload or {}).get("reset_token") if verification else None
    if not stored_token or not hmac.compare_digest(stored_token, reset_token):
        return _error(
            "This reset link is no longer valid. Request a new code.", code="no_pending_reset"
        )

    verified_at = verification.payload.get("verified_at")
    try:
        verified_at = datetime.fromisoformat(verified_at)
    except (TypeError, ValueError):
        verified_at = None
    if verified_at is None or (timezone.now() - verified_at).total_seconds() > RESET_TOKEN_TTL_SECONDS:
        verification.delete()
        return _error(
            "Your reset session expired. Request a new code.", code="no_pending_reset"
        )

    user = UserProfile.objects.filter(email__iexact=email).first()
    if user is None:
        verification.delete()
        return _error("This reset link is no longer valid. Request a new code.", code="no_pending_reset")

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        return Response(
            {"error": exc.messages[0], "fields": {"new_password": list(exc.messages)}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        verification.delete()
    # Anyone holding an old session (e.g. whoever caused the reset) is signed out.
    _blacklist_all_refresh_tokens_for_user(user.pk)

    return Response({"message": "Your password has been changed. Sign in with your new password."})


# ── Sessions ────────────────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_api(request):
    email = normalize_email_address(request.data.get("email"))
    password = request.data.get("password") or ""
    if not email or not password:
        return _error("Enter your email and password.")

    user = authenticate(request, username=email, password=password)
    if user is None:
        inactive = UserProfile.objects.filter(email__iexact=email, is_active=False).first()
        if inactive is not None and inactive.check_password(password):
            return _error(
                "This account has been suspended. Contact support if you think this is a mistake.",
                status.HTTP_403_FORBIDDEN,
                "account_suspended",
            )
        if EmailVerification.objects.filter(
            email=email, verification_type="signup", is_used=False
        ).exists():
            return _error(
                "Please verify your email to finish creating your account.",
                status.HTTP_400_BAD_REQUEST,
                "email_not_verified",
            )
        return _error("Incorrect email or password.", status.HTTP_400_BAD_REQUEST, "invalid_credentials")

    return Response(_session_payload(user))


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token_api(request):
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return Response(INVALID_REFRESH_TOKEN, status=status.HTTP_401_UNAUTHORIZED)

    try:
        refresh = RefreshToken(refresh_token)
        user_id = refresh.payload.get(jwt_api_settings.USER_ID_CLAIM)
        user = UserProfile.objects.get(**{jwt_api_settings.USER_ID_FIELD: user_id})
        if not jwt_api_settings.USER_AUTHENTICATION_RULE(user):
            raise TokenError("User is inactive")
        refresh.blacklist()
        new_refresh = RefreshToken.for_user(user)
    except UserProfile.DoesNotExist:
        return Response(INVALID_REFRESH_TOKEN, status=status.HTTP_401_UNAUTHORIZED)
    except TokenError:
        _revoke_user_tokens_if_refresh_reused(refresh_token)
        return Response(INVALID_REFRESH_TOKEN, status=status.HTTP_401_UNAUTHORIZED)

    return Response(
        {"access_token": str(new_refresh.access_token), "refresh_token": str(new_refresh)}
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_api(request):
    """Revoke the given refresh token. Works even after the access token expired."""
    refresh_token = request.data.get("refresh_token")
    if refresh_token:
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            pass
    return Response({"message": "Signed out."})


# ── Profile ─────────────────────────────────────────────────────────────────


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def profile_api(request):
    if request.method in ("PUT", "PATCH"):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(UserProfileSerializer(request.user).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_profile_picture_api(request):
    upload = request.FILES.get("picture") or request.FILES.get("profile_picture")
    serializer = ProfilePictureUploadSerializer(
        request.user, data={"profile_picture": upload}, partial=True
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(UserProfileSerializer(request.user).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_profile_picture_api(request):
    request.user.profile_picture = None
    request.user.save(update_fields=["profile_picture"])
    return Response(UserProfileSerializer(request.user).data)
