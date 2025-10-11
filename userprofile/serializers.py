# userprofile/serializers.py
from rest_framework import serializers
from .models import UserProfile, VendorProfile, VendorPlan, SubscriptionHistory
from store.serializers import Product, ProductSerializer
from store.models import OrderItem, Order
from django.utils.text import slugify
from datetime import timedelta
from django.utils import timezone
from store.utils import create_paystack_subaccount
import requests
from django.core.files.base import ContentFile
from urllib.parse import urlparse
import os


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile details"""

    vendor_info = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "id",
            "user_name",
            "email",
            "first_name",
            "last_name",
            "hostel",
            "profile_picture",
            "start_date",
            "is_vendor",
            "vendor_info",
        ]

    def get_vendor_info(self, obj):
        """Get vendor information if user is a vendor"""
        if hasattr(obj, "vendor_profile"):
            vendor = obj.vendor_profile
            return {
                "id": vendor.id,
                "store_name": vendor.store_name,
                "store_description": vendor.store_description,
                "phone_number": (
                    str(vendor.phone_number) if vendor.phone_number else None
                ),
                "whatsapp_number": (
                    str(vendor.whatsapp_number) if vendor.whatsapp_number else None
                ),
                "instagram_handle": vendor.instagram_handle,
                "tiktok_handle": vendor.tiktok_handle,
                "is_verified": vendor.is_verified,
                "subscription_status": vendor.subscription_status,
                "subscription_start": vendor.subscription_start,
                "subscription_expiry": vendor.subscription_expiry,
            }
        return None


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile information (excluding profile picture)"""

    class Meta:
        model = UserProfile
        fields = [
            "first_name",
            "last_name",
            "hostel",
        ]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
            "hostel": {"required": False},
        }

    def validate_hostel(self, value):
        """Validate hostel choice"""
        if value and value not in [choice[0] for choice in UserProfile.HOSTEL_CHOICES]:
            raise serializers.ValidationError(
                f"Invalid hostel choice. Must be one of: {[choice[0] for choice in UserProfile.HOSTEL_CHOICES]}"
            )
        return value


class ProfilePictureUploadSerializer(serializers.ModelSerializer):
    """Dedicated serializer for profile picture uploads"""

    class Meta:
        model = UserProfile
        fields = ["profile_picture"]
        extra_kwargs = {
            "profile_picture": {
                "required": True,
                "help_text": "Upload a profile picture (JPG, PNG, GIF, SVG supported)",
            },
        }

    def validate_profile_picture(self, value):
        """Validate uploaded profile picture"""
        if value:
            # Check file size (limit to 5MB)
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError(
                    "Profile picture file size cannot exceed 5MB."
                )

            # Check file type
            valid_extensions = [".jpg", ".jpeg", ".png", ".gif", ".svg"]
            import os

            ext = os.path.splitext(value.name)[1].lower()
            if ext not in valid_extensions:
                raise serializers.ValidationError(
                    f"Invalid file type. Supported formats: {', '.join(valid_extensions)}"
                )

            # Additional validation for SVG files
            if ext == ".svg":
                # Basic SVG content validation
                try:
                    content = value.read()
                    value.seek(0)  # Reset file pointer

                    # Check if it's a valid SVG by looking for SVG tags
                    content_str = content.decode("utf-8", errors="ignore")
                    if not (
                        "<svg" in content_str.lower()
                        and "</svg>" in content_str.lower()
                    ):
                        raise serializers.ValidationError(
                            "Invalid SVG file. File must contain valid SVG content."
                        )
                except Exception:
                    raise serializers.ValidationError(
                        "Invalid SVG file. Unable to process the file."
                    )

        return value


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(max_length=150, required=True, allow_blank=False)
    last_name = serializers.CharField(max_length=150, required=True, allow_blank=False)

    class Meta:
        model = UserProfile
        fields = ["user_name", "email", "first_name", "last_name", "password"]

    def validate_first_name(self, value):
        """Ensure first_name is not just whitespace"""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "First name is required and cannot be empty."
            )
        return value.strip()

    def validate_last_name(self, value):
        """Ensure last_name is not just whitespace"""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "Last name is required and cannot be empty."
            )
        return value.strip()

    def create(self, validated_data):
        user = UserProfile(
            user_name=validated_data["user_name"],
            email=validated_data.get("email", ""),
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
        )
        user.set_password(validated_data["password"])
        user.save()
        return user


class VendorRegisterSerializer(serializers.ModelSerializer):
    # Store logo can be either a URL string or an uploaded file
    store_logo = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="URL to a logo image (optional when sending JSON)",
    )

    def to_internal_value(self, data):
        # If store_logo is a file upload, remove it from data so CharField doesn't validate it
        # We'll handle the file in create() method
        request = self.context.get("request")
        if request and hasattr(request, "FILES") and "store_logo" in request.FILES:
            # Make a copy of data and remove store_logo to avoid CharField validation
            data = data.copy() if hasattr(data, "copy") else dict(data)
            data.pop("store_logo", None)

        return super().to_internal_value(data)

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
            "store_logo",
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
        # Extract and remove fields we will handle manually
        account_number = validated_data.pop("account_number")
        bank_code = validated_data.pop("bank_code")
        store_logo_url = validated_data.pop("store_logo", None)

        # Check if an uploaded file was provided (multipart/form-data)
        file_logo = None
        if hasattr(request, "FILES") and request.FILES.get("store_logo"):
            file_logo = request.FILES.get("store_logo")

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

            # Step 2: Create the vendor profile with trial period
            vendor_data = {
                "user": request.user,
                "plan": default_plan,
                "subscription_status": "trial",  # Start with trial
                "trial_start": timezone.now(),
                "trial_end": timezone.now() + timedelta(days=14),  # 14-day trial
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

            # Log trial creation
            from .models import SubscriptionHistory

            SubscriptionHistory.log_event(
                vendor=vendor,
                event_type="trial_started",
                new_plan=default_plan,
                notes="14-day trial period started on vendor registration",
            )

            # If a file was uploaded, validate and save it. Otherwise, try the URL path.
            if file_logo:
                # Basic validation: size and extension
                max_size = 5 * 1024 * 1024
                if hasattr(file_logo, "size") and file_logo.size > max_size:
                    raise serializers.ValidationError(
                        {"store_logo": ["File size cannot exceed 5MB."]}
                    )

                valid_extensions = [".jpg", ".jpeg", ".png", ".gif", ".svg"]
                name = getattr(file_logo, "name", "store_logo")
                ext = os.path.splitext(name)[1].lower()
                if ext == "" and hasattr(file_logo, "content_type"):
                    # attempt to infer extension from content_type (very basic)
                    if file_logo.content_type == "image/svg+xml":
                        ext = ".svg"

                if ext not in valid_extensions:
                    raise serializers.ValidationError(
                        {
                            "store_logo": [
                                f"Unsupported file type '{ext}'. Supported: {', '.join(valid_extensions)}"
                            ]
                        }
                    )

                # Save uploaded file to ImageField
                vendor.store_logo.save(name, file_logo, save=True)

            elif store_logo_url:
                try:
                    resp = requests.get(store_logo_url, timeout=6)
                    if resp.status_code == 200:
                        parsed = urlparse(store_logo_url)
                        filename = (
                            os.path.basename(parsed.path)
                            or f"store_logo_{vendor.pk}.png"
                        )
                        # Ensure filename has an extension
                        if not os.path.splitext(filename)[1]:
                            filename = f"{filename}.png"
                        vendor.store_logo.save(
                            filename, ContentFile(resp.content), save=True
                        )
                    else:
                        print(
                            f"[userprofile] Failed to fetch store_logo from {store_logo_url}: HTTP {resp.status_code}"
                        )
                except Exception as logo_exc:
                    print(
                        f"[userprofile] Error fetching store_logo from {store_logo_url}: {logo_exc}"
                    )

            # Step 3: Mark the user as a vendor
            request.user.is_vendor = True
            request.user.save()

            # Step 4: Create Paystack subaccount and link it to the vendor
            try:
                create_paystack_subaccount(vendor, account_number, bank_code)
            except Exception as paystack_error:
                # If Paystack fails, we still have the vendor. Print error so devs see it.
                print(
                    f"[userprofile] Failed to create Paystack subaccount for vendor {vendor.pk}: {paystack_error}"
                )

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
        # The slug will be auto-generated in the model's save method with uniqueness
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Update the product - slug will be regenerated if title changes
        if "title" in validated_data:
            # Clear the slug so it gets regenerated in the model's save method
            instance.slug = ""
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
    average_rating = serializers.SerializerMethodField()

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
            "average_rating",
        ]

    def get_product_count(self, obj):
        """Get count of active products for this vendor"""
        return Product.objects.filter(
            vendor=obj, status=Product.ACTIVE, stock=Product.IN_STOCK
        ).count()

    def get_average_rating(self, obj):
        """Calculate average rating across all vendor's products"""
        from django.db.models import Avg
        from store.models import Review

        # Get all reviews for all products belonging to this vendor
        vendor_reviews = Review.objects.filter(
            product__vendor=obj, approved_review=True
        ).aggregate(avg_rating=Avg("rating"))

        avg_rating = vendor_reviews["avg_rating"]
        return round(avg_rating, 1) if avg_rating is not None else 0.0


class VendorPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorPlan
        fields = [
            "id",
            "name",
            "price",
            "max_products",
            "paystack_plan_code",
            "is_active",
        ]
        read_only_fields = ["id", "paystack_plan_code"]


class SubscriptionInitiateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(
        help_text="ID of the vendor plan to subscribe to"
    )

    def validate_plan_id(self, value):
        try:
            plan = VendorPlan.objects.get(id=value, is_active=True)
            return value
        except VendorPlan.DoesNotExist:
            raise serializers.ValidationError("Invalid or inactive plan selected.")


class SubscriptionResponseSerializer(serializers.Serializer):
    authorization_url = serializers.URLField(help_text="Paystack payment URL")
    access_code = serializers.CharField(help_text="Paystack access code")
    reference = serializers.CharField(help_text="Payment reference")
    message = serializers.CharField(help_text="Success message")


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    """Serializer for subscription history events"""

    vendor_name = serializers.CharField(source="vendor.store_name", read_only=True)
    previous_plan_name = serializers.CharField(
        source="previous_plan.name", read_only=True
    )
    new_plan_name = serializers.CharField(source="new_plan.name", read_only=True)
    event_display = serializers.CharField(
        source="get_event_type_display", read_only=True
    )

    class Meta:
        model = SubscriptionHistory
        fields = [
            "id",
            "event_type",
            "event_display",
            "vendor_name",
            "previous_plan_name",
            "new_plan_name",
            "previous_status",
            "new_status",
            "amount",
            "payment_reference",
            "notes",
            "created_at",
        ]
        read_only_fields = fields
