from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class OperationsConfig(AppConfig):
    default = True
    default_auto_field = "django.db.models.BigAutoField"
    name = "operations"
    verbose_name = "Marketplace operations"


class VendorXprtAdminConfig(admin_apps.AdminConfig):
    """Replaces django.contrib.admin so ``admin.site`` is our customised site."""

    default = False
    default_site = "operations.admin_site.VendorXprtAdminSite"
