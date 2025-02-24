from django.db import models
from userprofile.models import VendorProfile, UserProfile
from django.core.files import File
from io import BytesIO
from PIL import Image
from django.utils import timezone
from django.urls import reverse
from django.db.models import Avg



class Category(models.Model):
    title = models.CharField(max_length=50)
    slug = models.SlugField()

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.title


class Product(models.Model):
    DRAFT = "draft"
    WAITING_APPROVAL = "waiting approval"
    ACTIVE = 'active'
    DELETED = 'deleted'
    IN_STOCK = 'in stock'
    OUT_OF_STOCK = 'out of stock'

    STATUS_CHOICES = (
        (DRAFT , "draft"),
        (WAITING_APPROVAL , "waiting approval"),
        (ACTIVE , 'active'),
        (DELETED , 'deleted'),
    )

    STOCK_CHOICES = (
        (IN_STOCK , 'In stock'),
        (OUT_OF_STOCK , 'Out of stock'),

    )


    category = models.ForeignKey(Category, related_name='product', on_delete=models.CASCADE)
    vendor = models.ForeignKey(VendorProfile,related_name='product', on_delete=models.CASCADE)
    title = models.CharField(max_length=50)
    slug = models.SlugField()
    description = models.TextField()
    price = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_image = models.ImageField(upload_to='uploads/product_image/', blank=True, null=True)
    thumbnail = models.ImageField(upload_to='uploads/product_image/thumbnail', blank=True, null=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=ACTIVE)
    stock = models.CharField(max_length=50, choices=STOCK_CHOICES, default=IN_STOCK)
    featured = models.BooleanField(default=False)


    class Meta:
        ordering = ('-created_at',)

    def display_price(self):
        return self.price/100

    def __str__(self):
        return self.title
    
    def make_thumbnail(self, product_image, size=(300, 300)):
        img = Image.open(product_image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=85)
        name = product_image.name.replace('uploads/product_images/', '')
        thumbnail = File(thumb_io, name=name)
        
        return thumbnail
    
    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail.url
        else:
            if self.product_image:
                self.thumbnail = self.make_thumbnail(self.product_image)
                self.save()

                return self.thumbnail.url
            else:
                return 'https://via.placeholder.com/240x240x.jpg'
            
    def average_rating(self):
        avg_rating = self.comments.filter(approved_review=True).aggregate(Avg('rating'))['rating__avg']
        return round(avg_rating, 1) if avg_rating is not None else 0



class Review(models.Model):
    product = models.ForeignKey(Product, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(UserProfile, related_name='comments_by_user', on_delete=models.CASCADE)
    subject = models.CharField(max_length=50)
    text = models.TextField(max_length=500, blank=True)
    rating = models.FloatField()
    created_date = models.DateTimeField(default=timezone.now)
    approved_review = models.BooleanField(default=True)

    def disapprove(self):
        self.approved_review = False
        self.save()

    def approve(self):
        self.approved_review = True
        self.save()

    def get_absolute_url(self):
       return reverse("product_detail", kwargs={"pk": self.product.pk})
    
    def __str__(self):
        return self.text[:50]
    