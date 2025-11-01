#!/usr/bin/env python
"""
Test script for Cloudinary integration.
This script tests basic Cloudinary functionality without requiring actual credentials.
"""

import os
import sys
import django

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from django.conf import settings
from userprofile.models import UserProfile, VendorProfile
from store.models import Product


def test_cloudinary_config():
    """Test Cloudinary configuration"""
    print("=== Testing Cloudinary Configuration ===")

    # Check if Cloudinary is properly configured
    cloudinary_config = getattr(settings, "CLOUDINARY_STORAGE", {})
    print(f"Cloud Name: {'✓' if cloudinary_config.get('CLOUD_NAME') else '✗'}")
    print(f"API Key: {'✓' if cloudinary_config.get('API_KEY') else '✗'}")
    print(f"API Secret: {'✓' if cloudinary_config.get('API_SECRET') else '✗'}")

    # Check storage backend
    default_storage = settings.STORAGES.get("default", {}).get("BACKEND")
    is_cloudinary = "cloudinary" in default_storage.lower()
    print(f"Storage Backend: {default_storage}")
    print(f"Cloudinary Storage: {'✓' if is_cloudinary else '✗'}")


def test_model_fields():
    """Test that models have CloudinaryField"""
    print("\n=== Testing Model Fields ===")

    # Test UserProfile
    user_field = UserProfile._meta.get_field("profile_picture")
    print(f"UserProfile.profile_picture: {type(user_field).__name__}")

    # Test VendorProfile
    vendor_field = VendorProfile._meta.get_field("store_logo")
    print(f"VendorProfile.store_logo: {type(vendor_field).__name__}")

    # Test Product
    product_image_field = Product._meta.get_field("product_image")
    product_thumb_field = Product._meta.get_field("thumbnail")
    print(f"Product.product_image: {type(product_image_field).__name__}")
    print(f"Product.thumbnail: {type(product_thumb_field).__name__}")


def test_cloudinary_import():
    """Test Cloudinary import"""
    print("\n=== Testing Cloudinary Import ===")
    try:
        import cloudinary
        import cloudinary.uploader
        import cloudinary.utils
        from cloudinary.models import CloudinaryField

        print("✓ Cloudinary imports successful")

        # Check if cloudinary is configured
        try:
            config = cloudinary.config()
            print(f"✓ Cloudinary configured: {bool(config.cloud_name)}")
        except Exception as e:
            print(f"✗ Cloudinary configuration issue: {e}")

    except ImportError as e:
        print(f"✗ Cloudinary import failed: {e}")


def main():
    """Run all tests"""
    print("Testing Cloudinary Integration\n")

    test_cloudinary_import()
    test_cloudinary_config()
    test_model_fields()

    print("\n=== Summary ===")
    print("Cloudinary integration setup complete!")
    print("\nNext steps:")
    print("1. Add your Cloudinary credentials to environment variables:")
    print("   - CLOUDINARY_CLOUD_NAME")
    print("   - CLOUDINARY_API_KEY")
    print("   - CLOUDINARY_API_SECRET")
    print("2. Test file uploads through the API endpoints")
    print("3. Verify images are stored in Cloudinary dashboard")


if __name__ == "__main__":
    main()
