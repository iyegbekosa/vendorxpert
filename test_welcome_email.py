#!/usr/bin/env python
"""
Test the welcome email functionality by creating a test user
"""
import os
import sys
import django
import requests
import json
from pathlib import Path

# Add the project directory to Python path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from django.conf import settings


def test_user_signup_with_welcome_email():
    """Test user signup via API and welcome email sending"""

    # API endpoint
    signup_url = "http://127.0.0.1:8000/userprofile/api/signup/"

    # Test user data
    test_user_data = {
        "user_name": "testuser_welcome",
        "email": "egyadesm@gmail.com",  # Using the same email we tested earlier
        "first_name": "Test",
        "last_name": "User",
        "password": "testpass123",
        "password2": "testpass123",
    }

    print("🧪 Testing User Signup with Welcome Email")
    print("=" * 50)
    print(f"📡 API Endpoint: {signup_url}")
    print(f"👤 Test User: {test_user_data['first_name']} {test_user_data['last_name']}")
    print(f"📧 Email: {test_user_data['email']}")
    print("-" * 50)

    try:
        # Send POST request to signup API
        print("📤 Sending signup request...")
        response = requests.post(signup_url, json=test_user_data)

        print(f"📥 Response Status: {response.status_code}")

        if response.status_code == 201:
            response_data = response.json()
            print("✅ User signup successful!")
            print(f"📋 Response: {json.dumps(response_data, indent=2)}")

            if "Welcome email sent" in response_data.get("message", ""):
                print("✅ Welcome email functionality is working!")
            else:
                print("⚠️ Welcome email might not have been sent")

        else:
            print("❌ User signup failed!")
            try:
                error_data = response.json()
                print(f"❌ Error: {json.dumps(error_data, indent=2)}")
            except:
                print(f"❌ Error: {response.text}")

    except requests.exceptions.ConnectionError:
        print(
            "❌ Connection Error: Make sure Django server is running on http://127.0.0.1:8000"
        )
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")


def test_direct_email_function():
    """Test the email function directly"""
    print("\n🧪 Testing Welcome Email Function Directly")
    print("=" * 50)

    from userprofile.models import UserProfile
    from userprofile.email_utils import send_welcome_email

    # Create a test user directly
    try:
        # Check if test user already exists
        test_email = "egyadesm@gmail.com"
        try:
            test_user = UserProfile.objects.get(email=test_email)
            print(f"📧 Found existing test user: {test_user.user_name}")
        except UserProfile.DoesNotExist:
            print("👤 Creating test user...")
            test_user = UserProfile.objects.create_user(
                email=test_email,
                user_name="direct_test_user",
                first_name="Direct",
                last_name="Test",
                password="testpass123",
            )
            print(f"✅ Test user created: {test_user.user_name}")

        # Send welcome email
        print("📧 Sending welcome email directly...")
        result = send_welcome_email(test_user)

        if result:
            print("✅ Welcome email sent successfully!")
        else:
            print("❌ Failed to send welcome email")

    except Exception as e:
        print(f"❌ Error in direct test: {str(e)}")


if __name__ == "__main__":
    print("🚀 VendorXpert Welcome Email Testing")
    print("=" * 60)

    # Test direct email function first
    test_direct_email_function()

    # Test API signup
    print("\n" + "=" * 60)
    test_user_signup_with_welcome_email()

    print("\n" + "=" * 60)
    print("🎯 Test completed!")
    print("📧 Check egyadesm@gmail.com inbox for welcome emails")
