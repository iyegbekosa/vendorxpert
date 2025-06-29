# userprofile/serializers.py
from rest_framework import serializers
from .models import UserProfile, VendorProfile
from store.serializers import Product, ProductSerializer
from store.models import OrderItem, Order
from django.utils.text import slugify
from datetime import timedelta, timezone
from store.utils import create_paystack_subaccount



class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = UserProfile
        fields = ['username', 'email', 'password']

    def create(self, validated_data):
        user = UserProfile(
            username=validated_data['username'],
            email=validated_data.get('email', '')
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class VendorRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorProfile
        fields = ['store_name', 'account_number', 'bank_code']

    def create(self, validated_data):
        request = self.context['request']
        account_number = validated_data.pop('account_number')
        bank_code = validated_data.pop('bank_code')

        vendor = VendorProfile.objects.create(
            user=request.user,
            subscription_expiry=timezone.now() + timedelta(days=30),
            **validated_data
        )

        create_paystack_subaccount(vendor, account_number, bank_code)

        return vendor

class VendorProfileSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = ['id', 'store_name', 'account_number', 'bank_code', 'products']

    def get_products(self, obj):
        products = Product.objects.filter(vendor=obj, status=Product.ACTIVE, stock=Product.IN_STOCK, vendor__subscription_status__in=['active', 'grace'])
        return ProductSerializer(products, many=True).data


class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        exclude = ['vendor', 'slug', 'created_at', 'updated_at']

    def update(self, instance, validated_data):
        if 'title' in validated_data:
            validated_data['slug'] = slugify(validated_data['title'])
        return super().update(instance, validated_data)



class OrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source='product.title', read_only=True)
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    quantity = serializers.IntegerField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'product_title', 'order_id', 'quantity', 'price']


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(source='orderitem_set', many=True, read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'created_at', 'total_cost', 'items']


class VendorOrderDetailSerializer(serializers.Serializer):
    order = serializers.SerializerMethodField()
    items = OrderItemSerializer(many=True)

    def get_order(self, obj):
        order = obj['order']
        return {
            'order_id': order.id,
            'ref': order.ref,
            'first_name': order.first_name,
            'last_name': order.last_name,
            'phone': str(order.phone),
            'pickup_location': order.pickup_location,
            'is_paid': order.is_paid,
            'created_at': order.created_at,
        }
    

class VendorOrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source='product.title', read_only=True)
    order_ref = serializers.CharField(source='order.ref', read_only=True)
    customer_name = serializers.SerializerMethodField()
    pickup_location = serializers.CharField(source='order.pickup_location', read_only=True)
    phone = serializers.CharField(source='order.phone', read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'product_title', 'quantity', 'price', 'fulfilled',
                  'order_ref', 'customer_name', 'pickup_location', 'phone']

    def get_customer_name(self, obj):
        return f"{obj.order.first_name} {obj.order.last_name}"