#!/usr/bin/env python
"""
Test phone number validation for Nigerian formats
"""
import os
import django
from pathlib import Path

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.serializers import VendorUpdateSerializer
from userprofile.models import VendorProfile


def test_phone_validation():
    """Test phone number validation with various formats"""
    print("🧪 Testing Phone Number Validation")
    print("=" * 60)

    # Test cases
    test_numbers = [
        # Format: (input, description, should_pass)
        ("09025144369", "Nigerian local format", True),
        ("+2349025144369", "International format", True),
        ("08012345678", "Another local format", True),
        ("+2348012345678", "Another international format", True),
        ("070123456789", "Invalid - too many digits", False),
        ("0902514436", "Invalid - too few digits", False),
        ("1234567890", "Invalid - doesn't start with 0 or +234", False),
        ("", "Empty string", True),  # Should be allowed (optional field)
        (None, "None value", True),  # Should be allowed (optional field)
    ]

    for phone_input, description, should_pass in test_numbers:
        print(f"\n🔍 Testing: {description}")
        print(f"   Input: '{phone_input}'")

        # Create a mock serializer instance
        serializer = VendorUpdateSerializer()

        try:
            if phone_input is not None:
                result = serializer.validate_whatsapp_number(phone_input)
                if should_pass:
                    print(f"   ✅ PASS: Converted to: {result}")
                else:
                    print(f"   ❌ FAIL: Should have been rejected but got: {result}")
            else:
                result = serializer.validate_whatsapp_number(phone_input)
                print(f"   ✅ PASS: None/empty handled correctly: {result}")

        except Exception as e:
            if should_pass:
                print(f"   ❌ FAIL: Should have passed but got error: {e}")
            else:
                print(f"   ✅ PASS: Correctly rejected with: {e}")

    print("\n" + "=" * 60)


def test_full_serializer():
    """Test full serializer with the user's data"""
    print("\n🧪 Testing Full Serializer with User Data")
    print("=" * 60)

    # User's actual data (using valid Nigerian mobile number)
    test_data = {
        "store_name": "Ayo-shopa",
        "store_description": "Welcome to Ayo-shopa! We offer quality products and excellent service. Thank you",
        "phone_number": "",
        "whatsapp_number": "09025144369",  # Valid Nigerian mobile number
        "instagram_handle": "",
        "tiktok_handle": "",
    }

    print(f"📝 Test data: {test_data}")

    # Create serializer with mock vendor
    try:
        # Get a vendor to test with
        vendor = VendorProfile.objects.first()
        if vendor:
            serializer = VendorUpdateSerializer(vendor, data=test_data, partial=True)

            if serializer.is_valid():
                print("✅ Serializer validation PASSED!")
                print(f"📋 Validated data: {serializer.validated_data}")
            else:
                print("❌ Serializer validation FAILED!")
                print(f"🚨 Errors: {serializer.errors}")
        else:
            print("⚠️  No vendor found for testing")

    except Exception as e:
        print(f"❌ Error during serializer test: {e}")


if __name__ == "__main__":
    test_phone_validation()
    test_full_serializer()
