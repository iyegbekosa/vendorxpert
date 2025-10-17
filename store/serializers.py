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
