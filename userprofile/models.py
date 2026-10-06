import logging
from datetime import timedelta

from cloudinary.models import CloudinaryField
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

logger = logging.getLogger(__name__)



def grace_days():
    """Days a lapsed paid vendor keeps selling (admin-managed setting)."""
    from operations.config import get_settings

    return get_settings().grace_days


def normalize_email_address(email):
    """Emails are case-insensitive for identity purposes; store them lowercased."""
    return (email or "").strip().lower()


class CustomAccountManager(BaseUserManager):
    def create_user(
        self, email, user_name, first_name, last_name, password, **other_fields
    ):

        if not email:
            raise ValueError(_("You must provide a valid email address"))

        email = normalize_email_address(email)
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

    def get_by_natural_key(self, username):
        """Case-insensitive login lookup.

        Older accounts may have been stored with mixed-case emails, so try an
        exact match first and only then fall back to a case-insensitive one.
        """
        try:
            return self.get(email=username)
        except self.model.DoesNotExist:
            try:
                return self.get(email__iexact=normalize_email_address(username))
            except self.model.MultipleObjectsReturned:
                raise self.model.DoesNotExist


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

    class Meta:
        permissions = [("suspend_user", "Can suspend or restore user accounts")]
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

    MAX_ATTEMPTS = 5

    email = models.EmailField()
    code = models.CharField(max_length=6)
    # Failed code submissions. The code is invalidated after MAX_ATTEMPTS so a
    # 6-digit OTP cannot be brute-forced.
    attempts = models.PositiveSmallIntegerField(default=0)
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

    def is_locked(self):
        return self.attempts >= self.MAX_ATTEMPTS

    def mark_used(self):
        self.is_used = True
        self.save()


def selling_access_q(prefix=""):
    """Database filter equivalent of ``VendorProfile.has_selling_access``.

    ``prefix`` lets callers apply it across relations, e.g. ``"vendor__"`` when
    filtering products. Keep both implementations in sync (covered by tests).
    """
    now = timezone.now()

    def field(name):
        return f"{prefix}{name}"

    in_trial = Q(**{field("subscription_status"): "trial"}) & (
        Q(**{f"{field('trial_end')}__isnull": True})
        | (
            Q(**{f"{field('trial_end')}__gte": now})
            & (
                Q(**{f"{field('trial_start')}__isnull": True})
                | Q(**{f"{field('trial_start')}__lte": now})
            )
        )
    )
    paid = Q(
        **{
            f"{field('subscription_status')}__in": ["active", "grace"],
            f"{field('subscription_expiry')}__gte": now - timedelta(days=grace_days()),
        }
    ) | Q(
        **{
            field("subscription_status"): "active",
            f"{field('subscription_expiry')}__isnull": True,
        }
    )
    cancelled_but_paid_up = Q(
        **{
            field("subscription_status"): "cancelled",
            f"{field('subscription_expiry')}__gte": now,
        }
    )
    paused = Q(**{field("subscription_status"): "paused"})
    not_suspended = Q(**{field("is_suspended"): False, field("user__is_active"): True})
    return not_suspended & (in_trial | paid | cancelled_but_paid_up | paused)


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
    # Paystack "email_token" for the current subscription; required to disable it.
    subscription_token = models.CharField(max_length=255, blank=True, null=True)
    # Reference of a subscription/plan-change payment the vendor has started
    # but which is not yet confirmed.
    pending_ref = models.CharField(max_length=50, blank=True, null=True)
    # Reusable card authorisation and customer from the last subscription
    # payment; needed to move the recurring billing to a different plan.
    paystack_customer_code = models.CharField(max_length=100, blank=True, default="")
    paystack_authorization_code = models.CharField(max_length=100, blank=True, default="")
    whatsapp_number = PhoneNumberField(unique=True, null=True, blank=True, region="NG")
    account_number = models.CharField(max_length=20, null=True, blank=True)
    bank_code = models.CharField(max_length=10, null=True, blank=True)
    instagram_handle = models.CharField(max_length=50, blank=True)
    tiktok_handle = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)
    # Staff-imposed suspension: listings are hidden and no new orders can be
    # placed, but the vendor can still log in and complete paid orders.
    is_suspended = models.BooleanField(default=False, db_index=True)
    suspension_reason = models.CharField(max_length=255, blank=True)
    plan = models.ForeignKey(VendorPlan, on_delete=models.SET_NULL, null=True)
    # Plan the vendor switches to at the next billing date (downgrades).
    scheduled_plan = models.ForeignKey(
        VendorPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scheduled_vendors",
    )
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

    class Meta:
        permissions = [("suspend_vendor", "Can suspend or restore vendor stores")]

    def __str__(self):
        return self.store_name

    def clean(self):
        from django.core.exceptions import ValidationError
        paid_statuses = {"active", "grace", "defaulted"}
        if self.subscription_status in paid_statuses:
            if not self.plan:
                raise ValidationError(
                    {"plan": f"A plan is required when subscription_status is '{self.subscription_status}'."}
                )
            if not self.subscription_expiry:
                raise ValidationError(
                    {"subscription_expiry": f"subscription_expiry must be set when subscription_status is '{self.subscription_status}'."}
                )

    def has_active_trial(self):
        """Return True when the vendor is inside a valid trial window."""
        if self.subscription_status != "trial":
            return False
        if not self.trial_end:
            return True

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
                if now <= self.subscription_expiry + timedelta(days=grace_days()):
                    return "grace"
                return "expired"

        if self.subscription_status == "trial":
            # Trial window has passed and no paid subscription replaced it.
            return "expired"

        return self.subscription_status

    def get_effective_subscription_expiry(self):
        """Return the date currently controlling vendor access."""
        if self.has_active_trial():
            return self.trial_end
        return self.subscription_expiry

    def has_selling_access(self):
        """Whether the vendor may list products and receive orders.

        Mirrors ``selling_access_q`` — keep the two in sync.
        """
        if self.is_suspended or not self.user.is_active:
            return False
        if self.has_active_trial():
            return True

        if self.subscription_status == "paused":
            return True  # Paused subscriptions maintain access

        now = timezone.now()
        if self.subscription_status == "cancelled":
            # Cancelling stops renewal; the vendor keeps what they paid for.
            return bool(self.subscription_expiry and now <= self.subscription_expiry)

        if not self.subscription_expiry:
            return self.subscription_status == "active"

        return self.subscription_status in ["active", "grace"] and (
            now <= self.subscription_expiry + timedelta(days=grace_days())
        )

    # Backwards-compatible name used throughout the codebase.
    is_subscription_active = has_selling_access

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
            and now <= self.subscription_expiry + timedelta(days=grace_days())
        )

    def start_trial(self, days=30):
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

    def paid_period_start(self):
        """When a newly paid 30-day period should start.

        Paying early never loses time: an unexpired trial or paid period is
        honoured and the new period starts when it ends.
        """
        now = timezone.now()
        candidates = [now]
        if self.has_active_trial() and self.trial_end:
            candidates.append(self.trial_end)
        if (
            self.subscription_status in ("active", "grace", "cancelled")
            and self.subscription_expiry
        ):
            candidates.append(self.subscription_expiry)
        return max(candidates)


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
