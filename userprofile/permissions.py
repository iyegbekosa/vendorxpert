from rest_framework.permissions import BasePermission

from .models import VendorProfile


def get_vendor(user):
    try:
        return user.vendor_profile
    except (AttributeError, VendorProfile.DoesNotExist):
        return None


class IsVendor(BasePermission):
    """The user has a vendor profile.

    Used for everything a vendor must always be able to do — view orders,
    fulfil paid orders, manage their store and billing — even when their
    subscription has lapsed, so buyers who already paid are never stranded.
    """

    message = "This is only available to vendors."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and get_vendor(request.user))


class CanSell(IsVendor):
    """The vendor's trial or subscription currently allows selling."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        vendor = get_vendor(request.user)
        if vendor.has_selling_access():
            return True
        if vendor.is_suspended:
            self.message = (
                "Your store is suspended"
                + (f": {vendor.suspension_reason}" if vendor.suspension_reason else "")
                + ". Contact support to resolve it."
            )
        elif vendor.subscription_status == "trial":
            self.message = "Your free trial has ended. Choose a plan to keep selling."
        else:
            self.message = "Your subscription has expired. Renew it to keep selling."
        return False


def can_create_product(vendor):
    """Whether the vendor's plan allows one more listing."""
    if not vendor.has_selling_access():
        return False
    plan = vendor.plan
    if plan is None or plan.max_products is None:
        return True
    return vendor.product.exclude(status="deleted").count() < plan.max_products
