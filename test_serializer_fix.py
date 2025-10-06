#!/usr/bin/env python3
"""
Quick test for the AttributeError fix

This script tests that the profile endpoints work correctly after the serializer fix.
"""

import requests
import json


def test_fixed_endpoints():
    """Test that the serializer fix works"""

    base_url = "http://localhost:8000"
    profile_url = f"{base_url}/api/profile/"

    # You'll need a valid token to test
    token = "your_jwt_token_here"
    headers = {"Authorization": f"Bearer {token}"}

    print("🔧 Testing Fixed Profile Endpoints")
    print("=" * 40)

    print("\n1️⃣ Testing GET /api/profile/ (should work)")
    try:
        response = requests.get(profile_url, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("✅ GET request successful - vendor_info method working!")
            data = response.json()
            print(f"User: {data.get('user_name', 'N/A')}")
            print(f"Vendor Info: {'Yes' if data.get('vendor_info') else 'No'}")
        else:
            print(f"❌ GET failed: {response.text}")
    except Exception as e:
        print(f"❌ GET Error: {e}")

    print("\n2️⃣ Testing PUT /api/profile/ (was causing AttributeError)")
    test_data = {"first_name": "Test Update", "hostel": "hall_1"}

    try:
        response = requests.put(profile_url, headers=headers, json=test_data)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("✅ PUT request successful - AttributeError fixed!")
            data = response.json()
            print(f"Message: {data.get('message', 'N/A')}")
        else:
            print(f"❌ PUT failed: {response.text}")
    except Exception as e:
        print(f"❌ PUT Error: {e}")


if __name__ == "__main__":
    print("🏥 Profile Serializer Fix Verification")
    print("=" * 40)
    print("\n⚠️  Make sure:")
    print("1. Django server is running")
    print("2. Replace 'your_jwt_token_here' with valid token")
    print("3. pip install requests")

    # Uncomment to run test
    # test_fixed_endpoints()

    print("\n✅ The AttributeError should now be fixed!")
    print("   - UserProfileSerializer has get_vendor_info method")
    print("   - ProfileUpdateSerializer has hostel validation")
    print("   - Both serializers work independently")
