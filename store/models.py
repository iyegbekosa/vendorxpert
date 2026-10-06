from cloudinary.models import CloudinaryField
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, F
from django.utils import timezone
from django.utils.text import slugify
from phonenumber_field.modelfields import PhoneNumberField

from userprofile.models import UserProfile, VendorProfile, selling_access_q
from vendorxpert.uploads import media_url


class Category(models.Model):
    title = models.CharField(max_length=50)
    slug = models.SlugField()

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.title


class ProductQuerySet(models.QuerySet):
    def visible(self):
        """Products a buyer may see: active listings from vendors allowed to sell."""
        return self.filter(status=Product.ACTIVE).filter(
            selling_access_q(prefix="vendor__")
        )

    def purchasable(self):
        """Visible products that currently have stock."""
        return self.visible().filter(quantity__gt=0)


class Product(models.Model):
    DRAFT = "draft"
    WAITING_APPROVAL = "waiting approval"
    ACTIVE = "active"
    DELETED = "deleted"
    HIDDEN = "hidden"
    IN_STOCK = "in stock"
    OUT_OF_STOCK = "out of stock"

    STATUS_CHOICES = (
        (DRAFT, "draft"),
        (WAITING_APPROVAL, "waiting approval"),
        (ACTIVE, "active"),
        (DELETED, "deleted"),
        (HIDDEN, "hidden by staff"),
    )

    STOCK_CHOICES = (
        (IN_STOCK, "In stock"),
        (OUT_OF_STOCK, "Out of stock"),
    )

    category = models.ForeignKey(
        Category, related_name="product", on_delete=models.CASCADE
    )
    vendor = models.ForeignKey(
        VendorProfile, related_name="product", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=50)
    slug = models.SlugField()
    description = models.TextField()
    price = models.BigIntegerField(
        validators=[MinValueValidator(1, message="Enter a valid price greater than 0.")]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_image = CloudinaryField(
        "image",
        folder="product_images",
        blank=False,
        null=False,
        transformation={
            "width": 800,
            "height": 600,
            "crop": "fill",
            "quality": "auto:good",
        },
    )
    thumbnail = CloudinaryField(
        "image",
        folder="product_thumbnails",
        blank=True,
        null=True,
        transformation={
            "width": 300,
            "height": 300,
            "crop": "fill",
            "quality": "auto:good",
        },
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=ACTIVE, db_index=True)
    stock = models.CharField(max_length=50, choices=STOCK_CHOICES, default=IN_STOCK)
    quantity = models.PositiveIntegerField(
        default=0, help_text="Available quantity in stock"
    )
    featured = models.BooleanField(default=False)
    # Why staff hid this listing; shown to the vendor.
    moderation_note = models.CharField(max_length=255, blank=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        permissions = [
            ("moderate_product", "Can hide or restore listings"),
            ("feature_product", "Can feature or unfeature listings"),
        ]

    def display_price(self):
        return self.price

    def __str__(self):
        return self.title

    def get_thumbnail(self):
        """Get thumbnail URL from Cloudinary or product image"""
        if self.thumbnail:
            return media_url(self.thumbnail)
        elif self.product_image:
            return media_url(self.product_image)
        else:
            return "https://placehold.co/600x400"

    def average_rating(self):
        avg_rating = self.comments.filter(approved_review=True).aggregate(
            Avg("rating")
        )["rating__avg"]
        return round(avg_rating, 1) if avg_rating is not None else 0

    @property
    def is_in_stock(self):
        """Returns True if product has quantity > 0"""
        return self.quantity > 0

    @property
    def stock_display(self):
        """Returns 'in stock' or 'out of stock' based on quantity"""
        return self.IN_STOCK if self.is_in_stock else self.OUT_OF_STOCK

    def reduce_stock(self, amount):
        """Atomically reduce stock, never letting it go below zero.

        Uses a conditional UPDATE so two concurrent buyers cannot both take the
        last unit. Returns True when the stock was reduced.
        """
        updated = Product.objects.filter(pk=self.pk, quantity__gte=amount).update(
            quantity=F("quantity") - amount
        )
        if updated:
            Product.objects.filter(pk=self.pk, quantity=0).update(stock=self.OUT_OF_STOCK)
            self.refresh_from_db(fields=["quantity", "stock"])
        return bool(updated)

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()

        if not self.product_image:
            raise ValidationError({"product_image": "Product image is required."})

    def save(self, *args, **kwargs):
        # Generate slug before full_clean so the blank check passes.
        if not self.slug and self.title:
            self.slug = self._generate_unique_slug()

        self.full_clean()

        # Auto-update stock status based on quantity
        if self.quantity > 0:
            self.stock = self.IN_STOCK
        else:
            self.stock = self.OUT_OF_STOCK

        super().save(*args, **kwargs)

    def _generate_unique_slug(self):
        """Generate a unique slug for the product"""
        base_slug = slugify(self.title)
        slug = base_slug
        counter = 1

        # Keep checking until we find a unique slug
        while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug


class Review(models.Model):
    product = models.ForeignKey(
        Product, related_name="comments", on_delete=models.CASCADE
    )
    author = models.ForeignKey(
        UserProfile, related_name="comments_by_user", on_delete=models.CASCADE
    )
    subject = models.CharField(max_length=50, blank=True)
    text = models.TextField(max_length=500, blank=True)
    rating = models.FloatField(
        validators=[
            MinValueValidator(1, message="Rating must be between 1 and 5."),
            MaxValueValidator(5, message="Rating must be between 1 and 5."),
        ]
    )
    created_date = models.DateTimeField(default=timezone.now)
    approved_review = models.BooleanField(default=True)

    class Meta:
        permissions = [("moderate_review", "Can hide or restore reviews")]

    def disapprove(self):
        self.approved_review = False
        self.save()

    def approve(self):
        self.approved_review = True
        self.save()

    def __str__(self):
        return self.text[:50]


class Order(models.Model):

    ADMIN = "admin"
    FACULTY = "faculty"
    TETFUND = "tetfund"
    HALL_1 = "hall_1"
    HALL_2 = "hall_2"
    HALL_3 = "hall_3"
    HALL_4 = "hall_4"
    HALL_5 = "hall_5"
    HALL_6 = "hall_6"
    HALL_7 = "hall_7"
    HALL_8 = "hall_8"

    # Initial pickup points; the live list is operations.PickupLocation.
    PICKUP_CHOICES = (
        (ADMIN, "Admin Block"),
        (FACULTY, "Faculty Building"),
        (TETFUND, "TETFund Building"),
        (HALL_1, "Hall 1"),
        (HALL_2, "Hall 2"),
        (HALL_3, "Hall 3"),
        (HALL_4, "Hall 4"),
        (HALL_5, "Hall 5"),
        (HALL_6, "Hall 6"),
        (HALL_7, "Hall 7"),
        (HALL_8, "Hall 8"),
    )

    created_by = models.ForeignKey(
        UserProfile, related_name="order", on_delete=models.SET_NULL, null=True
    )
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone = PhoneNumberField()
    # Code of an operations.PickupLocation (admin-managed list).
    pickup_location = models.CharField(max_length=50, default=ADMIN)
    # Sum of item prices in naira (what vendors receive).
    total_cost = models.IntegerField(blank=True, null=True)
    # Payment processing fee in naira, charged on top of total_cost.
    service_fee = models.IntegerField(default=0)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    merchant_id = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ref = models.CharField(max_length=50, unique=True)

    REFUND_NONE = ""
    REFUND_PENDING = "pending"
    REFUND_PROCESSED = "processed"
    REFUND_FAILED = "failed"
    REFUND_CHOICES = [
        (REFUND_NONE, "Not refunded"),
        (REFUND_PENDING, "Refund pending"),
        (REFUND_PROCESSED, "Refunded"),
        (REFUND_FAILED, "Refund failed"),
    ]
    refund_status = models.CharField(max_length=12, choices=REFUND_CHOICES, blank=True, default="")
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("refund_order", "Can refund paid orders"),
            ("recheck_payment", "Can re-check payments with Paystack"),
        ]

    @property
    def amount_due(self):
        return (self.total_cost or 0) + self.service_fee

    def get_pickup_location_display(self):
        from operations.config import pickup_label

        return pickup_label(self.pickup_location)

    def __str__(self):
        return f"Order {self.ref}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    # PROTECT: order history must survive product removal. Products are
    # soft-deleted (status="deleted") so this never blocks normal use.
    product = models.ForeignKey(Product, related_name="item", on_delete=models.PROTECT)
    # Line total in naira (unit price x quantity) at the time of purchase.
    price = models.IntegerField()
    quantity = models.PositiveIntegerField(default=1)
    fulfilled = models.BooleanField(default=False, db_index=True)


class Payment(models.Model):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    ref = models.CharField(max_length=20, unique=True)
    # Amount charged in naira (order total + service fee).
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paystack_response = models.JSONField(
        null=True, blank=True
    )  # raw API response for reference


class CartItem(models.Model):
    """
    User-based cart item for authenticated users using JWT.
    Provides persistent cart storage across sessions.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items"
    )
    product = models.ForeignKey("Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "product")
        ordering = ["-updated_at"]

    def __str__(self):
        user_display = getattr(self.user, "user_name", None) or getattr(self.user, "email", "unknown")
        return f"{user_display} - {self.product.title} ({self.quantity})"

    @property
    def total_price(self):
        return self.product.price * self.quantity
