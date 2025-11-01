# permissions.py

from rest_framework.permissions import BasePermission
from datetime import timedelta
from django.utils import timezone


class HasActiveSubscription(BasePermission):

    def has_permission(self, request, view):
        user = request.user

        # Ensure user is a vendor
        if not hasattr(user, "vendor_profile"):
            return False

        vendor = user.vendor_profile

        # Use the vendor's own subscription check method which handles all cases
        # including trial periods, active subscriptions, and grace periods
        return vendor.is_subscription_active()


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
    def has_permission(self, request, view):
        vendor = getattr(request.user, "vendor_profile", None)
        if not vendor:
            return False

        # For trial periods, allow access without verification requirement
        if vendor.subscription_status == "trial":
            return vendor.is_subscription_active()

        # For paid subscriptions, require verification
        if not vendor.is_verified:
            return False
        return vendor.is_subscription_active()
