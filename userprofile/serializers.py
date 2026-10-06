import logging
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from operations.config import get_settings
from store.utils import PaystackError, create_paystack_subaccount
from vendorxpert.uploads import media_url, validate_image_upload

from .bank_codes import VALID_BANK_CODES
from .models import (
    SubscriptionHistory,
    UserProfile,
    VendorPlan,
    VendorProfile,
    normalize_email_address,
)
from .phone_utils import normalize_and_validate_nigerian_phone

logger = logging.getLogger(__name__)

STORE_DESCRIPTION_MAX_LENGTH = 500
_FORBIDDEN_NAME_CHARS = set("<>&\"'")


def _isoformat_or_none(value):
    return value.isoformat() if value is not None else None


def vendor_subscription_payload(vendor):
    return {
        "subscription_status": vendor.get_effective_subscription_status(),
        "subscription_expiry": _isoformat_or_none(vendor.get_effective_subscription_expiry()),
        "raw_subscription_status": vendor.subscription_status,
        "raw_subscription_expiry": _isoformat_or_none(vendor.subscription_expiry),
        "trial_start": _isoformat_or_none(vendor.trial_start),
        "trial_end": _isoformat_or_none(vendor.trial_end),
    }


def store_details_payload(vendor):
    """Store summary returned at login and after vendor signup."""
    return {
        "store_name": vendor.store_name,
        "store_logo_url": media_url(vendor.store_logo),
        "store_description": vendor.store_description,
        "phone_number": str(vendor.phone_number) if vendor.phone_number else None,
        "whatsapp_number": str(vendor.whatsapp_number) if vendor.whatsapp_number else None,
        "instagram_handle": vendor.instagram_handle,
        "tiktok_handle": vendor.tiktok_handle,
        "is_verified": vendor.is_verified,
        **vendor_subscription_payload(vendor),
    }


def _clean_handle(value):
    return (value or "").strip().lstrip("@")[:50]


# ── Accounts ────────────────────────────────────────────────────────────────


class UserProfileSerializer(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField()
    vendor_info = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "id",
            "user_name",
            "email",
            "first_name",
            "last_name",
            "hostel",
            "profile_picture",
            "start_date",
            "is_vendor",
            "vendor_info",
        ]

    def get_profile_picture(self, user):
        return media_url(user.profile_picture)

    def get_vendor_info(self, user):
        vendor = getattr(user, "vendor_profile", None)
        if vendor is None:
            return None
        return {"id": vendor.pk, **store_details_payload(vendor)}


class ProfileUpdateSerializer(serializers.ModelSerializer):
    hostel = serializers.ChoiceField(
        choices=UserProfile.HOSTEL_CHOICES, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = UserProfile
        fields = ["first_name", "last_name", "hostel"]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
        }

    def validate_first_name(self, value):
        return value.strip()

    def validate_last_name(self, value):
        return value.strip()

    def validate_hostel(self, value):
        return value or None


class ProfilePictureUploadSerializer(serializers.ModelSerializer):
    profile_picture = serializers.ImageField()

    class Meta:
        model = UserProfile
        fields = ["profile_picture"]

    def validate_profile_picture(self, value):
        return validate_image_upload(value)


class SignupSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)

    class Meta:
        model = UserProfile
        fields = ["user_name", "email", "first_name", "last_name", "password"]

    def validate_email(self, value):
        value = normalize_email_address(value)
        if UserProfile.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists. Try signing in instead."
            )
        return value

    def validate_user_name(self, value):
        value = value.strip()
        if UserProfile.objects.filter(user_name__iexact=value).exists():
            raise serializers.ValidationError("This username is taken. Try another one.")
        return value

    def validate_first_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("First name is required.")
        return value

    def validate_last_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Last name is required.")
        return value

    def validate(self, attrs):
        candidate = UserProfile(
            email=attrs.get("email", ""),
            user_name=attrs.get("user_name", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


# ── Vendors ─────────────────────────────────────────────────────────────────


class VendorRegisterSerializer(serializers.Serializer):
    store_name = serializers.CharField(max_length=150)
    store_description = serializers.CharField(
        required=False, allow_blank=True, max_length=STORE_DESCRIPTION_MAX_LENGTH
    )
    account_number = serializers.CharField(max_length=20)
    bank_code = serializers.CharField(max_length=10)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    whatsapp_number = serializers.CharField(required=False, allow_blank=True)
    store_logo = serializers.ImageField(required=False)

    def validate_store_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Store name must be at least 3 characters.")
        if _FORBIDDEN_NAME_CHARS & set(value):
            raise serializers.ValidationError("Store name can't contain < > & or quotes.")
        return value

    def validate_account_number(self, value):
        value = value.replace(" ", "").replace("-", "")
        if not value.isdigit() or len(value) != 10:
            raise serializers.ValidationError("Account number must be exactly 10 digits.")
        return value

    def validate_bank_code(self, value):
        value = value.strip()
        if value not in VALID_BANK_CODES:
            raise serializers.ValidationError("Choose your bank from the list.")
        return value

    def _validate_unique_phone(self, value, field, label):
        if not value or not str(value).strip():
            return None
        phone = normalize_and_validate_nigerian_phone(value, label)
        # Half-created stores from failed sign-up attempts (no payout account)
        # must not block a legitimate retry.
        taken = VendorProfile.objects.filter(**{field: phone}).exclude(
            subaccount_code__isnull=True
        ).exclude(subaccount_code="")
        if taken.exists():
            raise serializers.ValidationError(f"This {label} is already used by another store.")
        return phone

    def validate_phone_number(self, value):
        return self._validate_unique_phone(value, "phone_number", "phone number")

    def validate_whatsapp_number(self, value):
        return self._validate_unique_phone(value, "whatsapp_number", "WhatsApp number")

    def validate_store_logo(self, value):
        return validate_image_upload(value)

    def create(self, validated_data):
        user = self.context["request"].user
        account_number = validated_data.pop("account_number")
        bank_code = validated_data.pop("bank_code")
        store_logo = validated_data.pop("store_logo", None)
        store_name = validated_data["store_name"]

        plan = (
            VendorPlan.objects.filter(name=VendorPlan.BASIC, is_active=True).first()
            or VendorPlan.objects.filter(is_active=True).order_by("price").first()
        )
        now = timezone.now()
        trial_days = get_settings().trial_days

        with transaction.atomic():
            vendor = VendorProfile.objects.create(
                user=user,
                plan=plan,
                store_name=store_name,
                store_description=validated_data.get("store_description")
                or f"Welcome to {store_name}!",
                phone_number=validated_data.get("phone_number"),
                whatsapp_number=validated_data.get("whatsapp_number"),
                subscription_status="trial",
                trial_start=now,
                trial_end=now + timedelta(days=trial_days),
                is_verified=True,
            )
            if store_logo:
                vendor.store_logo = store_logo
                vendor.save(update_fields=["store_logo"])
            user.is_vendor = True
            user.save(update_fields=["is_vendor"])
            SubscriptionHistory.log_event(
                vendor=vendor,
                event_type="trial_started",
                new_plan=plan,
                new_status="trial",
                notes=f"{trial_days}-day free trial started",
            )

        # External call outside the transaction so a slow Paystack doesn't
        # hold the database. On failure the half-created store is removed.
        try:
            create_paystack_subaccount(vendor, account_number, bank_code)
        except PaystackError as exc:
            logger.warning("Paystack subaccount failed for user %s: %s", user.pk, exc.message)
            with transaction.atomic():
                vendor.delete()
                user.is_vendor = False
                user.save(update_fields=["is_vendor"])
            raise serializers.ValidationError(
                {
                    "account_number": [
                        "We couldn't set up payouts to this account. "
                        "Check the account number and bank, then try again."
                    ]
                }
            )
        return vendor


class VendorUpdateSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(required=False, allow_blank=True)
    whatsapp_number = serializers.CharField(required=False, allow_blank=True)
    store_logo = serializers.ImageField(required=False)
    store_description = serializers.CharField(
        required=False, allow_blank=True, max_length=STORE_DESCRIPTION_MAX_LENGTH
    )

    class Meta:
        model = VendorProfile
        fields = [
            "store_name",
            "store_description",
            "store_logo",
            "phone_number",
            "whatsapp_number",
            "instagram_handle",
            "tiktok_handle",
        ]

    def validate_store_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Store name must be at least 3 characters.")
        if _FORBIDDEN_NAME_CHARS & set(value):
            raise serializers.ValidationError("Store name can't contain < > & or quotes.")
        return value

    def validate_store_logo(self, value):
        return validate_image_upload(value)

    def validate_instagram_handle(self, value):
        return _clean_handle(value)

    def validate_tiktok_handle(self, value):
        return _clean_handle(value)

    def _validate_unique_phone(self, value, field, label):
        if not value or not str(value).strip():
            return None
        phone = normalize_and_validate_nigerian_phone(value, label)
        clash = VendorProfile.objects.filter(**{field: phone}).exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f"This {label} is already used by another store.")
        return phone

    def validate_phone_number(self, value):
        return self._validate_unique_phone(value, "phone_number", "phone number")

    def validate_whatsapp_number(self, value):
        return self._validate_unique_phone(value, "whatsapp_number", "WhatsApp number")


class VendorListSerializer(serializers.ModelSerializer):
    """Public vendor card. Expects ``listed_product_count``/``avg_rating`` annotations."""

    store_logo = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    whatsapp_number = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = [
            "id",
            "store_name",
            "store_logo",
            "store_description",
            "phone_number",
            "whatsapp_number",
            "instagram_handle",
            "tiktok_handle",
            "is_verified",
            "product_count",
            "average_rating",
        ]

    def get_store_logo(self, vendor):
        return media_url(vendor.store_logo)

    def get_phone_number(self, vendor):
        return str(vendor.phone_number) if vendor.phone_number else None

    def get_whatsapp_number(self, vendor):
        return str(vendor.whatsapp_number) if vendor.whatsapp_number else None

    def get_product_count(self, vendor):
        return getattr(vendor, "listed_product_count", 0) or 0

    def get_average_rating(self, vendor):
        average = getattr(vendor, "avg_rating", None)
        return round(average, 1) if average is not None else 0


class VendorPlanSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()

    class Meta:
        model = VendorPlan
        fields = ["id", "name", "display_name", "description", "price", "max_products", "features", "is_active"]

    def get_display_name(self, plan):
        return str(plan).title()

    def get_features(self, plan):
        return [line.strip() for line in (plan.features or "").splitlines() if line.strip()]


class SubscriptionInitiateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()

    def validate_plan_id(self, value):
        if not VendorPlan.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError("That plan isn't available.")
        return value


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    previous_plan_name = serializers.CharField(source="previous_plan.name", read_only=True, default=None)
    new_plan_name = serializers.CharField(source="new_plan.name", read_only=True, default=None)
    event_display = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = SubscriptionHistory
        fields = [
            "id",
            "event_type",
            "event_display",
            "previous_plan_name",
            "new_plan_name",
            "previous_status",
            "new_status",
            "amount",
            "payment_reference",
            "notes",
            "created_at",
        ]
        read_only_fields = fields
