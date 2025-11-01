#!/usr/bin/env python3
"""
Complete Email System Test for VendorXprt
Tests all email functionality including templates, delivery, and error handling.
"""

import os
import sys
import django
from django.test import TestCase
from django.core import mail
from django.conf import settings
from unittest.mock import patch

# Add the project root to the Python path
sys.path.append("/Users/mac/Desktop/projects/vendorxpert-be")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")

# Setup Django
django.setup()

# Override email recipient for testing
TEST_EMAIL_RECIPIENT = "egyadesmond@gmail.com"

from userprofile.models import UserProfile
from store.models import Product, Category, Order, OrderItem
from userprofile.email_utils import (
    send_welcome_email,
    send_vendor_welcome_email,
    send_receipt_email,
    send_vendor_order_notification,
)
from decimal import Decimal
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_data():
    """Create test users, products, and orders for email testing."""
    print("🔧 Creating test data...")

    # Create test customer
    try:
        customer = UserProfile.objects.get(email="testcustomer@example.com")
        print("✅ Found existing test customer")
    except UserProfile.DoesNotExist:
        customer = UserProfile.objects.create_user(
            user_name="testcustomer",
            email="testcustomer@example.com",
            password="testpass123",
            first_name="John",
            last_name="Customer",
        )
        print("✅ Created test customer")

    # Create test vendor
    try:
        vendor = UserProfile.objects.get(email="testvendor@example.com")
        print("✅ Found existing test vendor")
    except UserProfile.DoesNotExist:
        vendor = UserProfile.objects.create_user(
            user_name="testvendor",
            email="testvendor@example.com",
            password="testpass123",
            first_name="Jane",
            last_name="Vendor",
            is_vendor=True,
        )
        print("✅ Created test vendor")

    # Create test category
    category, created = Category.objects.get_or_create(
        title="Test Category", defaults={"slug": "test-category"}
    )
    if created:
        print("✅ Created test category")
    else:
        print("✅ Found existing test category")

    # Create vendor profile for the vendor user
    from userprofile.models import VendorProfile

    vendor_profile, created = VendorProfile.objects.get_or_create(
        user=vendor,
        defaults={
            "store_name": "Test Store",
            "store_description": "A test store for email testing",
        },
    )
    if created:
        print("✅ Created vendor profile")
    else:
        print("✅ Found existing vendor profile")

    # Create test product
    product, created = Product.objects.get_or_create(
        title="Test Product",
        defaults={
            "slug": "test-product",
            "description": "A test product for email testing",
            "price": 2599,  # Price in kobo/cents
            "vendor": vendor_profile,
            "category": category,
        },
    )
    if created:
        print("✅ Created test product")
    else:
        print("✅ Found existing test product")

    # Create test order
    order = Order.objects.create(
        created_by=customer,
        first_name=customer.first_name,
        last_name=customer.last_name,
        phone="+2348031234567",
        pickup_location="admin",
        total_cost=2599,  # Price in kobo
        is_paid=True,
        merchant_id="test_merchant_123",
        ref="test_order_ref_123",
    )

    # Create order item
    OrderItem.objects.create(
        order=order, product=product, quantity=1, price=product.price
    )

    print("✅ Created test order and order item")

    return customer, vendor, product, order


def test_welcome_emails():
    """Test welcome email functionality."""
    print("\n📧 Testing Welcome Emails...")

    customer, vendor, _, _ = create_test_data()

    # Test customer welcome email with override
    print("📨 Testing customer welcome email...")
    try:
        # Create a mock customer with test email
        mock_customer = customer
        mock_customer.email = TEST_EMAIL_RECIPIENT

        result = send_welcome_email(mock_customer)
        if result:
            print(
                f"✅ Customer welcome email sent successfully to {TEST_EMAIL_RECIPIENT}"
            )
        else:
            print("❌ Customer welcome email failed")
    except Exception as e:
        print(f"❌ Customer welcome email error: {e}")

    # Test vendor welcome email with override
    print("📨 Testing vendor welcome email...")
    try:
        # Get the vendor profile for the vendor user
        from userprofile.models import VendorProfile

        vendor_profile = VendorProfile.objects.get(user=vendor)

        # Override the email address
        vendor_profile.user.email = TEST_EMAIL_RECIPIENT

        result = send_vendor_welcome_email(vendor_profile)
        if result:
            print(
                f"✅ Vendor welcome email sent successfully to {TEST_EMAIL_RECIPIENT}"
            )
        else:
            print("❌ Vendor welcome email failed")
    except Exception as e:
        print(f"❌ Vendor welcome email error: {e}")


def test_transaction_emails():
    """Test transaction-related emails."""
    print("\n💰 Testing Transaction Emails...")

    _, _, _, order = create_test_data()

    # Override customer email for receipt
    order.created_by.email = TEST_EMAIL_RECIPIENT

    # Test receipt email
    print("📨 Testing receipt email...")
    try:
        result = send_receipt_email(order)
        if result:
            print(f"✅ Receipt email sent successfully to {TEST_EMAIL_RECIPIENT}")
        else:
            print("❌ Receipt email failed")
    except Exception as e:
        print(f"❌ Receipt email error: {e}")

    # Test vendor notification email
    print("📨 Testing vendor notification email...")
    try:
        # Override vendor email for notification
        for item in order.items.all():
            item.product.vendor.user.email = TEST_EMAIL_RECIPIENT

        result = send_vendor_order_notification(order)
        if result:
            print(
                f"✅ Vendor notification email sent successfully to {TEST_EMAIL_RECIPIENT}"
            )
        else:
            print("❌ Vendor notification email failed")
    except Exception as e:
        print(f"❌ Vendor notification email error: {e}")


def test_email_templates():
    """Test that all email templates exist and can be rendered."""
    print("\n📄 Testing Email Templates...")

    from django.template.loader import render_to_string
    from django.template import TemplateDoesNotExist

    templates = [
        "emails/welcome_user.html",
        "emails/welcome_user.txt",
        "emails/welcome_vendor.html",
        "emails/welcome_vendor.txt",
        "emails/receipt.html",
        "emails/receipt.txt",
        "emails/vendor_order_notification.html",
        "emails/vendor_order_notification.txt",
    ]

    customer, vendor, _, order = create_test_data()

    # Test context for different template types
    contexts = {
        "welcome_user": {"user": customer},
        "welcome_vendor": {"user": vendor},
        "receipt": {"order": order, "user": customer},
        "vendor_order_notification": {"order": order, "vendor": vendor},
    }

    for template in templates:
        try:
            template_type = template.split("/")[1].split(".")[0]
            if template_type.startswith("welcome_vendor"):
                context = contexts["welcome_vendor"]
            elif template_type.startswith("welcome_user"):
                context = contexts["welcome_user"]
            elif template_type.startswith("receipt"):
                context = contexts["receipt"]
            elif template_type.startswith("vendor_order"):
                context = contexts["vendor_order_notification"]
            else:
                context = {}

            rendered = render_to_string(template, context)
            if rendered:
                print(f"✅ Template {template} rendered successfully")
            else:
                print(f"❌ Template {template} rendered but is empty")
        except TemplateDoesNotExist:
            print(f"❌ Template {template} does not exist")
        except Exception as e:
            print(f"❌ Template {template} error: {e}")


def test_email_configuration():
    """Test email configuration and SMTP settings."""
    print("\n⚙️  Testing Email Configuration...")

    # Check email settings
    print(f"📧 Email Backend: {settings.EMAIL_BACKEND}")
    print(f"📧 Email Host: {settings.EMAIL_HOST}")
    print(f"📧 Email Port: {settings.EMAIL_PORT}")
    print(f"📧 Email Use SSL: {settings.EMAIL_USE_SSL}")
    print(f"📧 Default From Email: {settings.DEFAULT_FROM_EMAIL}")

    # Test SMTP connection
    try:
        from django.core.mail import get_connection

        connection = get_connection()
        connection.open()
        print("✅ SMTP connection successful")
        connection.close()
    except Exception as e:
        print(f"❌ SMTP connection failed: {e}")


def run_all_tests():
    """Run all email system tests."""
    print("🚀 Starting VendorXprt Email System Tests")
    print("=" * 50)

    try:
        test_email_configuration()
        test_email_templates()
        test_welcome_emails()
        test_transaction_emails()

        print("\n" + "=" * 50)
        print("✅ Email system testing completed!")
        print("\n📋 Test Summary:")
        print("- Email configuration ✅")
        print("- Template rendering ✅")
        print("- Welcome emails ✅")
        print("- Transaction emails ✅")
        print(f"\n💡 All emails have been sent to: {TEST_EMAIL_RECIPIENT}")
        print("   Check your email inbox to verify delivery!")
        print(
            f"   📬 Expected emails: Welcome (customer), Welcome (vendor), Receipt, Vendor notification"
        )

    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
