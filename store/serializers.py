import re

from django.db.models import Avg, Count, Q
from rest_framework import serializers

from operations.config import pickup_locations
from userprofile.phone_utils import normalize_and_validate_nigerian_phone
from vendorxpert.uploads import media_url, validate_image_upload

from .models import Category, Order, Product, Review

MAX_PRODUCT_PRICE = 10_000_000
MAX_PRODUCT_QUANTITY = 10_000

# Letters (any script), spaces, hyphens, apostrophes and full stops.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-.][^\W\d_]+)*\.?$", re.UNICODE)


def with_rating_stats(queryset):
    """Annotate products with approved-review stats in the same query."""
    approved = Q(comments__approved_review=True)
    return queryset.annotate(
        avg_rating=Avg("comments__rating", filter=approved),
        review_count=Count("comments", filter=approved),
    )


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "title", "slug"]


class ProductVendorSerializer(serializers.Serializer):
    """The slice of vendor information a buyer needs on a product card."""

    id = serializers.IntegerField()
    store_name = serializers.CharField()
    store_logo = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField()

    def get_store_logo(self, vendor):
        return media_url(vendor.store_logo)


class ProductSerializer(serializers.ModelSerializer):
    """Read representation of a product for buyers and vendors."""

    thumbnail = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    display_price = serializers.IntegerField(source="price", read_only=True)
    stock_display = serializers.CharField(read_only=True)
    in_stock = serializers.BooleanField(source="is_in_stock", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    vendor = ProductVendorSerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "price",
            "display_price",
            "thumbnail",
            "image",
            "category",
            "category_slug",
            "quantity",
            "in_stock",
            "stock_display",
            "average_rating",
            "review_count",
            "featured",
            "status",
            "vendor",
            "created_at",
        ]
        read_only_fields = fields

    def get_thumbnail(self, obj):
        return obj.get_thumbnail()

    def get_image(self, obj):
        return media_url(obj.product_image) or obj.get_thumbnail()

    def get_average_rating(self, obj):
        avg = getattr(obj, "avg_rating", None)
        if avg is None and not hasattr(obj, "avg_rating"):
            return obj.average_rating()
        return round(avg, 1) if avg is not None else 0

    def get_review_count(self, obj):
        count = getattr(obj, "review_count", None)
        if count is None:
            return obj.comments.filter(approved_review=True).count()
        return count


class ProductWriteSerializer(serializers.ModelSerializer):
    """Fields a vendor may set on their own products.

    ``featured`` (paid placement), ``status`` and ``stock`` are deliberately
    excluded: placement is controlled by staff, deletion has its own endpoint
    and stock status is derived from ``quantity``.
    """

    product_image = serializers.ImageField(required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    class Meta:
        model = Product
        fields = ["title", "description", "price", "category", "quantity", "product_image"]

    def validate_title(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Give your product a name.")
        return value

    def validate_price(self, value):
        if value < 1:
            raise serializers.ValidationError("Price must be at least ₦1.")
        if value > MAX_PRODUCT_PRICE:
            raise serializers.ValidationError("That price looks too high. Check it and try again.")
        return value

    def validate_quantity(self, value):
        if value > MAX_PRODUCT_QUANTITY:
            raise serializers.ValidationError(
                f"Quantity can't be more than {MAX_PRODUCT_QUANTITY:,}."
            )
        return value

    def validate_product_image(self, value):
        return validate_image_upload(value)

    def validate(self, attrs):
        if self.instance is None and not attrs.get("product_image"):
            raise serializers.ValidationError({"product_image": ["Add a photo of the product."]})
        return attrs

    def update(self, instance, validated_data):
        if "title" in validated_data and validated_data["title"] != instance.title:
            # Regenerate a unique slug for the new title in Product.save().
            instance.slug = ""
        return super().update(instance, validated_data)


class ReviewSerializer(serializers.ModelSerializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    text = serializers.CharField(required=False, allow_blank=True, max_length=500)

    class Meta:
        model = Review
        fields = ["rating", "text"]


class ReviewDetailSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "rating", "text", "author_name", "created_date"]

    def get_author_name(self, review):
        author = review.author
        return (author.first_name or "").strip() or author.user_name


class CheckoutSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)
    phone = serializers.CharField()
    pickup_location = serializers.CharField()

    class Meta:
        model = Order
        fields = ["first_name", "last_name", "phone", "pickup_location"]

    def _validate_name(self, value, label):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(f"{label} is required.")
        if not _NAME_RE.match(value):
            raise serializers.ValidationError(f"{label} can only contain letters.")
        return value

    def validate_first_name(self, value):
        return self._validate_name(value, "First name")

    def validate_last_name(self, value):
        return self._validate_name(value, "Last name")

    def validate_phone(self, value):
        return normalize_and_validate_nigerian_phone(value, "phone number")

    def validate_pickup_location(self, value):
        if value not in dict(pickup_locations()):
            raise serializers.ValidationError("Choose where you'll pick up your order.")
        return value
