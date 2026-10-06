"""The single Paystack webhook for the whole platform.

Paystack delivers every event for the account to one URL, so this view handles
both marketplace order payments and vendor subscriptions. It is mounted at
every historical webhook path so whichever URL is configured in the Paystack
dashboard keeps working.

Responses: 200 once the event is processed or deliberately ignored (so
Paystack stops retrying), 400/403 for malformed or unsigned requests, and 500
only for unexpected failures — which makes Paystack retry later.
"""

import json
import logging

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from store import paystack
from store.models import Payment
from store.services import confirm_order_payment

from . import services

logger = logging.getLogger(__name__)


def _handle_charge_success(data):
    reference = data.get("reference")
    if reference and Payment.objects.filter(ref=reference).exists():
        confirm_order_payment(reference, transaction_data=data)
        return
    if services.apply_subscription_transaction(data) is None:
        logger.info("charge.success %s matched no order or vendor; ignoring", reference)


def _handle_charge_failed(data):
    reference = data.get("reference")
    if reference and Payment.objects.filter(ref=reference).exists():
        confirm_order_payment(reference, transaction_data=data)


def _handle_refund_processed(data):
    from operations.services import apply_refund_event

    apply_refund_event(data, processed=True)


def _handle_refund_failed(data):
    from operations.services import apply_refund_event

    apply_refund_event(data, processed=False)


EVENT_HANDLERS = {
    "charge.success": _handle_charge_success,
    "charge.failed": _handle_charge_failed,
    "subscription.create": services.handle_subscription_created,
    "subscription.disable": services.handle_subscription_disabled,
    "subscription.not_renew": services.handle_subscription_disabled,
    "invoice.payment_failed": services.handle_invoice_payment_failed,
    "refund.processed": _handle_refund_processed,
    "refund.failed": _handle_refund_failed,
}


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    if not paystack.is_valid_webhook_signature(request.body, signature):
        logger.warning("Rejected Paystack webhook with invalid signature")
        return HttpResponse(status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)

    event = payload.get("event")
    data = payload.get("data") or {}
    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        logger.info("Ignoring Paystack event %s", event)
        return HttpResponse(status=200)

    try:
        handler(data)
    except Exception:
        logger.exception("Failed to process Paystack event %s (%s)", event, data.get("reference"))
        return HttpResponse(status=500)
    return HttpResponse(status=200)
