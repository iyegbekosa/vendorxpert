#!/usr/bin/env python
"""
Debug PhoneNumberField and Serializer integration
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.models import VendorProfile
from userprofile.serializers import VendorUpdateSerializer
from phonenumber_field.phonenumber import PhoneNumber

def test_serializer_validation():
    """Test the exact serializer scenario"""
    print("🔍 Testing VendorUpdateSerializer with existing vendor")
    print("=" * 60)
    
    # Get existing vendor
    vendor = VendorProfile.objects.first()
    if not vendor:
        print("❌ No vendor found")
        return
        
    print(f"📊 Testing with vendor: {vendor.store_name} (ID: {vendor.id})")
    print(f"📱 Current WhatsApp: {vendor.whatsapp_number}")
    
    # Test data - using the same number that already exists
    test_data = {
        'whatsapp_number': '09025144369'  # This might already be their number
    }
    
    print(f"📝 Test data: {test_data}")
    
    # Create serializer instance
    serializer = VendorUpdateSerializer(vendor, data=test_data, partial=True)
    
    print("🔍 Running serializer validation...")
    
    if serializer.is_valid():
        print("✅ Serializer validation PASSED!")
        validated_whatsapp = serializer.validated_data.get('whatsapp_number')
        print(f"📱 Validated WhatsApp: {validated_whatsapp}")
        print(f"📱 Type: {type(validated_whatsapp)}")
        
        # Try to save
        print("💾 Attempting to save...")
        try:
            updated_vendor = serializer.save()
            print(f"✅ Save successful! New WhatsApp: {updated_vendor.whatsapp_number}")
        except Exception as e:
            print(f"❌ Save failed: {e}")
            
    else:
        print("❌ Serializer validation FAILED!")
        print(f"🚨 Errors: {serializer.errors}")
        
        # Detailed error analysis
        for field, errors in serializer.errors.items():
            print(f"   {field}: {errors}")

def test_phone_number_field():
    """Test direct PhoneNumber field behavior"""
    print("\n🔍 Testing PhoneNumberField behavior")
    print("=" * 50)
    
    # Test different ways to create PhoneNumber
    test_cases = [
        "09025144369",
        "+2349025144369", 
        PhoneNumber.from_string("09025144369", region="NG"),
        PhoneNumber.from_string("+2349025144369", region="NG"),
    ]
    
    for i, case in enumerate(test_cases):
        print(f"\n🧪 Test {i+1}: {type(case).__name__} = {case}")
        
        try:
            # Try to create PhoneNumber object
            if isinstance(case, str):
                phone_obj = PhoneNumber.from_string(case, region="NG")
            else:
                phone_obj = case
                
            print(f"✅ PhoneNumber created: {phone_obj}")
            print(f"   Is valid: {phone_obj.is_valid()}")
            print(f"   Formatted: {phone_obj.as_e164}")
            
            # Test field validation
            vendor = VendorProfile.objects.first()
            if vendor:
                old_whatsapp = vendor.whatsapp_number
                vendor.whatsapp_number = phone_obj
                try:
                    vendor.full_clean()  # This runs field validation
                    print(f"✅ Field validation passed")
                except Exception as e:
                    print(f"❌ Field validation failed: {e}")
                finally:
                    vendor.whatsapp_number = old_whatsapp  # Restore
                    
        except Exception as e:
            print(f"❌ Failed to create PhoneNumber: {e}")

if __name__ == "__main__":
    test_phone_number_field()
    test_serializer_validation()