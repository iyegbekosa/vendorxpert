import json

from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from operations import services as ops
from operations.admin_actions import RefundForm, confirmed_action, simple_action
from operations.models import AuditLog

from .models import Category, Order, OrderItem, Payment, Product, Review


def admin_link(obj, label=None):
    if obj is None:
        return "—"
    url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, label or obj)


def naira(amount):
    return f"₦{(amount or 0):,}"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "listings")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(listing_count=Count("product"))

    @admin.display(description="Listings", ordering="listing_count")
    def listings(self, obj):
        return obj.listing_count

    def has_delete_permission(self, request, obj=None):
        # Deleting a category would delete its products and break order history.
        if obj is not None and obj.product.exists():
            return False
        return super().has_delete_permission(request, obj)


# ── Listings ────────────────────────────────────────────────────────────────


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "vendor", "price_display", "quantity", "status", "featured", "created_at")
    list_filter = ("status", "featured", "category", "vendor__is_suspended")
    search_fields = ("title", "description", "vendor__store_name", "slug")
    list_select_related = ("vendor", "category")
    date_hierarchy = "created_at"
    readonly_fields = ("image_preview", "title", "slug", "description", "price", "quantity", "category",
                       "vendor_link", "status", "moderation_note", "featured", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("image_preview", "title", "vendor_link", "category", "price", "quantity", "description")}),
        ("Moderation", {"fields": ("status", "moderation_note", "featured")}),
        ("Record", {"fields": ("slug", "created_at", "updated_at")}),
    )
    actions = [
        confirmed_action(
            name="hide_listings", label="Hide listing", permission="moderate", service=ops.hide_product,
            consequences="The listing disappears from the marketplace and the vendor sees your reason. Past orders are unaffected.",
            reversible="Yes — use “Restore listing”.", submit_label="Hide listing",
        ),
        confirmed_action(
            name="restore_listings", label="Restore listing", permission="moderate", service=ops.restore_product,
            consequences="The listing becomes visible again if it has stock and the vendor can sell.",
            reversible="Yes — hide it again.", submit_label="Restore listing",
        ),
        simple_action(name="feature_listings", label="Feature listing", permission="feature",
                      service=lambda obj, **kw: ops.set_featured(obj, True, **kw)),
        simple_action(name="unfeature_listings", label="Stop featuring", permission="feature",
                      service=lambda obj, **kw: ops.set_featured(obj, False, **kw)),
    ]

    def has_add_permission(self, request):
        return False  # vendors create listings

    def has_change_permission(self, request, obj=None):
        return False  # changes happen through audited actions

    def has_delete_permission(self, request, obj=None):
        return False

    def has_moderate_permission(self, request):
        return request.user.has_perm("store.moderate_product")

    def has_feature_permission(self, request):
        return request.user.has_perm("store.feature_product")

    @admin.display(description="Price", ordering="price")
    def price_display(self, obj):
        return naira(obj.price)

    @admin.display(description="Vendor")
    def vendor_link(self, obj):
        return admin_link(obj.vendor)

    @admin.display(description="Photo")
    def image_preview(self, obj):
        return format_html('<img src="{}" style="max-height:180px;border-radius:8px">', obj.get_thumbnail())


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "author", "rating", "short_text", "approved_review", "created_date")
    list_filter = ("approved_review", "rating", ("created_date", admin.DateFieldListFilter))
    search_fields = ("text", "product__title", "author__email", "product__vendor__store_name")
    list_select_related = ("product", "author")
    readonly_fields = ("product", "author", "rating", "text", "created_date", "approved_review", "moderation_history")
    exclude = ("subject",)
    actions = [
        confirmed_action(
            name="hide_reviews", label="Hide review", permission="moderate", service=ops.hide_review,
            consequences="The review stops showing on the product and vendor pages and no longer counts towards ratings. The text is kept.",
            reversible="Yes — use “Restore review”.", submit_label="Hide review",
        ),
        confirmed_action(
            name="restore_reviews", label="Restore review", permission="moderate", service=ops.restore_review,
            consequences="The review shows again and counts towards ratings.",
            reversible="Yes — hide it again.", submit_label="Restore review",
        ),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # hide instead, so ratings can't be silently rewritten

    def has_moderate_permission(self, request):
        return request.user.has_perm("store.moderate_review")

    @admin.display(description="Review")
    def short_text(self, obj):
        return (obj.text[:70] + "…") if len(obj.text) > 70 else obj.text

    @admin.display(description="Moderation history")
    def moderation_history(self, obj):
        entries = AuditLog.objects.filter(target_type="store.Review", target_id=str(obj.pk))
        if not entries:
            return "—"
        return format_html_join(
            "", "<div>{} · {} · {} — {}</div>",
            ((e.created_at.strftime("%d %b %Y %H:%M"), e.actor_label, e.action, e.reason) for e in entries),
        )


# ── Orders & payments ───────────────────────────────────────────────────────


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    fields = ("product_link", "vendor", "quantity", "line_total", "fulfilled")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Product")
    def product_link(self, obj):
        return admin_link(obj.product)

    @admin.display(description="Vendor")
    def vendor(self, obj):
        return admin_link(obj.product.vendor)

    @admin.display(description="Line total")
    def line_total(self, obj):
        return naira(obj.price)


class PaymentInline(admin.TabularInline):
    model = Payment
    fields = ("payment_link", "amount", "status", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Reference")
    def payment_link(self, obj):
        return admin_link(obj, obj.ref)


class AwaitingPickupFilter(admin.SimpleListFilter):
    title = "pickup"
    parameter_name = "awaiting_pickup"

    def lookups(self, request, model_admin):
        return [("yes", "Awaiting pickup"), ("no", "All collected")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(items__fulfilled=False).distinct()
        if self.value() == "no":
            return queryset.exclude(items__fulfilled=False)
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("ref", "buyer", "total_display", "is_paid", "paid_at", "pickup", "refund_status")
    list_filter = ("is_paid", AwaitingPickupFilter, "refund_status", "pickup_location", ("created_at", admin.DateFieldListFilter))
    search_fields = ("ref", "created_by__email", "first_name", "last_name", "phone", "items__product__title")
    list_select_related = ("created_by",)
    date_hierarchy = "created_at"
    inlines = [OrderItemInline, PaymentInline]
    readonly_fields = ("ref", "buyer_link", "first_name", "last_name", "phone", "pickup",
                       "subtotal", "fee", "total_display", "is_paid", "created_at", "paid_at",
                       "refund_status", "refund_requested_at", "refunded_at", "timeline")
    fieldsets = (
        ("Order", {"fields": ("ref", "buyer_link", "created_at", "is_paid", "paid_at")}),
        ("Pickup", {"fields": ("first_name", "last_name", "phone", "pickup")}),
        ("Money", {"fields": ("subtotal", "fee", "total_display", "refund_status", "refund_requested_at", "refunded_at")}),
        ("Timeline", {"fields": ("timeline",)}),
    )
    actions = [
        confirmed_action(
            name="refund_orders", label="Refund order in full", permission="refund", service=ops.refund_order,
            form_class=RefundForm,
            consequences=("Paystack refunds the full amount the buyer paid, including the processing fee, to "
                          "their card or bank. The order shows “Refund pending” until Paystack confirms."),
            reversible="No — a refund can't be undone once Paystack processes it.", submit_label="Refund",
        ),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_refund_permission(self, request):
        return request.user.has_perm("store.refund_order")

    @admin.display(description="Buyer")
    def buyer(self, obj):
        return obj.created_by.email if obj.created_by else "—"

    @admin.display(description="Buyer")
    def buyer_link(self, obj):
        return admin_link(obj.created_by, obj.created_by and obj.created_by.email)

    @admin.display(description="Pickup point", ordering="pickup_location")
    def pickup(self, obj):
        return obj.get_pickup_location_display()

    @admin.display(description="Items")
    def subtotal(self, obj):
        return naira(obj.total_cost)

    @admin.display(description="Processing fee")
    def fee(self, obj):
        return naira(obj.service_fee)

    @admin.display(description="Total", ordering="total_cost")
    def total_display(self, obj):
        return naira(obj.amount_due)

    @admin.display(description="What happened")
    def timeline(self, obj):
        events = [(obj.created_at, "Checkout started")]
        for payment in obj.payments.all():
            events.append((payment.created_at, f"Payment {payment.ref} — {payment.status}"))
        if obj.paid_at:
            events.append((obj.paid_at, f"Paid {naira(obj.amount_due)}"))
        collected = [item.product.title for item in obj.items.select_related("product") if item.fulfilled]
        if collected:
            events.append((obj.paid_at or obj.created_at, "Collected: " + ", ".join(collected)))
        if obj.refund_requested_at:
            events.append((obj.refund_requested_at, "Refund requested"))
        if obj.refunded_at:
            events.append((obj.refunded_at, "Refund completed"))
        for entry in AuditLog.objects.filter(target_type="store.Order", target_id=str(obj.pk)):
            events.append((entry.created_at, f"{entry.actor_label}: {entry.action} — {entry.reason}"))
        for ticket in obj.tickets.all():
            events.append((ticket.created_at, f"Support ticket {ticket.reference} ({ticket.get_status_display()})"))
        events.sort(key=lambda event: event[0])
        return format_html_join(
            "", "<div style='margin-bottom:4px'><strong>{}</strong> — {}</div>",
            ((moment.strftime("%d %b %Y %H:%M"), text) for moment, text in events),
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("ref", "user", "amount_display", "status", "created_at", "order_link")
    list_filter = ("status", ("created_at", admin.DateFieldListFilter))
    search_fields = ("ref", "user__email", "order__ref")
    list_select_related = ("user", "order")
    date_hierarchy = "created_at"
    readonly_fields = ("ref", "user", "order_link", "amount_display", "status", "created_at", "gateway_response")
    exclude = ("paystack_response", "amount", "order")
    actions = [
        simple_action(name="recheck_payments", label="Re-check with Paystack", permission="recheck",
                      service=ops.recheck_payment),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_recheck_permission(self, request):
        return request.user.has_perm("store.recheck_payment")

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"₦{obj.amount:,.0f}"

    @admin.display(description="Order")
    def order_link(self, obj):
        return admin_link(obj.order, obj.order.ref)

    @admin.display(description="Paystack response")
    def gateway_response(self, obj):
        return format_html("<pre style='white-space:pre-wrap;max-height:400px;overflow:auto'>{}</pre>",
                           json.dumps(obj.paystack_response, indent=2, default=str))
