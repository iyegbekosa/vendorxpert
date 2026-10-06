"""Public endpoints backed by admin-managed data: site config and support."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from store.models import Order, Product, Review
from userprofile.models import UserProfile, VendorProfile

from .config import get_settings, pickup_locations
from .models import SupportTicket


class SupportTicketThrottle(UserRateThrottle):
    scope = "support_ticket"


@api_view(["GET"])
@permission_classes([AllowAny])
def site_config_api(request):
    """Operational settings the storefront displays or respects."""
    platform = get_settings()
    return Response({
        "announcement": platform.announcement or None,
        "announcement_level": platform.announcement_level,
        "support_email": platform.support_email,
        "accepting_orders": platform.accepting_orders,
        "orders_paused_message": platform.orders_paused_message if not platform.accepting_orders else None,
        "vendor_signups_open": platform.vendor_signups_open,
        "trial_days": platform.trial_days,
        "pickup_locations": [{"value": code, "label": label} for code, label in pickup_locations()],
        "halls": [{"value": code, "label": label} for code, label in UserProfile.HOSTEL_CHOICES],
    })


class TicketCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SupportTicket.KIND_CHOICES)
    message = serializers.CharField(min_length=10, max_length=3000)
    order_ref = serializers.CharField(required=False, allow_blank=True)
    product_id = serializers.IntegerField(required=False)
    vendor_id = serializers.IntegerField(required=False)
    review_id = serializers.IntegerField(required=False)


def _ticket_payload(ticket):
    return {
        "reference": ticket.reference,
        "kind": ticket.kind,
        "kind_display": ticket.get_kind_display(),
        "status": ticket.status,
        "status_display": ticket.get_status_display(),
        "subject": ticket.subject,
        "created_at": ticket.created_at,
        "order_ref": ticket.order.ref if ticket.order else None,
        "replies": [
            {"body": note.body, "created_at": note.created_at}
            for note in ticket.notes.filter(is_internal=False)
        ],
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SupportTicketThrottle])
def support_tickets_api(request):
    if request.method == "GET":
        tickets = SupportTicket.objects.filter(reporter=request.user).select_related("order")[:50]
        return Response({"results": [_ticket_payload(ticket) for ticket in tickets]})

    serializer = TicketCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    order = product = vendor = review = None
    if data.get("order_ref"):
        # Only the buyer — or a vendor with items in it — may raise a ticket on an order.
        order = Order.objects.filter(ref=data["order_ref"]).first()
        vendor_profile = getattr(request.user, "vendor_profile", None)
        if order is None or not (
            order.created_by_id == request.user.pk
            or (vendor_profile and order.items.filter(product__vendor=vendor_profile).exists())
        ):
            return Response({"error": "We couldn't find that order on your account."}, status=status.HTTP_404_NOT_FOUND)
    if data.get("product_id"):
        product = get_object_or_404(Product, pk=data["product_id"])
        vendor = product.vendor
    if data.get("vendor_id"):
        vendor = get_object_or_404(VendorProfile, pk=data["vendor_id"])
    if data.get("review_id"):
        review = get_object_or_404(Review, pk=data["review_id"])
        product = review.product

    subject = {
        "order_problem": f"Problem with order {order.ref}" if order else "Problem with an order",
        "payment": f"Payment problem — {order.ref}" if order else "Payment problem",
        "report_vendor": f"Report: {vendor.store_name}" if vendor else "Vendor report",
        "report_listing": f"Report: {product.title}" if product else "Listing report",
        "report_review": f"Review report on {product.title}" if product else "Review report",
    }.get(data["kind"], dict(SupportTicket.KIND_CHOICES)[data["kind"]])

    priority = "high" if data["kind"] in ("payment",) else "normal"
    ticket = SupportTicket.objects.create(
        kind=data["kind"],
        subject=subject[:150],
        description=data["message"],
        reporter=request.user,
        order=order,
        product=product,
        vendor=vendor,
        review=review,
        priority=priority,
    )
    support_email = get_settings().support_email
    return Response(
        {
            **_ticket_payload(ticket),
            "message": f"Thanks — we've got it. Your reference is {ticket.reference}. We'll reply by email ({support_email} if you need us sooner).",
        },
        status=status.HTTP_201_CREATED,
    )
