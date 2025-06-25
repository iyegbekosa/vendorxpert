from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from phonenumber_field.modelfields import PhoneNumberField


class CustomAccountManager(BaseUserManager):
    def create_user(self, email, user_name, first_name, last_name, password, **other_fields):
        
        if not email:
            raise ValueError(_('You must provide a valid email address'))

        email = self.normalize_email(email)
        user = self.model(email=email, user_name=user_name, first_name=first_name, last_name=last_name, **other_fields)
        user.set_password(password)
        user.save()
        return user
    
    def create_superuser(self, email, user_name, first_name, last_name, password, **other_fields):

        other_fields.setdefault('is_staff', True)
        other_fields.setdefault('is_superuser', True)
        other_fields.setdefault('is_active', True)

        if other_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must be assigned is_staff=True'))
        
        if other_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must be assigned is_superuser=True'))
        
        return self.create_user(email, user_name, first_name, last_name, password, **other_fields)



class UserProfile(AbstractBaseUser, PermissionsMixin):
    
    email = models.EmailField(_('email address'), unique=True)
    user_name = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    start_date = models.DateTimeField(default=timezone.now)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_vendor = models.BooleanField(default=False)

    objects = CustomAccountManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['user_name','first_name','last_name']

    def __str__(self):
        return self.user_name
    
    
class VendorProfile(models.Model):

    BANK_CHOICES = [
    ('044', 'Access Bank'),
    ('058', 'GTBank'),
    ('011', 'First Bank'),
    ('232', 'Sterling Bank'),
    ('033', 'UBA'),
    ('063', 'Access Bank (Diamond)'),
]

    user = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name="vendor_profile")
    store_name = models.CharField(max_length=150)
    store_logo = models.ImageField(upload_to='store_logo', blank=True, null=True)
    store_description = models.TextField()
    phone_number = PhoneNumberField(unique=True, default="08031234567")
    account_number = models.CharField(max_length=10)
    bank_code = models.CharField(max_length=50, choices=BANK_CHOICES, null=True)
    subaccount_code = models.CharField(max_length=100, unique=True, null=True, blank=True)
    whatsapp_number = PhoneNumberField(unique=True, default="08031234567")
    instagram_handle = models.CharField(max_length=50, blank=True)
    tiktok_handle = models.CharField(max_length=50, blank=True)
    is_verified = models.BooleanField(default=False)


    def __str__(self):
        return f"{self.store_name} (Vendor: {self.user.user_name})"
    
    def gen_paystack_code(self):
        pass

