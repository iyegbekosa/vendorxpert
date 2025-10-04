#!/usr/bin/env python
import os
import django
import requests
import json

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorPlan


def test_vendor_plans_endpoint():
    """Test the vendor plans listing endpoint"""
    print("=== Testing Vendor Plans Endpoint ===")

    # This would be the actual endpoint URL in production
    base_url = "http://127.0.0.1:8000"  # Django dev server URL
    endpoint = f"{base_url}/userprofile/api/vendor-plans/"

    print(f"Available plans in database:")
    plans = VendorPlan.objects.filter(is_active=True).order_by("price")
    for plan in plans:
        print(f"  - {plan.name}: ₦{plan.price}/month, {plan.max_products} products")

    print(f"\nEndpoint would be available at: {endpoint}")
    print("Expected response format:")
    print(
        json.dumps(
            [
                {
                    "id": plan.id,
                    "name": plan.name,
                    "price": float(plan.price),
                    "max_products": plan.max_products,
                    "is_active": plan.is_active,
                }
                for plan in plans
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    test_vendor_plans_endpoint()
