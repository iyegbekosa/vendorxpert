from rest_framework import serializers
from .models import Product, Review, Order, Category


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'title', 'slug']


class ProductSerializer(serializers.ModelSerializer):
    average_rating = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = [
            'id', 'title', 'price', 'get_thumbnail', 'slug', 'category', 
            'display_price', 'get_stock_display', 'average_rating', 'featured'
        ]
    def get_average_rating(self, obj):
        return obj.average_rating()

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['rating', 'text']


class CartItemSerializer(serializers.Serializer):
    product = serializers.SerializerMethodField()
    quantity = serializers.IntegerField()
    total_price = serializers.IntegerField()

    def get_product(self, obj):
        product = obj['product']
        return {
            'id': product.id,
            'title': product.title,
            'thumbnail': product.get_thumbnail(),
            'price': product.display_price(),
        }
    
class CheckoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['first_name', 'last_name', 'phone', 'pickup_location']