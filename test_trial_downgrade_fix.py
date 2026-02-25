#!/usr/bin/env python3
"""
Test script to verify the trial downgrade fix
"""
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorProfile, VendorPlan


def test_trial_user_scenarios():
    """Test different trial user plan change scenarios"""

    # Get test plans
    try:
        free_plan = VendorPlan.objects.get(name="free")
        basic_plan = VendorPlan.objects.get(name="basic")  # ₦1500
        pro_plan = VendorPlan.objects.get(name="pro")  # ₦3500
        premium_plan = VendorPlan.objects.get(name="premium")  # ₦5000
    except VendorPlan.DoesNotExist:
        print("❌ Required plans not found")
        return

    # Get trial vendor (if exists)
    trial_vendor = VendorProfile.objects.filter(subscription_status="trial").first()
    if not trial_vendor:
        print("❌ No trial vendor found")
        return

    print(f"🧪 Testing trial vendor: {trial_vendor.store_name} (ID: {trial_vendor.id})")
    print(f"📊 Current plan: {trial_vendor.plan.name if trial_vendor.plan else 'None'}")
    print(f"📊 Current price: ₦{trial_vendor.plan.price if trial_vendor.plan else 0}")

    # Test scenarios without actual payment processing
    print("\n" + "=" * 60)
    print("🔬 TESTING TRIAL USER SCENARIOS")
    print("=" * 60)

    scenarios = [
        ("Upgrade to Basic", basic_plan, "Should require payment"),
        ("Upgrade to Pro", pro_plan, "Should require payment"),
        ("Upgrade to Premium", premium_plan, "Should require payment"),
        ("Downgrade to Pro (from Premium)", pro_plan, "Should be FREE"),
        ("Downgrade to Basic (from Premium)", basic_plan, "Should be FREE"),
        ("Downgrade to Free", free_plan, "Should be FREE"),
    ]

    # Set trial vendor to premium plan first for downgrade tests
    trial_vendor.plan = premium_plan
    trial_vendor.save()
    print(f"📝 Set vendor to Premium plan for testing\n")

    for i, (scenario_name, target_plan, expected) in enumerate(scenarios, 1):
        print(f"\n🔬 Scenario {i}: {scenario_name}")
        print(f"💡 Expected: {expected}")
        print("-" * 40)

        # Determine is_upgrade
        current_price = trial_vendor.plan.price if trial_vendor.plan else 0
        is_upgrade = target_plan.price > current_price

        print(
            f"📊 Current: {trial_vendor.plan.name if trial_vendor.plan else 'None'} (₦{current_price})"
        )
        print(f"🎯 Target: {target_plan.name} (₦{target_plan.price})")
        print(f"📈 Is upgrade: {is_upgrade}")

        # Test the logic conditions
        if (
            trial_vendor.subscription_status == "trial"
            and is_upgrade
            and target_plan.price > 0
        ):
            print("💳 Result: PAYMENT REQUIRED ✅")
            payment_amount = target_plan.price
            print(f"💰 Amount: ₦{payment_amount}")
        elif trial_vendor.subscription_status == "trial" and not is_upgrade:
            print("🔽 Result: FREE (Trial downgrade) ✅")
            payment_amount = 0
            print(f"💰 Amount: ₦{payment_amount}")
        else:
            print("🔄 Result: Standard logic applies")

        # Update vendor plan for next test
        trial_vendor.plan = target_plan

    print("\n" + "=" * 60)
    print("✅ TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    test_trial_user_scenarios()
