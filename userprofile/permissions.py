# permissions.py

from rest_framework.permissions import BasePermission
from datetime import timedelta
from django.utils import timezone


class HasActiveSubscription(BasePermission):
    message = "Vendor subscription is not active."

    def has_permission(self, request, view):
        user = request.user

        # Ensure user is a vendor
        if not hasattr(user, "vendor_profile"):
            self.message = "User is not registered as a vendor."
            return False

        vendor = user.vendor_profile

        # Use the vendor's own subscription check method which handles all cases
        # including trial periods, active subscriptions, and grace periods
        if vendor.is_subscription_active():
            return True

        if vendor.subscription_status == "trial":
            self.message = "Vendor trial has expired. Please subscribe to continue."
            return False

        if vendor.subscription_expiry:
            self.message = "Vendor subscription has expired. Please renew to continue."

        return False


def can_create_product(user):

    if not hasattr(user, "vendor_profile"):
        return False

    vendor = user.vendor_profile
    plan = vendor.plan

    # Check if vendor has active subscription (includes trial periods)
    if not vendor.is_subscription_active():
        return False

    # If no plan is set, allow creation (shouldn't happen but safe fallback)
    if not plan:
        return True

    # If plan has unlimited products, allow creation
    if plan.max_products is None:
        return True

    # Check if vendor is within their product limit
    current_count = vendor.product.exclude(status="deleted").count()
    return current_count < plan.max_products


class VendorFeatureAccess(BasePermission):
    message = "Vendor feature access denied."

    def has_permission(self, request, view):
        vendor = getattr(request.user, "vendor_profile", None)
        if not vendor:
            self.message = "User is not registered as a vendor."
            return False

        # Active trials are allowed even before paid-subscription verification.
        if vendor.has_active_trial():
            return True

        # For paid subscriptions, require verification
        if not vendor.is_verified:
            self.message = "Vendor account is not verified."
            return False

        if vendor.is_subscription_active():
            return True

        if vendor.subscription_status == "trial":
            self.message = "Vendor trial has expired. Please subscribe to continue."
        elif vendor.subscription_expiry:
            self.message = "Vendor subscription has expired. Please renew to continue."
        else:
            self.message = "Vendor subscription is not active."

        return False
