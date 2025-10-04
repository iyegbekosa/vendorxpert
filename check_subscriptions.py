#!/usr/bin/env python
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorPlan

print("=== UPDATING VENDOR PLANS ===")

# Update basic plan
try:
    basic_plan = VendorPlan.objects.get(name="basic")
    basic_plan.max_products = 6
    basic_plan.price = 2500  # ₦2500/month
    basic_plan.save()
    print("✓ Updated basic plan: ₦2500/month, max_products = 6")
except VendorPlan.DoesNotExist:
    print("✗ Basic plan not found")

# Create/Update Pro plan
pro_plan, created = VendorPlan.objects.get_or_create(
    name="pro",
    defaults={
        "price": 3500,  # ₦3500/month
        "max_products": 15,
        "paystack_plan_code": "",  # You'll need to set this after creating the plan in Paystack
    },
)
if created:
    print("✓ Created Pro plan: ₦3500/month, max_products = 15")
else:
    # Update existing pro plan price
    pro_plan.price = 3500
    pro_plan.save()
    print("✓ Updated Pro plan: ₦3500/month, max_products = 15")

# Create/Update Premium plan
premium_plan, created = VendorPlan.objects.get_or_create(
    name="premium",
    defaults={
        "price": 5000,  # ₦5000/month
        "max_products": 50,
        "paystack_plan_code": "",  # You'll need to set this after creating the plan in Paystack
    },
)
if created:
    print("✓ Created Premium plan: ₦5000/month, max_products = 50")
else:
    # Update existing premium plan price
    premium_plan.price = 5000
    premium_plan.save()
    print("✓ Updated Premium plan: ₦5000/month, max_products = 50")

print("\n=== CURRENT VENDOR PLANS ===")
plans = VendorPlan.objects.all().order_by("price")
print(f"Total plans: {plans.count()}")

for plan in plans:
    print(f"\nPlan ID: {plan.id}")
    print(f"  Name: {plan.name}")
    print(f"  Price: ₦{plan.price}/month")
    print(f"  Max Products: {plan.max_products}")
    print(f"  Paystack Plan Code: {plan.paystack_plan_code}")

print("\n✓ Plan setup complete!")
