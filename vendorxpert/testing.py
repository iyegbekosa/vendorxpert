"""Factories shared by the backend test suites."""

import hashlib
import hmac
import itertools
import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.utils import timezone

_counter = itertools.count(1)


def make_user(email=None, username=None, password="Str0ng-pass-123", **extra):
    from userprofile.models import UserProfile

    n = next(_counter)
    return UserProfile.objects.create_user(
        email=email or f"user{n}@example.com",
        user_name=username or f"user{n}",
        first_name="Ada",
        last_name="Obi",
        password=password,
        **extra,
    )


def make_plan(name="basic", price=3000, max_products=6, code=None):
    from userprofile.models import VendorPlan

    return VendorPlan.objects.create(
        name=name,
        price=price,
        max_products=max_products,
        is_active=True,
        paystack_plan_code=code if code is not None else f"PLN_{name}",
    )


def make_vendor(user=None, plan=None, status="trial", **extra):
    from userprofile.models import VendorProfile

    user = user or make_user()
    now = timezone.now()
    defaults = {
        "store_name": f"{user.user_name} store",
        "store_description": "Good things",
        "plan": plan,
        "subscription_status": status,
        "subaccount_code": f"ACCT_{user.pk}",
    }
    if status == "trial":
        defaults.update(trial_start=now - timedelta(days=1), trial_end=now + timedelta(days=29))
    elif status == "active":
        defaults.update(subscription_expiry=now + timedelta(days=20))
    defaults.update(extra)
    user.is_vendor = True
    user.save(update_fields=["is_vendor"])
    return VendorProfile.objects.create(user=user, **defaults)


def make_category(slug="gadgets"):
    from store.models import Category

    return Category.objects.get_or_create(slug=slug, defaults={"title": slug.title()})[0]


def make_product(vendor, category=None, title="Power bank", price=1500, quantity=5, **extra):
    """Create a Product without touching Cloudinary (full_clean is bypassed)."""
    from store.models import Product

    product = Product(
        vendor=vendor,
        category=category or make_category(),
        title=title,
        description="Works well",
        price=price,
        quantity=quantity,
        product_image="test/image.jpg",
        **extra,
    )
    with patch.object(Product, "full_clean"):
        product.save()
    return product


def signed_webhook(client, payload, path="/api/paystack_webhook/"):
    body = json.dumps(payload).encode()
    signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512
    ).hexdigest()
    return client.post(
        path, data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature
    )
