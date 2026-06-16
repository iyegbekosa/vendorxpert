from django.test import TestCase
from unittest.mock import patch

from userprofile.models import UserProfile, VendorProfile, VendorPlan
from .models import Category, Product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user():
    return UserProfile.objects.create_user(
        email="vendor@example.com",
        user_name="vendoruser",
        first_name="Vendor",
        last_name="User",
        password="strongpass123",
    )


def make_vendor(user):
    plan = VendorPlan.objects.create(name=VendorPlan.BASIC, price=2000, is_active=True)
    return VendorProfile.objects.create(
        user=user,
        store_name="Test Shop",
        store_description="Quality goods",
        plan=plan,
    )


def make_category():
    return Category.objects.create(title="Electronics", slug="electronics")


def make_product(vendor, category, title="Test Product", slug=None, **kwargs):
    """Create a Product while bypassing full_clean (Cloudinary not available in tests)."""
    product = Product(
        vendor=vendor,
        category=category,
        title=title,
        slug=slug or "",
        description="A great product",
        price=1500,
        product_image="test/image.jpg",  # CloudinaryField stores strings in tests
        **kwargs,
    )
    # Generate slug the same way save() does, then write directly to DB.
    if not product.slug and product.title:
        product.slug = product._generate_unique_slug()
    with patch.object(Product, "full_clean"):
        product.save()
    return product


# ---------------------------------------------------------------------------
# Product slug generation
# ---------------------------------------------------------------------------

class ProductSlugTests(TestCase):
    """Test automatic slug generation and uniqueness enforcement."""

    def setUp(self):
        self.vendor = make_vendor(make_user())
        self.category = make_category()

    def test_slug_auto_generated_from_title(self):
        product = make_product(self.vendor, self.category, title="Cool Widget")
        self.assertEqual(product.slug, "cool-widget")

    def test_slug_not_overwritten_on_update(self):
        product = make_product(self.vendor, self.category, title="Original Title")
        original_slug = product.slug
        product.title = "Changed Title"
        with patch.object(Product, "full_clean"):
            product.save()
        self.assertEqual(product.slug, original_slug)

    def test_duplicate_title_gets_numeric_suffix(self):
        first = make_product(self.vendor, self.category, title="Blue Bag")
        second = make_product(self.vendor, self.category, title="Blue Bag")
        self.assertNotEqual(first.slug, second.slug)
        self.assertTrue(
            second.slug.startswith("blue-bag-"),
            f"Expected suffix slug, got: {second.slug}",
        )

    def test_three_products_with_same_title_get_unique_slugs(self):
        products = [
            make_product(self.vendor, self.category, title="Red Shirt")
            for _ in range(3)
        ]
        slugs = {p.slug for p in products}
        self.assertEqual(len(slugs), 3, f"Expected 3 unique slugs, got: {slugs}")

    def test_explicit_slug_not_overridden_on_create(self):
        product = make_product(
            self.vendor, self.category, title="Any Title", slug="my-custom-slug"
        )
        self.assertEqual(product.slug, "my-custom-slug")

    def test_stock_set_to_in_stock_when_quantity_positive(self):
        product = make_product(self.vendor, self.category, quantity=5)
        self.assertEqual(product.stock, Product.IN_STOCK)

    def test_stock_set_to_out_of_stock_when_quantity_zero(self):
        product = make_product(self.vendor, self.category, quantity=0)
        self.assertEqual(product.stock, Product.OUT_OF_STOCK)
