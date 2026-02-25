#!/usr/bin/env python
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorPlan

print("=== UPDATING VENDOR PLANS TO NEW PRICING ===")

# Update basic plan to ₦3000
try:
    basic_plan = VendorPlan.objects.get(name="basic")
    basic_plan.max_products = 10  # Increased from 6
    basic_plan.price = 3000  # ₦3000/month (increased from ₦2500)
    basic_plan.save()
    print("✓ Updated basic plan: ₦3000/month, max_products = 10")
except VendorPlan.DoesNotExist:
    print("✗ Basic plan not found")

# Create/Update Pro plan to ₦5000
pro_plan, created = VendorPlan.objects.get_or_create(
    name="pro",
    defaults={
        "price": 5000,  # ₦5000/month (increased from ₦3500)
        "max_products": 20,  # Increased from 15
        "paystack_plan_code": "",  # You'll need to set this after creating the plan in Paystack
    },
)
if created:
    print("✓ Created Pro plan: ₦5000/month, max_products = 20")
else:
    # Update existing pro plan price
    pro_plan.price = 5000
    pro_plan.max_products = 20
    pro_plan.save()
    print("✓ Updated Pro plan: ₦5000/month, max_products = 20")

# Create/Update Premium plan to ₦10000 with 25 products max
premium_plan, created = VendorPlan.objects.get_or_create(
    name="premium",
    defaults={
        "price": 10000,  # ₦10000/month (increased from ₦5000)
        "max_products": 25,  # Reduced from 50 to 25
        "paystack_plan_code": "",  # You'll need to set this after creating the plan in Paystack
    },
)
if created:
    print("✓ Created Premium plan: ₦10000/month, max_products = 25")
else:
    # Update existing premium plan price
    premium_plan.price = 10000
    premium_plan.max_products = 25
    premium_plan.save()
    print("✓ Updated Premium plan: ₦10000/month, max_products = 25")

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
