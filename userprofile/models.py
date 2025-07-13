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

    email = models.EmailField(_("email address"), unique=True)
    user_name = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    start_date = models.DateTimeField(default=timezone.now)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_vendor = models.BooleanField(default=False)

    objects = CustomAccountManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["user_name", "first_name", "last_name"]

    def __str__(self):
        return self.user_name


class VendorPlan(models.Model):
    BASIC = "basic"
    PREMIUM = "premium"
    EXTERNAL = "external"

    PLAN_CHOICES = [
        (BASIC, "Basic"),
        (PREMIUM, "Premium"),
        (EXTERNAL, "External"),
    ]

    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    description = models.TextField(blank=True)
    price = models.IntegerField(help_text="Monthly price in NGN")
    max_products = models.IntegerField(
        null=True, blank=True, help_text="Max number of products allowed"
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
    store_logo = models.ImageField(upload_to="store_logo", blank=True, null=True)
    store_description = models.TextField()
    phone_number = PhoneNumberField(unique=True, null=True, blank=True)
    subaccount_code = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )
    paystack_subscription_code = models.CharField(max_length=100, blank=True, null=True)
    paystack_subscription_code = models.CharField(max_length=100, blank=True, null=True)
    subscription_token = models.CharField(max_length=255, blank=True, null=True)
    pending_ref = models.CharField(max_length=50, blank=True, null=True)
    whatsapp_number = PhoneNumberField(unique=True, null=True, blank=True)
    instagram_handle = models.CharField(max_length=50, blank=True)
    tiktok_handle = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)
    plan = models.ForeignKey(VendorPlan, on_delete=models.SET_NULL, null=True)
    subscription_start = models.DateTimeField(auto_now_add=True)
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    subscription_status = models.CharField(
        max_length=50,
        choices=(
            ("active", "Active"),
            ("grace", "Grace Period"),
            ("defaulted", "Defaulted"),
            ("cancelled", "Cancelled"),
        ),
        default="active",
    )
    last_payment_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.store_name} (Vendor: {self.user.user_name})"

    def is_subscription_active(self):
        if not self.subscription_expiry:
            return False
        return timezone.now() <= self.subscription_expiry + timedelta(days=7)
