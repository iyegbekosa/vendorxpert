from rest_framework import serializers
from .models import Product, Review, Order, Category


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "title", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    average_rating = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()

    description = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "price",
            "get_thumbnail",
            "slug",
            "category",
            "display_price",
            "get_stock_display",
            "average_rating",
            "featured",
            "vendor",
            "description",
        ]

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
    class Meta:
        model = Order
        fields = ["first_name", "last_name", "phone", "pickup_location"]

    def validate_phone(self, value):
        """Normalize Nigerian local formats (090...) to +234 and validate.

        Accepts either an 11-digit local number starting with 0 (e.g. 09012345678)
        or an international +234XXXXXXXXXX. Returns the normalized +234 string.
        """
        if not value or not str(value).strip():
            raise serializers.ValidationError("Phone number is required")

        phone_str = str(value).strip().replace(" ", "").replace("-", "")

        # Convert local Nigerian format to international
        if phone_str.startswith("0") and len(phone_str) == 11:
            phone_str = "+234" + phone_str[1:]

        import re

        if not re.match(r"^\+234[0-9]{10}$", phone_str):
            raise serializers.ValidationError(
                "Phone must be in format +2349025144369 or 09025144369"
            )

        return phone_str
