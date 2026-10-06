from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Count, Q
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils.html import format_html

from operations import services as ops
from operations.admin_actions import confirmed_action
from operations.audit import record
from store.models import Product

from .models import SubscriptionHistory, UserProfile, VendorPlan, VendorProfile


class StaffAccountCreationForm(UserCreationForm):
    class Meta:
        model = UserProfile
        fields = ("email", "user_name", "first_name", "last_name")


@admin.register(UserProfile)
class UserProfileAdmin(UserAdmin):
    add_form = StaffAccountCreationForm
    list_display = ("email", "full_name", "is_vendor", "is_active", "is_staff", "start_date", "last_login")
    list_filter = ("is_active", "is_vendor", "is_staff", "groups", ("start_date", admin.DateFieldListFilter))
    search_fields = ("email", "user_name", "first_name", "last_name")
    ordering = ("-start_date",)
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("start_date", "last_login", "is_active", "vendor_link")
    fieldsets = (
        ("Account", {"fields": ("email", "user_name", "password", "is_active", "start_date", "last_login")}),
        ("Profile", {"fields": ("first_name", "last_name", "hostel", "profile_picture", "is_vendor", "vendor_link")}),
        ("Staff access", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "description": "Create a staff account here, then give it a role under “Staff access”.",
            "fields": ("email", "user_name", "first_name", "last_name", "password1", "password2"),
        }),
    )
    actions = [
        confirmed_action(
            name="suspend_users", label="Suspend account", permission="suspend", service=ops.suspend_user,
            consequences=("The person is signed out everywhere and can't sign in. If they are a vendor their "
                          "listings are hidden too. Their orders and history are kept."),
            reversible="Yes — use “Restore account”.", submit_label="Suspend",
        ),
        confirmed_action(
            name="restore_users", label="Restore account", permission="suspend", service=ops.restore_user,
            consequences="The person can sign in again.", reversible="Yes.", submit_label="Restore",
        ),
    ]

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # Only superusers may grant access or edit identities.
            fields += ["email", "user_name", "is_staff", "is_superuser", "groups", "user_permissions", "is_vendor"]
        return fields

    def has_delete_permission(self, request, obj=None):
        return False  # suspend instead; deleting would break order history

    def has_suspend_permission(self, request):
        return request.user.has_perm("userprofile.suspend_user")

    @admin.display(description="Name")
    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    @admin.display(description="Store")
    def vendor_link(self, obj):
        vendor = getattr(obj, "vendor_profile", None)
        if vendor is None:
            return "—"
        url = reverse("admin:userprofile_vendorprofile_change", args=[vendor.pk])
        return format_html('<a href="{}">{}</a>', url, vendor.store_name)

    def save_model(self, request, obj, form, change):
        access_fields = {"is_staff", "is_superuser", "groups", "user_permissions"}
        super().save_model(request, obj, form, change)
        changed = set(form.changed_data)
        if change and changed:
            record(actor=request.user, action="user.edit", target=obj,
                   changes={"fields": sorted(changed), "access_changed": bool(access_fields & changed)},
                   request=request)


class ProductInline(admin.TabularInline):
    model = Product
    fields = ("product_link", "price", "quantity", "status", "featured")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(status=Product.DELETED)

    @admin.display(description="Listing")
    def product_link(self, obj):
        url = reverse("admin:store_product_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.title)


class SellingFilter(admin.SimpleListFilter):
    title = "selling now"
    parameter_name = "selling"

    def lookups(self, request, model_admin):
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request, queryset):
        from .models import selling_access_q

        if self.value() == "yes":
            return queryset.filter(selling_access_q())
        if self.value() == "no":
            return queryset.exclude(selling_access_q())
        return queryset


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ("store_name", "owner", "plan", "status", "selling", "is_suspended", "live_listings")
    list_filter = (SellingFilter, "subscription_status", "plan", "is_suspended", "is_verified")
    search_fields = ("store_name", "user__email", "user__first_name", "user__last_name", "whatsapp_number")
    list_select_related = ("user", "plan")
    inlines = [ProductInline]
    readonly_fields = (
        "owner_link", "status", "selling", "is_suspended", "suspension_reason", "subscription_start",
        "subaccount_code", "paystack_subscription_code", "public_store",
    )
    fieldsets = (
        ("Store", {"fields": ("store_name", "owner_link", "public_store", "store_description", "store_logo",
                              "is_verified")}),
        ("Contact", {"fields": ("whatsapp_number", "phone_number", "instagram_handle", "tiktok_handle")}),
        ("Status", {"fields": ("selling", "status", "is_suspended", "suspension_reason")}),
        ("Subscription", {"fields": ("plan", "scheduled_plan", "subscription_status", "subscription_start",
                                     "subscription_expiry", "trial_start", "trial_end", "last_payment_date",
                                     "failed_payment_count")}),
        ("Paystack", {"classes": ("collapse",), "fields": ("subaccount_code", "paystack_subscription_code")}),
    )
    actions = [
        confirmed_action(
            name="suspend_vendors", label="Suspend store", permission="suspend", service=ops.suspend_vendor,
            consequences=("The store and its listings disappear from the marketplace and no new orders can be "
                          "placed. The vendor can still sign in, see your reason, and complete orders already paid for."),
            reversible="Yes — use “Restore store”.", submit_label="Suspend store",
        ),
        confirmed_action(
            name="restore_vendors", label="Restore store", permission="suspend", service=ops.restore_vendor,
            consequences="The store becomes visible again if its plan or trial allows selling.",
            reversible="Yes.", submit_label="Restore store",
        ),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            live_count=Count("product", filter=Q(product__status=Product.ACTIVE, product__quantity__gt=0))
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # Subscription dates are money: only changed through payments or by a superuser.
            fields += ["plan", "scheduled_plan", "subscription_status", "subscription_expiry", "trial_start",
                       "trial_end", "last_payment_date", "failed_payment_count", "is_verified"]
        return fields

    def has_add_permission(self, request):
        return False  # vendors register themselves

    def has_delete_permission(self, request, obj=None):
        return False

    def has_suspend_permission(self, request):
        return request.user.has_perm("userprofile.suspend_vendor")

    @admin.display(description="Owner", ordering="user__email")
    def owner(self, obj):
        return obj.user.email

    @admin.display(description="Owner")
    def owner_link(self, obj):
        url = reverse("admin:userprofile_userprofile_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)

    @admin.display(description="Public page")
    def public_store(self, obj):
        from django.conf import settings

        url = f"{settings.FRONTEND_URL}/home/vendor/{obj.pk}"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, url)

    @admin.display(description="Plan status")
    def status(self, obj):
        return obj.get_effective_subscription_status()

    @admin.display(description="Selling", boolean=True)
    def selling(self, obj):
        return obj.has_selling_access()

    @admin.display(description="Live listings", ordering="live_count")
    def live_listings(self, obj):
        return obj.live_count

    def save_model(self, request, obj, form, change):
        before = model_to_dict(VendorProfile.objects.get(pk=obj.pk), fields=form.changed_data) if change else {}
        super().save_model(request, obj, form, change)
        if change and form.changed_data:
            record(actor=request.user, action="vendor.edit", target=obj,
                   changes={field: [str(before.get(field)), str(getattr(obj, field))] for field in form.changed_data},
                   request=request)


@admin.register(VendorPlan)
class VendorPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_display", "max_products", "is_active", "vendors")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    fieldsets = (
        ("Plan", {"fields": ("name", "description", "price", "is_active")}),
        ("Limits & features", {"fields": ("max_products", "features"),
                               "description": "One feature per line; shown to vendors on the billing page."}),
        ("Paystack", {"fields": ("paystack_plan_code",),
                      "description": "Must match a plan created in the Paystack dashboard with the same price."}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(vendor_count=Count("vendorprofile"))

    def get_readonly_fields(self, request, obj=None):
        return () if request.user.is_superuser else ("paystack_plan_code",)

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead

    @admin.display(description="Price", ordering="price")
    def price_display(self, obj):
        return f"₦{obj.price:,}"

    @admin.display(description="Vendors on plan", ordering="vendor_count")
    def vendors(self, obj):
        return obj.vendor_count

    def save_model(self, request, obj, form, change):
        before = model_to_dict(VendorPlan.objects.get(pk=obj.pk), fields=form.changed_data) if change else {}
        super().save_model(request, obj, form, change)
        if form.changed_data:
            record(actor=request.user, action="plan.change" if change else "plan.add", target=obj,
                   changes={field: [before.get(field), getattr(obj, field)] for field in form.changed_data},
                   request=request)


@admin.register(SubscriptionHistory)
class SubscriptionHistoryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "vendor", "event_type", "new_plan", "amount", "payment_reference")
    list_filter = ("event_type", ("created_at", admin.DateFieldListFilter))
    search_fields = ("vendor__store_name", "payment_reference", "notes")
    list_select_related = ("vendor", "new_plan")
    date_hierarchy = "created_at"
    exclude = ("paystack_response",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
