import json

from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.forms.models import model_to_dict
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import config
from .audit import record
from .models import AuditLog, PickupLocation, PlatformSettings, SupportTicket, TicketNote


class ReadOnlyAdmin(admin.ModelAdmin):
    """Records nobody may create, edit or delete from the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Orders", {"fields": ("accepting_orders", "orders_paused_message", "max_quantity_per_item")}),
        ("Vendors", {"fields": ("vendor_signups_open", "trial_days", "grace_days")}),
        ("Communication", {"fields": ("announcement", "announcement_level", "support_email")}),
        ("History", {"fields": ("updated_at", "updated_by")}),
    )
    readonly_fields = ("updated_at", "updated_by")

    def changelist_view(self, request, extra_context=None):
        settings_obj = config.get_settings()
        return HttpResponseRedirect(
            reverse("admin:operations_platformsettings_change", args=[settings_obj.pk])
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = model_to_dict(PlatformSettings.objects.get(pk=obj.pk))
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        changes = {
            field: [before.get(field), getattr(obj, field)]
            for field in form.changed_data
        }
        record(actor=request.user, action="settings.change", target=obj, changes=changes, request=request)
        config.invalidate()


@admin.register(PickupLocation)
class PickupLocationAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("label", "code")

    def get_readonly_fields(self, request, obj=None):
        # Orders store the code; it must never change after creation.
        return ("code",) if obj else ()

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record(actor=request.user, action="pickup_location.change" if change else "pickup_location.add",
               target=obj, changes={field: form.cleaned_data.get(field) for field in form.changed_data},
               request=request)
        config.invalidate()


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor_label", "action", "target_type", "target_label", "short_reason")
    list_filter = ("action", "target_type", ("created_at", admin.DateFieldListFilter))
    search_fields = ("actor_label", "target_label", "target_id", "reason")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "actor_label", "action", "target_type", "target_id",
                       "target_label", "reason", "pretty_changes", "ip_address")
    exclude = ("actor", "changes")

    @admin.display(description="Reason")
    def short_reason(self, obj):
        return (obj.reason[:80] + "…") if len(obj.reason) > 80 else obj.reason

    @admin.display(description="Changes")
    def pretty_changes(self, obj):
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.changes, indent=2, default=str))


@admin.register(LogEntry)
class LogEntryAdmin(ReadOnlyAdmin):
    """Django's own record of add/change/delete made through the admin."""

    list_display = ("action_time", "user", "content_type", "object_repr", "action_flag", "change_message")
    list_filter = ("action_flag", "content_type")
    search_fields = ("object_repr", "change_message", "user__email")
    date_hierarchy = "action_time"


class TicketNoteInline(admin.StackedInline):
    model = TicketNote
    extra = 1
    fields = ("body", "is_internal", "author", "created_at")
    readonly_fields = ("author", "created_at")

    def has_change_permission(self, request, obj=None):
        return False  # notes are append-only

    def has_delete_permission(self, request, obj=None):
        return False


class OpenTicketFilter(admin.SimpleListFilter):
    title = "open"
    parameter_name = "open"

    def lookups(self, request, model_admin):
        return [("yes", "Open"), ("no", "Resolved or closed")]

    def queryset(self, request, queryset):
        closed = ["resolved", "closed"]
        if self.value() == "yes":
            return queryset.exclude(status__in=closed)
        if self.value() == "no":
            return queryset.filter(status__in=closed)
        return queryset


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "subject", "kind", "status", "priority", "reporter", "assigned_to", "created_at")
    list_filter = (OpenTicketFilter, "status", "priority", "kind", "assigned_to")
    search_fields = ("reference", "subject", "description", "reporter__email", "order__ref", "vendor__store_name")
    list_select_related = ("reporter", "assigned_to")
    date_hierarchy = "created_at"
    inlines = [TicketNoteInline]
    autocomplete_fields = ()
    readonly_fields = ("reference", "kind", "subject", "description", "reporter_link", "order_link",
                       "vendor_link", "product_link", "review_link", "created_at", "updated_at", "resolved_at")
    fieldsets = (
        ("Ticket", {"fields": ("reference", "kind", "subject", "description", "created_at", "updated_at", "resolved_at")}),
        ("Handling", {"fields": ("status", "priority", "assigned_to")}),
        ("Related", {"fields": ("reporter_link", "order_link", "vendor_link", "product_link", "review_link")}),
    )
    actions = ["assign_to_me", "mark_resolved"]

    def has_add_permission(self, request):
        return False  # tickets come from users

    def has_delete_permission(self, request, obj=None):
        return False

    def _admin_link(self, obj, label):
        if obj is None:
            return "—"
        url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, label or obj)

    @admin.display(description="Reporter")
    def reporter_link(self, obj):
        return self._admin_link(obj.reporter, obj.reporter.email)

    @admin.display(description="Order")
    def order_link(self, obj):
        return self._admin_link(obj.order, obj.order and obj.order.ref)

    @admin.display(description="Vendor")
    def vendor_link(self, obj):
        return self._admin_link(obj.vendor, None)

    @admin.display(description="Listing")
    def product_link(self, obj):
        return self._admin_link(obj.product, None)

    @admin.display(description="Review")
    def review_link(self, obj):
        return self._admin_link(obj.review, None)

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data:
            obj.resolved_at = timezone.now() if obj.status in ("resolved", "closed") else None
        super().save_model(request, obj, form, change)
        if form.changed_data:
            record(actor=request.user, action="ticket.update", target=obj,
                   changes={field: form.cleaned_data.get(field) for field in form.changed_data},
                   request=request)

    def save_formset(self, request, form, formset, change):
        notes = formset.save(commit=False)
        for note in notes:
            note.author = request.user
            note.save()
        formset.save_m2m()

    @admin.action(description="Assign to me", permissions=["change"])
    def assign_to_me(self, request, queryset):
        updated = queryset.update(assigned_to=request.user)
        for ticket in queryset:
            record(actor=request.user, action="ticket.assign", target=ticket, request=request)
        self.message_user(request, f"Assigned {updated} ticket(s) to you.", messages.SUCCESS)

    @admin.action(description="Mark as resolved", permissions=["change"])
    def mark_resolved(self, request, queryset):
        now = timezone.now()
        for ticket in queryset.exclude(status__in=["resolved", "closed"]):
            SupportTicket.objects.filter(pk=ticket.pk).update(status="resolved", resolved_at=now)
            record(actor=request.user, action="ticket.resolve", target=ticket, request=request)
        self.message_user(request, "Marked as resolved.", messages.SUCCESS)
