#!/usr/bin/env python3
"""
Simple test for phone number validation in VendorUpdateSerializer
"""
import os
import sys
import django
from pathlib import Path

# Add project directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.serializers import VendorUpdateSerializer
from userprofile.models import VendorProfile


def test_phone_validation():
    """Test phone number validation with a real vendor"""
    print("🧪 Testing Phone Number Validation After Migration")
    print("=" * 60)

    # Get a vendor to test with
    vendor = VendorProfile.objects.first()
    if not vendor:
        print("❌ No vendor found in database")
        return False

    print(f"👤 Testing with vendor: {vendor.store_name} (ID: {vendor.id})")

    # Test data with Nigerian local format
    test_data = {
        "whatsapp_number": "09025144369",  # Should convert to +2349025144369
        "phone_number": "08012345678",  # Should convert to +2348012345678
    }

    print(f"📱 Test data: {test_data}")

    # Test validation
    serializer = VendorUpdateSerializer(vendor, data=test_data, partial=True)

    if serializer.is_valid():
        print("✅ Validation PASSED!")
        validated_data = serializer.validated_data
        print(f"📱 WhatsApp: {validated_data.get('whatsapp_number')}")
        print(f"📞 Phone: {validated_data.get('phone_number')}")
        return True
    else:
        print("❌ Validation FAILED!")
        print(f"🚨 Errors: {serializer.errors}")
        return False


if __name__ == "__main__":
    try:
        result = test_phone_validation()
        if result:
            print("\n🎉 Phone number validation is working correctly!")
        else:
            print("\n⚠️  Phone number validation needs fixing")
    except Exception as e:
        print(f"❌ Error during testing: {e}")
