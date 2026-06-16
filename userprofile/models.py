from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)
from phonenumber_field.modelfields import PhoneNumberField
from datetime import timedelta
from django.utils import timezone
import uuid
import logging
from cloudinary.models import CloudinaryField

logger = logging.getLogger(__name__)


class CustomAccountManager(BaseUserManager):
    def create_user(
        self, email, user_name, first_name, last_name, password, **other_fields
    ):

        if not email:
            raise ValueError(_("You must provide a valid email address"))

        email = self.normalize_email(email)
        user = self.model(
            email=email,
            user_name=user_name,
            first_name=first_name,
            last_name=last_name,
            **other_fields,
        )
        user.set_password(password)
        user.save()
        return user

    def create_superuser(
        self, email, user_name, first_name, last_name, password, **other_fields
    ):

        other_fields.setdefault("is_staff", True)
        other_fields.setdefault("is_superuser", True)
        other_fields.setdefault("is_active", True)

        if other_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must be assigned is_staff=True"))

        if other_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must be assigned is_superuser=True"))

        return self.create_user(
            email, user_name, first_name, last_name, password, **other_fields
        )


class UserProfile(AbstractBaseUser, PermissionsMixin):
    HOSTEL_CHOICES = [
        ("hall_1", "Hall 1"),
        ("hall_2", "Hall 2"),
        ("hall_3", "Hall 3"),
        ("hall_4", "Hall 4"),
        ("hall_5", "Hall 5"),
        ("hall_6", "Hall 6"),
        ("hall_7", "Hall 7"),
        ("hall_8", "Hall 8"),
    ]

    email = models.EmailField(_("email address"), unique=True)
    user_name = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    hostel = models.CharField(
        max_length=20,
        choices=HOSTEL_CHOICES,
        blank=True,
        null=True,
        help_text="Select your hostel",
    )
    profile_picture = CloudinaryField(
        "image",
        folder="profile_pictures",
        blank=True,
        null=True,
        help_text="Upload your profile picture",
        transformation={
            "width": 300,
            "height": 300,
            "crop": "fill",
            "quality": "auto:good",
        },
    )
    start_date = models.DateTimeField(default=timezone.now)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_vendor = models.BooleanField(default=False)

    objects = CustomAccountManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["user_name", "first_name", "last_name"]

    def __str__(self):
        return self.user_name


class EmailVerification(models.Model):
    """Store temporary verification codes for signup email verification and password resets.

    For signup: Payload holds the pending user data (user_name, first_name, last_name and
    a hashed password) until the code is verified and the user is created.

    For password reset: Payload can be empty or hold additional context.
    """

    VERIFICATION_TYPES = (
        ("signup", "Signup Verification"),
        ("password_reset", "Password Reset"),
    )

    email = models.EmailField()
    code = models.CharField(max_length=6)
    verification_type = models.CharField(
        max_length=20, choices=VERIFICATION_TYPES, default="signup"
    )
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        # Allow multiple verification records per email (for different types)
        unique_together = [["email", "verification_type", "is_used"]]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def mark_used(self):
        self.is_used = True
        self.save()


class VendorPlan(models.Model):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    PREMIUM = "premium"
    EXTERNAL = "external"

    PLAN_CHOICES = [
        (FREE, "Free"),
        (BASIC, "Basic"),
        (PRO, "Pro"),
        (PREMIUM, "Premium"),
        (EXTERNAL, "External"),
    ]

    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    description = models.TextField(blank=True)
    price = models.IntegerField(help_text="Monthly price in NGN")
    max_products = models.IntegerField(
        null=True, blank=True, help_text="Max number of products allowed"
    )
    features = models.TextField(
        blank=True, help_text="List of plan features (one per line)"
    )
    paystack_plan_code = models.CharField(
        max_length=100, blank=True, help_text="Paystack plan code if integrated"
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return dict(self.PLAN_CHOICES).get(self.name, self.name)


class VendorProfile(models.Model):
    user = models.OneToOneField(
        UserProfile, on_delete=models.CASCADE, related_name="vendor_profile"
    )
    store_name = models.CharField(max_length=150)
    store_logo = CloudinaryField(
        "image",
        folder="store_logos",
        blank=True,
        null=True,
        transformation={
            "width": 400,
            "height": 400,
            "crop": "fill",
            "quality": "auto:good",
        },
    )
    store_description = models.TextField()
    phone_number = PhoneNumberField(unique=True, null=True, blank=True, region="NG")
    subaccount_code = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )
    paystack_subscription_code = models.CharField(max_length=100, blank=True, null=True)
    subscription_token = models.CharField(max_length=255, blank=True, null=True)
    pending_ref = models.CharField(max_length=50, blank=True, null=True)
    whatsapp_number = PhoneNumberField(unique=True, null=True, blank=True, region="NG")
    account_number = models.CharField(max_length=20, null=True, blank=True)
    bank_code = models.CharField(max_length=10, null=True, blank=True)
    instagram_handle = models.CharField(max_length=50, blank=True)
    tiktok_handle = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)
    plan = models.ForeignKey(VendorPlan, on_delete=models.SET_NULL, null=True)
    subscription_start = models.DateTimeField(auto_now_add=True)
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    subscription_status = models.CharField(
        max_length=50,
        choices=(
            ("trial", "Trial Period"),
            ("active", "Active"),
            ("grace", "Grace Period"),
            ("paused", "Paused"),
            ("defaulted", "Payment Failed"),
            ("cancelled", "Cancelled"),
            ("expired", "Expired"),
        ),
        default="trial",
    )
    last_payment_date = models.DateTimeField(null=True, blank=True)
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    pause_reason = models.CharField(max_length=255, blank=True, null=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    failed_payment_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.store_name} (Vendor: {self.user.user_name})"

    def has_active_trial(self):
        """Return True when the vendor is inside a valid trial window."""
        if not self.trial_end:
            return self.subscription_status == "trial"

        now = timezone.now()
        if self.trial_start and now < self.trial_start:
            return False

        return now <= self.trial_end

    def get_effective_subscription_status(self):
        """Get the access status after reconciling trial and paid subscription fields."""
        if self.subscription_status == "cancelled":
            return "cancelled"

        if self.has_active_trial():
            return "trial"

        if self.subscription_status == "paused":
            return "paused"

        if self.subscription_expiry:
            now = timezone.now()
            if self.subscription_status in ["active", "grace"]:
                if now <= self.subscription_expiry:
                    return "active"
                if now <= self.subscription_expiry + timedelta(days=7):
                    return "grace"
                return "expired"

        return self.subscription_status

    def get_effective_subscription_expiry(self):
        """Return the date currently controlling vendor access."""
        if self.has_active_trial():
            return self.trial_end
        return self.subscription_expiry

    def is_subscription_active(self):
        """Check if subscription provides active access"""
        if self.subscription_status == "cancelled":
            return False

        if self.has_active_trial():
            return True

        if self.subscription_status == "paused":
            return True  # Paused subscriptions maintain access

        if not self.subscription_expiry:
            return self.subscription_status == "active"

        now = timezone.now()
        # Active period or grace period (7 days after expiry)
        return self.subscription_status in ["active", "grace"] and (
            now <= self.subscription_expiry
            or now <= self.subscription_expiry + timedelta(days=7)
        )

    def get_subscription_days_remaining(self):
        """Get days remaining in subscription"""
        expiry = self.get_effective_subscription_expiry()
        if expiry:
            return max(0, (expiry - timezone.now()).days)
        return 0

    def is_in_grace_period(self):
        """Check if subscription is in grace period"""
        if self.has_active_trial():
            return False

        if not self.subscription_expiry:
            return False
        now = timezone.now()
        return (
            now > self.subscription_expiry
            and now <= self.subscription_expiry + timedelta(days=7)
        )

    def start_trial(self, days=14):
        """Start a trial period for the vendor"""
        self.subscription_status = "trial"
        self.trial_start = timezone.now()
        self.trial_end = timezone.now() + timedelta(days=days)
        self.save()

        # Log the event (import will be available after model definition)
        SubscriptionHistory.log_event(
            vendor=self,
            event_type="trial_started",
            notes=f"Started {days}-day trial period",
        )

    def pause_subscription(self, reason=""):
        """Pause the subscription"""
        if self.subscription_status not in ["active", "grace"]:
            return False

        old_status = self.subscription_status
        self.subscription_status = "paused"
        self.pause_reason = reason
        self.paused_at = timezone.now()
        self.save()

        # Log the event
        SubscriptionHistory.log_event(
            vendor=self,
            event_type="subscription_paused",
            previous_status=old_status,
            new_status="paused",
            notes=reason,
        )
        return True

    def resume_subscription(self):
        """Resume a paused subscription"""
        if self.subscription_status != "paused":
            return False

        self.subscription_status = "active"
        self.pause_reason = ""
        self.paused_at = None
        self.save()

        # Log the event
        SubscriptionHistory.log_event(
            vendor=self,
            event_type="subscription_resumed",
            previous_status="paused",
            new_status="active",
        )
        return True

    def change_plan_with_payment(self, new_plan, immediate=False, request=None):
        from .services import change_plan_with_payment as _svc
        return _svc(self, new_plan, immediate=immediate, request=request)

    def _update_paystack_subscription(self, new_plan):
        from .services import update_paystack_subscription as _svc
        return _svc(self, new_plan)

    def extend_subscription(self, days=30):
        """Extend subscription by specified days"""
        if self.subscription_expiry:
            # If subscription is still active, extend from expiry date
            if timezone.now() <= self.subscription_expiry:
                self.subscription_expiry += timedelta(days=days)
            else:
                # If expired, extend from now
                self.subscription_expiry = timezone.now() + timedelta(days=days)
        else:
            # No expiry set, create one
            self.subscription_expiry = timezone.now() + timedelta(days=days)

        self.subscription_status = "active"
        self.last_payment_date = timezone.now()
        self.failed_payment_count = 0  # Reset failed payment count
        self.save()

        # Log the event
        SubscriptionHistory.log_event(
            vendor=self,
            event_type="subscription_renewed",
            notes=f"Subscription extended by {days} days",
        )


class SubscriptionHistory(models.Model):
    """Track all subscription-related events and changes"""

    EVENT_TYPES = (
        ("subscription_created", "Subscription Created"),
        ("plan_upgraded", "Plan Upgraded"),
        ("plan_downgraded", "Plan Downgraded"),
        ("payment_success", "Payment Successful"),
        ("payment_failed", "Payment Failed"),
        ("subscription_renewed", "Subscription Renewed"),
        ("subscription_paused", "Subscription Paused"),
        ("subscription_resumed", "Subscription Resumed"),
        ("subscription_cancelled", "Subscription Cancelled"),
        ("trial_started", "Trial Started"),
        ("trial_ended", "Trial Ended"),
        ("grace_period_started", "Grace Period Started"),
        ("subscription_expired", "Subscription Expired"),
    )

    vendor = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="subscription_history"
    )
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    previous_plan = models.ForeignKey(
        VendorPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="previous_subscriptions",
    )
    new_plan = models.ForeignKey(
        VendorPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="new_subscriptions",
    )
    previous_status = models.CharField(max_length=50, blank=True)
    new_status = models.CharField(max_length=50, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    paystack_response = models.JSONField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Subscription History"

    def __str__(self):
        return f"{self.vendor.store_name} - {self.event_type} at {self.created_at}"

    @classmethod
    def log_event(cls, vendor, event_type, **kwargs):
        """Helper method to log subscription events"""
        return cls.objects.create(vendor=vendor, event_type=event_type, **kwargs)
