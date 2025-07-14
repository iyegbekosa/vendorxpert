from django.contrib import admin
from .models import UserProfile, VendorProfile, VendorPlan


admin.site.register(UserProfile)
admin.site.register(VendorProfile)
admin.site.register(VendorPlan)
