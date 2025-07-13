# userprofile/serializers.py
from rest_framework import serializers
from .models import UserProfile, VendorProfile, VendorPlan
from store.serializers import Product, ProductSerializer
from store.models import OrderItem, Order
from django.utils.text import slugify
from datetime import timedelta
from django.utils import timezone
from store.utils import create_paystack_subaccount


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = UserProfile
        fields = ["user_name", "email", "password"]

    def create(self, validated_data):
        user = UserProfile(
            user_name=validated_data["user_name"], email=validated_data.get("email", "")
        )
        user.set_password(validated_data["password"])
        user.save()
        return user


class VendorRegisterSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(
        max_length=255, help_text="The name of your store (required)"
    )
    account_number = serializers.CharField(
        max_length=20,
        help_text="Your bank account number for payment processing (required)",
    )
    bank_code = serializers.CharField(
        max_length=10,
        help_text="Your bank code (e.g., 044 for Access Bank, 058 for GTBank) (required)",
    )
    phone_number = serializers.CharField(
        required=False, allow_blank=True, help_text="Your phone number (optional)"
    )
    whatsapp_number = serializers.CharField(
        required=False, allow_blank=True, help_text="Your WhatsApp number (optional)"
    )

    class Meta:
        model = VendorProfile
        fields = [
            "store_name",
            "account_number",
            "bank_code",
            "phone_number",
            "whatsapp_number",
        ]

    def validate_account_number(self, value):
        """
        Validate account number format
        """
        # Remove any spaces or dashes
        account_number = value.replace(" ", "").replace("-", "")

        # Check if it's all digits
        if not account_number.isdigit():
            raise serializers.ValidationError("Account number must contain only digits")

        # Check length (most Nigerian banks use 10 digits)
        if len(account_number) != 10:
            raise serializers.ValidationError(
                "Account number must be exactly 10 digits"
            )

        return account_number

    def validate_bank_code(self, value):
        """
        Validate bank code format
        """
        # Common Nigerian bank codes
        valid_bank_codes = {
            "044": "Access Bank",
            "063": "Access Bank (Diamond)",
            "050": "Ecobank",
            "070": "Fidelity Bank",
            "011": "First Bank",
            "214": "First City Monument Bank",
            "058": "Guaranty Trust Bank",
            "030": "Heritage Bank",
            "301": "Jaiz Bank",
            "082": "Keystone Bank",
            "076": "Polaris Bank",
            "101": "Providus Bank",
            "221": "Stanbic IBTC Bank",
            "068": "Standard Chartered",
            "232": "Sterling Bank",
            "100": "SunTrust Bank",
            "032": "Union Bank",
            "033": "United Bank for Africa",
            "215": "Unity Bank",
            "035": "Wema Bank",
            "057": "Zenith Bank",
        }

        if value not in valid_bank_codes:
            raise serializers.ValidationError(
                f"Invalid bank code. Supported banks: {', '.join([f'{code} ({name})' for code, name in valid_bank_codes.items()])}"
            )

        return value

    def validate_store_name(self, value):
        """
        Validate store name
        """
        # Remove extra whitespace
        store_name = value.strip()

        # Check minimum length
        if len(store_name) < 3:
            raise serializers.ValidationError(
                "Store name must be at least 3 characters long"
            )

        # Check for inappropriate characters (basic check)
        if any(char in store_name for char in ["<", ">", "&", '"', "'"]):
            raise serializers.ValidationError("Store name contains invalid characters")

        return store_name

    def validate_phone_number(self, value):
        """
        Validate phone number format and uniqueness if provided
        """
        if not value or not value.strip():
            return None

        # Basic validation - you can expand this based on your requirements
        phone_number = value.strip()

        # Check if phone number already exists for another vendor
        if VendorProfile.objects.filter(phone_number=phone_number).exists():
            raise serializers.ValidationError(
                "This phone number is already registered with another vendor"
            )

        return phone_number

    def validate_whatsapp_number(self, value):
        """
        Validate WhatsApp number format and uniqueness if provided
        """
        if not value or not value.strip():
            return None

        # Basic validation - you can expand this based on your requirements
        whatsapp_number = value.strip()

        # Check if WhatsApp number already exists for another vendor
        if VendorProfile.objects.filter(whatsapp_number=whatsapp_number).exists():
            raise serializers.ValidationError(
                "This WhatsApp number is already registered with another vendor"
            )

        return whatsapp_number

    def validate(self, data):
        """
        Validate that the user isn't already a vendor and other business rules
        """
        request = self.context["request"]

        # Check if user is already a vendor
        if hasattr(request.user, "vendor_profile"):
            raise serializers.ValidationError("User is already registered as a vendor")

        return data

    def create(self, validated_data):
        request = self.context["request"]
        account_number = validated_data.pop("account_number")
        bank_code = validated_data.pop("bank_code")

        # Handle phone numbers - only set if provided and not empty
        phone_number = validated_data.pop("phone_number", None)
        whatsapp_number = validated_data.pop("whatsapp_number", None)

        # Clean empty strings to None
        if phone_number == "" or (phone_number and not phone_number.strip()):
            phone_number = None
        if whatsapp_number == "" or (whatsapp_number and not whatsapp_number.strip()):
            whatsapp_number = None

        try:
            # Step 1: Get or create a default plan for new vendors
            default_plan = None
            try:
                default_plan = VendorPlan.objects.get(
                    name=VendorPlan.BASIC, is_active=True
                )
            except VendorPlan.DoesNotExist:
                # If no basic plan exists, create one or use any active plan
                default_plan = VendorPlan.objects.filter(is_active=True).first()

            # Step 2: Create the vendor profile first (safer approach)
            vendor_data = {
                "user": request.user,
                "subscription_expiry": timezone.now() + timedelta(days=30),
                "plan": default_plan,
                "subscription_status": "active",
                "is_verified": True,  # Auto-verify new vendors for now
                **validated_data,
            }

            # Set default store description if not provided
            if not validated_data.get("store_description"):
                vendor_data["store_description"] = (
                    f"Welcome to {validated_data.get('store_name', 'our store')}! We offer quality products and excellent service."
                )

            # Only set phone numbers if provided, otherwise they will remain NULL
            if phone_number:
                vendor_data["phone_number"] = phone_number
            if whatsapp_number:
                vendor_data["whatsapp_number"] = whatsapp_number

            vendor = VendorProfile.objects.create(**vendor_data)

            # Step 3: Mark the user as a vendor
            request.user.is_vendor = True
            request.user.save()

            # Step 4: Create Paystack subaccount and link it to the vendor
            try:
                create_paystack_subaccount(vendor, account_number, bank_code)
            except Exception as paystack_error:
                # If Paystack fails, we still have the vendor but log the error
                # The vendor can retry linking their account later
                import logging

                logger = logging.getLogger(__name__)
                logger.error(
                    f"Failed to create Paystack subaccount for vendor {vendor.pk}: {paystack_error}"
                )

                # You could also set a flag to indicate incomplete setup
                # vendor.paystack_setup_complete = False
                # vendor.save()

                # Don't raise the error - let the vendor registration succeed
                pass

            return vendor

        except Exception as e:
            # If vendor creation fails, nothing to clean up
            raise serializers.ValidationError(
                f"Failed to create vendor account: {str(e)}"
            )


class VendorProfileSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = ["id", "store_name", "products"]

    def get_products(self, obj):
        products = Product.objects.filter(
            vendor=obj,
            status=Product.ACTIVE,
            stock=Product.IN_STOCK,
            vendor__subscription_status__in=["active", "grace"],
        )
        return ProductSerializer(products, many=True).data


class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        exclude = ["vendor", "slug", "created_at", "updated_at"]

    def create(self, validated_data):
        # Auto-generate slug from title when creating a new product
        if "title" in validated_data:
            validated_data["slug"] = slugify(validated_data["title"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Auto-generate slug from title when updating product title
        if "title" in validated_data:
            validated_data["slug"] = slugify(validated_data["title"])
        return super().update(instance, validated_data)


class OrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)
    order_id = serializers.IntegerField(source="order.id", read_only=True)
    quantity = serializers.IntegerField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product_title", "order_id", "quantity", "price"]


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(source="orderitem_set", many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["id", "created_at", "total_cost", "items"]


class VendorOrderDetailSerializer(serializers.Serializer):
    order = serializers.SerializerMethodField()
    items = OrderItemSerializer(many=True)

    def get_order(self, obj):
        order = obj["order"]
        return {
            "order_id": order.id,
            "ref": order.ref,
            "first_name": order.first_name,
            "last_name": order.last_name,
            "phone": str(order.phone),
            "pickup_location": order.pickup_location,
            "is_paid": order.is_paid,
            "created_at": order.created_at,
        }


class VendorOrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)
    order_ref = serializers.CharField(source="order.ref", read_only=True)
    customer_name = serializers.SerializerMethodField()
    pickup_location = serializers.CharField(
        source="order.pickup_location", read_only=True
    )
    phone = serializers.CharField(source="order.phone", read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product_title",
            "quantity",
            "price",
            "fulfilled",
            "order_ref",
            "customer_name",
            "pickup_location",
            "phone",
        ]

    def get_customer_name(self, obj):
        return f"{obj.order.first_name} {obj.order.last_name}"


class VendorListSerializer(serializers.ModelSerializer):
    """Serializer for listing vendors with essential information"""

    user_name = serializers.CharField(source="user.user_name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = [
            "id",
            "user_name",
            "store_name",
            "store_logo",
            "store_description",
            "phone_number",
            "whatsapp_number",
            "instagram_handle",
            "tiktok_handle",
            "is_verified",
            "plan_name",
            "subscription_status",
            "subscription_start",
            "subscription_expiry",
            "product_count",
        ]

    def get_product_count(self, obj):
        """Get count of active products for this vendor"""
        return Product.objects.filter(
            vendor=obj, status=Product.ACTIVE, stock=Product.IN_STOCK
        ).count()
