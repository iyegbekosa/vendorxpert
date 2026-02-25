from django.contrib import admin
from .models import UserProfile, VendorProfile, VendorPlan


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user_name",
        "email",
        "first_name",
        "last_name",
        "is_vendor",
        "start_date",
    ]
    list_filter = ["is_vendor", "is_active", "is_staff", "start_date"]
    search_fields = ["user_name", "email", "first_name", "last_name"]
    readonly_fields = ["start_date"]


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = [
        "store_name",
        "user",
        "plan",
        "subscription_status",
        "subscription_expiry",
        "is_verified",
    ]
    list_filter = ["subscription_status", "plan", "is_verified", "subscription_start"]
    search_fields = ["store_name", "user__user_name", "user__email"]
    readonly_fields = ["subscription_start", "trial_start"]

    fieldsets = (
        (
            "Store Information",
            {
                "fields": (
                    "user",
                    "store_name",
                    "store_description",
                    "store_logo",
                    "is_verified",
                )
            },
        ),
        (
            "Subscription Details",
            {
                "fields": (
                    "plan",
                    "subscription_status",
                    "subscription_start",
                    "subscription_expiry",
                    "trial_start",
                    "trial_end",
                    "last_payment_date",
                    "subscription_token",
                )
            },
        ),
        (
            "Contact Information",
            {"fields": ("whatsapp_number", "instagram_handle", "tiktok_handle")},
        ),
        (
            "Payment Information",
            {
                "fields": (
                    "account_number",
                    "bank_code",
                    "pending_ref",
                    "failed_payment_count",
                )
            },
        ),
        ("Status Management", {"fields": ("pause_reason", "paused_at")}),
    )


@admin.register(VendorPlan)
class VendorPlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "price_display",
        "max_products",
        "features_summary",
        "is_active",
    ]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]
    list_editable = ["is_active"]  # Allow quick enable/disable

    fieldsets = (
        (
            "Plan Details",
            {
                "fields": ("name", "description", "price", "is_active"),
                "description": "Basic plan information and pricing",
            },
        ),
        (
            "Limits & Features",
            {
                "fields": ("max_products", "features"),
                "description": "Plan limitations and feature list",
            },
        ),
    )

    def price_display(self, obj):
        """Display price with currency symbol"""
        return f"₦{obj.price:,}"

    price_display.short_description = "Price"
    price_display.admin_order_field = "price"

    def features_summary(self, obj):
        """Show abbreviated features list"""
        if obj.features:
            features = obj.features.split("\n")[:2]  # First 2 features
            summary = ", ".join(features)
            if len(obj.features.split("\n")) > 2:
                summary += "..."
            return summary
        return "No features listed"

    features_summary.short_description = "Key Features"

    # Add some helpful actions
    actions = ["make_active", "make_inactive"]

    def make_active(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} plans activated.")

    make_active.short_description = "Activate selected plans"

    def make_inactive(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} plans deactivated.")

    make_inactive.short_description = "Deactivate selected plans"
