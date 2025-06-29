# permissions.py

from rest_framework.permissions import BasePermission
from datetime import timedelta
from django.utils import timezone

class HasActiveSubscription(BasePermission):

    def has_permission(self, request, view):
        user = request.user

        # Ensure user is a vendor
        if not hasattr(user, 'vendor_profile'):
            return False

        vendor = user.vendor_profile
        expiry = vendor.subscription_expiry

        if not expiry:
            return False

        now = timezone.now()

        # Check if within active period or grace period
        return expiry >= now or expiry + timedelta(days=7) >= now
    

def can_create_product(user):
    
    if not hasattr(user, 'vendor_profile'):
        return False

    vendor = user.vendor_profile
    plan = vendor.plan

    if not plan or not vendor.is_subscription_active():
        return False

    if plan.max_products is None:
        return True

    current_count = vendor.product.exclude(status='deleted').count()
    return current_count < plan.max_products


class VendorFeatureAccess(BasePermission):
    def has_permission(self, request, view):
        vendor = getattr(request.user, 'vendor_profile', None)
        if not vendor or not vendor.is_verified:
            return False
        return vendor.is_subscription_active()