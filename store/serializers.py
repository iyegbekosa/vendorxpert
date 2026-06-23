from rest_framework import serializers
from .models import Product, Review, Order, Category
from userprofile.phone_utils import normalize_and_validate_nigerian_phone


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "title", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    thumbnail = serializers.SerializerMethodField()
    display_price = serializers.SerializerMethodField()
    stock_display = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()

    description = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "price",
            "thumbnail",
            "slug",
            "category",
            "display_price",
            "stock_display",
            "average_rating",
            "featured",
            "vendor",
            "description",
        ]

    def get_thumbnail(self, obj):
        return obj.get_thumbnail()

    def get_display_price(self, obj):
        return obj.display_price()

    def get_stock_display(self, obj):
        return obj.get_stock_display()

    def get_average_rating(self, obj):
        return obj.average_rating()

    def get_vendor(self, obj):
        from userprofile.serializers import VendorListSerializer

        return VendorListSerializer(obj.vendor).data


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["rating", "text"]


class ReviewDetailSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.user_name", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "rating",
            "text",
            "subject",
            "author_name",
            "created_date",
            "approved_review",
        ]


class CartItemSerializer(serializers.Serializer):
    product = serializers.SerializerMethodField()
    quantity = serializers.IntegerField()
    total_price = serializers.IntegerField()

    def get_product(self, obj):
        product = obj["product"]
        return {
            "id": product.id,
            "title": product.title,
            "thumbnail": product.get_thumbnail(),
            "price": product.display_price(),
        }


class CheckoutSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(required=True)
    first_name = serializers.CharField(required=True, max_length=50)
    last_name = serializers.CharField(required=True, max_length=50)

    class Meta:
        model = Order
        fields = ["first_name", "last_name", "phone", "pickup_location"]

    def validate_first_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("First name is required.")
        if not value.replace("-", "").replace(" ", "").isalpha():
            raise serializers.ValidationError("First name may only contain letters, spaces, and hyphens.")
        return value

    def validate_last_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Last name is required.")
        if not value.replace("-", "").replace(" ", "").isalpha():
            raise serializers.ValidationError("Last name may only contain letters, spaces, and hyphens.")
        return value

    def validate_phone(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Phone number is required.")
        return normalize_and_validate_nigerian_phone(value, "phone number")
