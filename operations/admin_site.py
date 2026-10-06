"""The VendorXprt admin: Django admin with a dashboard and a hardened login."""

from datetime import timedelta

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


class RateLimitedAdminLoginForm(AdminAuthenticationForm):
    """Locks an IP + email pair after repeated failures (the stock admin login
    has no protection against password guessing)."""

    def _cache_key(self):
        email = (self.data.get("username") or "").strip().lower()
        return f"admin-login-failures:{_client_ip(self.request)}:{email}"

    def clean(self):
        key = self._cache_key()
        if cache.get(key, 0) >= LOGIN_MAX_FAILURES:
            raise forms.ValidationError(
                "Too many failed sign-in attempts. Try again in 15 minutes.", code="locked"
            )
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            cache.set(key, cache.get(key, 0) + 1, LOGIN_LOCKOUT_SECONDS)
            raise
        cache.delete(key)
        return cleaned


def _link(model_label, **filters):
    app_label, model = model_label.split(".")
    url = reverse(f"admin:{app_label}_{model}_changelist")
    if filters:
        url += "?" + "&".join(f"{key}={value}" for key, value in filters.items())
    return url


class VendorXprtAdminSite(admin.AdminSite):
    site_header = "VendorXprt operations"
    site_title = "VendorXprt admin"
    index_title = "Marketplace overview"
    login_form = RateLimitedAdminLoginForm
    index_template = "admin/vx_index.html"

    def index(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "dashboard": self.dashboard(request)}
        return super().index(request, extra_context)

    def dashboard(self, request):
        """Live counts for the cards the current staff member may see."""
        from operations.models import AuditLog, SupportTicket
        from store.models import Order, Payment, Product, Review
        from userprofile.models import UserProfile, VendorProfile, selling_access_q

        user = request.user
        now = timezone.now()
        today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        sections = []

        if user.has_perm("store.view_order"):
            paid = Order.objects.filter(is_paid=True)
            week = paid.filter(paid_at__gte=week_ago).aggregate(
                count=Count("id"), sales=Sum("total_cost"), fees=Sum("service_fee")
            )
            awaiting_pickup = paid.filter(items__fulfilled=False).distinct().count()
            sections.append({
                "title": "Orders",
                "cards": [
                    {"label": "Paid today", "value": paid.filter(paid_at__gte=today).count(),
                     "url": _link("store.order", is_paid__exact=1)},
                    {"label": "Paid in the last 7 days", "value": week["count"] or 0,
                     "url": _link("store.order", is_paid__exact=1)},
                    {"label": "Sales in the last 7 days", "value": f"₦{(week['sales'] or 0):,}",
                     "hint": f"plus ₦{(week['fees'] or 0):,} processing fees"},
                    {"label": "Awaiting pickup", "value": awaiting_pickup,
                     "url": _link("store.order", is_paid__exact=1, awaiting_pickup="yes")},
                    {"label": "Refunds pending", "value": paid.filter(refund_status=Order.REFUND_PENDING).count(),
                     "url": _link("store.order", refund_status__exact="pending"), "alert": True},
                ],
            })

        if user.has_perm("store.view_payment"):
            stuck = Payment.objects.filter(status=Payment.PENDING, created_at__lte=now - timedelta(minutes=30),
                                           created_at__gte=now - timedelta(days=2)).count()
            sections.append({
                "title": "Payments",
                "cards": [
                    {"label": "Pending over 30 min (last 48h)", "value": stuck,
                     "url": _link("store.payment", status__exact="pending"), "alert": stuck > 0,
                     "hint": "Re-check these with Paystack"},
                    {"label": "Failed in the last 7 days",
                     "value": Payment.objects.filter(status=Payment.FAILED, created_at__gte=week_ago).count(),
                     "url": _link("store.payment", status__exact="failed")},
                ],
            })

        if user.has_perm("userprofile.view_vendorprofile"):
            vendors = VendorProfile.objects.all()
            sections.append({
                "title": "Vendors",
                "cards": [
                    {"label": "Selling now", "value": vendors.filter(selling_access_q()).count(),
                     "url": _link("userprofile.vendorprofile")},
                    {"label": "Trials ending within 7 days",
                     "value": vendors.filter(subscription_status="trial", trial_end__gte=now,
                                             trial_end__lte=now + timedelta(days=7)).count(),
                     "url": _link("userprofile.vendorprofile", subscription_status__exact="trial")},
                    {"label": "Suspended", "value": vendors.filter(is_suspended=True).count(),
                     "url": _link("userprofile.vendorprofile", is_suspended__exact=1)},
                ],
            })

        if user.has_perm("store.view_product"):
            sections.append({
                "title": "Listings & reviews",
                "cards": [
                    {"label": "Live listings", "value": Product.objects.purchasable().count(),
                     "url": _link("store.product", status__exact="active")},
                    {"label": "Hidden by staff", "value": Product.objects.filter(status=Product.HIDDEN).count(),
                     "url": _link("store.product", status__exact="hidden")},
                    {"label": "Hidden reviews", "value": Review.objects.filter(approved_review=False).count(),
                     "url": _link("store.review", approved_review__exact=0)},
                ],
            })

        if user.has_perm("operations.view_supportticket"):
            open_tickets = SupportTicket.objects.exclude(status__in=["resolved", "closed"])
            sections.append({
                "title": "Support",
                "cards": [
                    {"label": "Open tickets", "value": open_tickets.count(),
                     "url": _link("operations.supportticket", open="yes")},
                    {"label": "Urgent or high", "value": open_tickets.filter(priority__in=["urgent", "high"]).count(),
                     "url": _link("operations.supportticket", open="yes", priority__in="urgent,high"), "alert": True},
                    {"label": "Unassigned", "value": open_tickets.filter(assigned_to__isnull=True).count(),
                     "url": _link("operations.supportticket", open="yes", assigned_to__isnull="True")},
                    {"label": "Assigned to me", "value": open_tickets.filter(assigned_to=user).count(),
                     "url": _link("operations.supportticket", open="yes", assigned_to__id__exact=user.pk)},
                ],
            })

        if user.has_perm("userprofile.view_userprofile"):
            users = UserProfile.objects.all()
            sections.append({
                "title": "People",
                "cards": [
                    {"label": "Accounts", "value": users.count(), "url": _link("userprofile.userprofile")},
                    {"label": "New this week", "value": users.filter(start_date__gte=week_ago).count()},
                    {"label": "Suspended", "value": users.filter(is_active=False).count(),
                     "url": _link("userprofile.userprofile", is_active__exact=0)},
                ],
            })

        recent_audit = (
            list(AuditLog.objects.all()[:8]) if user.has_perm("operations.view_auditlog") else []
        )
        for section in sections:
            for card in section["cards"]:
                card.setdefault("alert", False)
                if card["alert"] and not card["value"]:
                    card["alert"] = False
        return {"sections": sections, "recent_audit": recent_audit}
