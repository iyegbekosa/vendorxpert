"""Operational data owned by the marketplace team rather than by code."""

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PlatformSettings(models.Model):
    """Single row of business settings editable from the admin.

    Read it through ``operations.config.get_settings()`` (cached), never by
    querying directly, so every request sees one consistent value.
    """

    trial_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(180)],
        help_text="Length of the free trial new vendors get. Applies to new vendors only.",
    )
    grace_days = models.PositiveSmallIntegerField(
        default=7,
        validators=[MaxValueValidator(30)],
        help_text="Days a lapsed paid vendor keeps selling before their listings are hidden.",
    )
    max_quantity_per_item = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Most units of one product a buyer can have in their cart.",
    )
    accepting_orders = models.BooleanField(
        default=True,
        help_text="Turn off to pause checkout everywhere (e.g. during an incident). Browsing still works.",
    )
    orders_paused_message = models.CharField(
        max_length=200,
        blank=True,
        default="Checkout is paused for a short while. Please try again soon.",
        help_text="Shown to buyers while checkout is paused.",
    )
    vendor_signups_open = models.BooleanField(
        default=True, help_text="Turn off to stop new vendors from registering."
    )
    support_email = models.EmailField(default="support@vendorxprt.com")
    announcement = models.CharField(
        max_length=240,
        blank=True,
        help_text="Banner shown at the top of the marketplace. Leave empty for none.",
    )
    announcement_level = models.CharField(
        max_length=10,
        choices=[("info", "Information"), ("warning", "Warning")],
        default="info",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Platform settings"
        verbose_name_plural = "Platform settings"

    def __str__(self):
        return "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Platform settings can't be deleted.")


class PickupLocation(models.Model):
    """Places buyers can collect orders. ``code`` is stored on orders, so it
    never changes once created; deactivate a location instead of deleting it."""

    code = models.SlugField(max_length=50, unique=True, help_text="Permanent identifier, e.g. hall_2.")
    label = models.CharField(max_length=80, help_text="What buyers see, e.g. Hall 2.")
    is_active = models.BooleanField(default=True, help_text="Inactive locations can't be chosen at checkout.")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "label")

    def __str__(self):
        return self.label


class AuditLog(models.Model):
    """Append-only record of privileged actions. Never edited or deleted."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_label = models.CharField(max_length=254, help_text="Actor email at the time of the action.")
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=64, db_index=True)
    target_label = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True, help_text="Before/after values.")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.actor_label} {self.action} {self.target_label}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit log entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit log entries are immutable.")


def _ticket_reference():
    return f"T-{secrets.token_hex(3).upper()}"


class SupportTicket(models.Model):
    KIND_CHOICES = [
        ("order_problem", "Problem with an order"),
        ("payment", "Payment problem"),
        ("report_vendor", "Report a vendor"),
        ("report_listing", "Report a listing"),
        ("report_review", "Report a review"),
        ("account", "Account help"),
        ("other", "Something else"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In progress"),
        ("waiting_on_user", "Waiting on user"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]
    PRIORITY_CHOICES = [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]

    reference = models.CharField(max_length=12, unique=True, default=_ticket_reference, editable=False)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open", db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal", db_index=True)
    subject = models.CharField(max_length=150)
    description = models.TextField(max_length=3000)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets"
    )
    order = models.ForeignKey("store.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    vendor = models.ForeignKey(
        "userprofile.VendorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    product = models.ForeignKey("store.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    review = models.ForeignKey("store.Review", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
        limit_choices_to={"is_staff": True},
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.reference} · {self.subject}"


class TicketNote(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    is_internal = models.BooleanField(
        default=True, help_text="Internal notes are only visible to staff."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Note on {self.ticket.reference}"
