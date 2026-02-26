#!/usr/bin/env python
"""
Test ZeptoMail HTTP API integration
"""
import os
import django
from pathlib import Path

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from userprofile.zeptomail_client import ZeptoMailClient, send_zeptomail
from userprofile.email_utils import send_welcome_email, send_verification_email
from userprofile.models import UserProfile
from django.conf import settings
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_zeptomail_client():
    """Test the basic ZeptoMail client"""
    print("🧪 Testing ZeptoMail Client Configuration")
    print("=" * 60)

    try:
        client = ZeptoMailClient()
        print(f"✅ ZeptoMail client initialized")
        print(f"📧 From Email: {client.from_email}")
        print(f"👤 From Name: {client.from_name}")
        print(
            f"🔑 API Key: {client.api_key[:20]}..."
            if client.api_key
            else "❌ No API Key"
        )

        return client
    except Exception as e:
        print(f"❌ Failed to initialize ZeptoMail client: {e}")
        return None


def test_simple_email():
    """Test sending a simple test email"""
    print("\n🧪 Testing Simple Email")
    print("=" * 60)

    client = ZeptoMailClient()

    # Test simple email
    success = client.send_email(
        to_email="egyadesmond@gmail.com",
        subject="🚀 ZeptoMail Test - VendorXprt",
        text_content="""
Hello!

This is a test email from VendorXprt using ZeptoMail HTTP API.

✅ If you're receiving this, the ZeptoMail integration is working!

Configuration:
- API: ZeptoMail HTTP REST API
- From: contact@vendorxprt.com
- Service: VendorXprt

Best regards,
VendorXprt Team
        """,
        html_content="""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #2c3e50;">🚀 ZeptoMail Test - VendorXprt</h2>
    <p>Hello!</p>
    <p>This is a test email from VendorXprt using <strong>ZeptoMail HTTP API</strong>.</p>
    
    <div style="background-color: #e8f5e8; padding: 15px; border-radius: 5px; margin: 15px 0;">
        <p>✅ If you're receiving this, the ZeptoMail integration is working!</p>
    </div>
    
    <h3>Configuration:</h3>
    <ul>
        <li><strong>API:</strong> ZeptoMail HTTP REST API</li>
        <li><strong>From:</strong> contact@vendorxprt.com</li>
        <li><strong>Service:</strong> VendorXprt</li>
    </ul>
    
    <hr>
    <p><small>Best regards,<br>VendorXprt Team</small></p>
</body>
</html>
        """,
    )

    if success:
        print("✅ Simple email sent successfully!")
    else:
        print("❌ Failed to send simple email")

    return success


def test_template_email():
    """Test sending template-based email"""
    print("\n🧪 Testing Template Email")
    print("=" * 60)

    # Test template email using welcome email
    test_user = None
    try:
        # Try to find existing test user or create one
        test_user = UserProfile.objects.filter(email__icontains="test").first()
        if not test_user:
            print("📝 No test user found, creating temporary test context")

            # Create temporary user data for testing
            class MockUser:
                email = "egyadesmond@gmail.com"
                first_name = "Test"
                last_name = "User"
                user_name = "testuser"

            test_user = MockUser()

        print(f"👤 Test user: {test_user.email}")

        # Test welcome email
        success = send_welcome_email(test_user)

        if success:
            print("✅ Template email sent successfully!")
        else:
            print("❌ Failed to send template email")

        return success

    except Exception as e:
        print(f"❌ Error testing template email: {e}")
        return False


def test_verification_email():
    """Test verification email"""
    print("\n🧪 Testing Verification Email")
    print("=" * 60)

    # Generate test verification code
    code = "123456"
    email = "egyadesmond@gmail.com"

    success = send_verification_email(email, code)

    if success:
        print("✅ Verification email sent successfully!")
    else:
        print("❌ Failed to send verification email")

    return success


def run_all_tests():
    """Run all ZeptoMail tests"""
    print("🚀 VendorXprt ZeptoMail Integration Tests")
    print("=" * 60)

    # Test 1: Client initialization
    client = test_zeptomail_client()
    if not client:
        print("❌ Cannot continue - ZeptoMail client initialization failed")
        return

    # Test 2: Simple email
    simple_test = test_simple_email()

    # Test 3: Template email
    template_test = test_template_email()

    # Test 4: Verification email
    verification_test = test_verification_email()

    # Summary
    print("\n🎯 Test Results Summary")
    print("=" * 60)
    print(f"✅ Client Init: {'Pass' if client else 'Fail'}")
    print(f"📧 Simple Email: {'Pass' if simple_test else 'Fail'}")
    print(f"📄 Template Email: {'Pass' if template_test else 'Fail'}")
    print(f"🔐 Verification Email: {'Pass' if verification_test else 'Fail'}")

    if all([client, simple_test, template_test, verification_test]):
        print("\n🎉 All tests passed! ZeptoMail integration is working perfectly!")
    else:
        print("\n⚠️  Some tests failed. Check the logs above for details.")


if __name__ == "__main__":
    run_all_tests()
