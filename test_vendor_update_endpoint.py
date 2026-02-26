#!/usr/bin/env python3
"""
Test script for the vendor store update endpoint
"""
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorProfile, UserProfile
from userprofile.serializers import VendorUpdateSerializer


def test_vendor_update_serializer():
    """Test the VendorUpdateSerializer functionality"""

    print("🧪 Testing VendorUpdateSerializer")
    print("=" * 50)

    # Get a vendor for testing
    vendor = VendorProfile.objects.first()
    if not vendor:
        print("❌ No vendor found for testing")
        return

    print(f"📊 Testing with vendor: {vendor.store_name} (ID: {vendor.id})")
    print(f"📧 User email: {vendor.user.email}")

    # Test data for updating - using Nigerian local format
    test_data = {
        "store_name": "Updated Test Store",
        "store_description": "This is an updated store description for testing",
        "phone_number": "09025144369",  # Nigerian local format - should convert to +234
        "whatsapp_number": "08123456789",  # Nigerian local format - should convert to +234
        "instagram_handle": "@updated_test_store",
        "tiktok_handle": "@updated_tiktok",
    }

    print(f"\\n🔧 Test update data:")
    for key, value in test_data.items():
        print(f"  - {key}: {value}")

    # Test serializer validation
    serializer = VendorUpdateSerializer(vendor, data=test_data, partial=True)

    if serializer.is_valid():
        print("\\n✅ Serializer validation passed!")
        print("📝 Validated data:")
        for key, value in serializer.validated_data.items():
            print(f"  - {key}: {value}")

        # Save the changes
        updated_vendor = serializer.save()
        print(f"\\n💾 Vendor updated successfully!")
        print(f"📊 New store name: {updated_vendor.store_name}")
        print(f"📄 New description: {updated_vendor.store_description}")

        # Test serializer output
        output_serializer = VendorUpdateSerializer(updated_vendor)
        print(f"\\n📤 Serializer output:")
        for key, value in output_serializer.data.items():
            print(f"  - {key}: {value}")

    else:
        print("\\n❌ Serializer validation failed!")
        print("🚨 Errors:")
        for field, errors in serializer.errors.items():
            print(f"  - {field}: {errors}")


def test_validation_errors():
    """Test validation error handling"""

    print("\\n\\n🧪 Testing Validation Errors")
    print("=" * 50)

    vendor = VendorProfile.objects.first()
    if not vendor:
        print("❌ No vendor found for testing")
        return

    # Test empty store name
    invalid_data = {
        "store_name": "   ",  # Empty/whitespace only
        "store_description": "x" * 501,  # Too long description
    }

    print("🚨 Testing invalid data:")
    for key, value in invalid_data.items():
        print(f"  - {key}: {repr(value)}")

    serializer = VendorUpdateSerializer(vendor, data=invalid_data, partial=True)

    if not serializer.is_valid():
        print("\\n✅ Validation correctly failed!")
        print("🚨 Expected errors:")
        for field, errors in serializer.errors.items():
            print(f"  - {field}: {errors}")
    else:
        print("\\n❌ Validation should have failed but didn't!")


def test_phone_number_formats():
    """Test different phone number formats"""
    print("\\n🧪 Testing Phone Number Format Validation")
    print("=" * 60)

    vendor = VendorProfile.objects.first()
    if not vendor:
        print("❌ No vendor found for testing")
        return

    formats_to_test = [
        {
            "phone": "09025144369",
            "whatsapp": "08123456789",
            "desc": "Nigerian local format (0)",
        },
        {
            "phone": "+2349025144369",
            "whatsapp": "+2348123456789",
            "desc": "International format (+234)",
        },
        {
            "phone": "0802 555 1234",
            "whatsapp": "0901-234-5678",
            "desc": "Local with spaces/dashes",
        },
    ]

    for i, test_case in enumerate(formats_to_test, 1):
        print(f"\\n🔬 Test Case {i}: {test_case['desc']}")
        print(f"📱 Phone: {test_case['phone']}")
        print(f"💬 WhatsApp: {test_case['whatsapp']}")

        test_data = {
            "phone_number": test_case["phone"],
            "whatsapp_number": test_case["whatsapp"],
        }

        serializer = VendorUpdateSerializer(vendor, data=test_data, partial=True)
        if serializer.is_valid():
            print("✅ Validation passed!")
            validated_phone = serializer.validated_data.get("phone_number")
            validated_whatsapp = serializer.validated_data.get("whatsapp_number")
            print(f"📱 Normalized Phone: {validated_phone}")
            print(f"💬 Normalized WhatsApp: {validated_whatsapp}")
        else:
            print(f"❌ Validation failed: {serializer.errors}")


def run_all_tests():
    """Run all tests"""
    print("🚀 VendorUpdateSerializer Testing")
    print("=" * 60)

    # Original test
    test_vendor_update_serializer()

    # Phone number format tests
    test_phone_number_formats()

    # Original validation test
    test_validation_errors()

    print("\\n🎉 All tests complete!")


if __name__ == "__main__":
    run_all_tests()
