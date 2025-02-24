from django.contrib import admin
from .models import UserProfile, VendorProfile


admin.site.register(UserProfile)
admin.site.register(VendorProfile)
