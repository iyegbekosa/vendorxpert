"""Thin Paystack API client.

Every outbound call to Paystack goes through ``request`` so that timeouts,
authentication, JSON decoding and error reporting behave the same way across
order checkout, vendor onboarding and subscriptions.
"""

import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackError(Exception):
    """Raised when Paystack is unreachable or rejects a request.

    ``message`` is safe to show to end users; raw responses are only logged.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def request(method, path, *, json=None, params=None):
    """Call the Paystack API and return the ``data`` member of a successful response."""
    url = f"{settings.PAYSTACK_BASE_URL}/{path.lstrip('/')}"
    try:
        response = requests.request(
            method,
            url,
            json=json,
            params=params,
            headers=_headers(),
            timeout=settings.PAYSTACK_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        logger.warning("Paystack %s %s timed out", method, path)
        raise PaystackError(
            "The payment provider is taking too long to respond. Please try again."
        ) from exc
    except requests.RequestException as exc:
        logger.warning("Paystack %s %s failed: %s", method, path, exc)
        raise PaystackError(
            "We couldn't reach the payment provider. Please try again."
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        logger.error(
            "Paystack %s %s returned non-JSON (HTTP %s)", method, path, response.status_code
        )
        raise PaystackError(
            "The payment provider returned an unexpected response.", response.status_code
        ) from exc

    if not response.ok or not body.get("status"):
        message = body.get("message") or "The payment provider rejected the request."
        logger.warning(
            "Paystack %s %s rejected (HTTP %s): %s",
            method,
            path,
            response.status_code,
            message,
        )
        raise PaystackError(message, response.status_code)

    return body.get("data")


def initialize_transaction(
    *, email, amount_kobo, reference, callback_url, metadata=None, split=None, plan=None
):
    payload = {
        "email": email,
        "amount": int(amount_kobo),
        "reference": reference,
        "callback_url": callback_url,
    }
    if metadata:
        payload["metadata"] = metadata
    if split:
        payload["split"] = split
    if plan:
        payload["plan"] = plan
    return request("POST", "transaction/initialize", json=payload)


def verify_transaction(reference):
    return request("GET", f"transaction/verify/{reference}")


def fetch_subscription(subscription_code):
    return request("GET", f"subscription/{subscription_code}")


def create_subscription(*, customer, plan, authorization, start_date):
    return request(
        "POST",
        "subscription",
        json={
            "customer": customer,
            "plan": plan,
            "authorization": authorization,
            "start_date": start_date.isoformat(),
        },
    )


def disable_subscription(subscription_code, email_token):
    return request(
        "POST",
        "subscription/disable",
        json={"code": subscription_code, "token": email_token},
    )


def list_banks():
    return request("GET", "bank", params={"country": "nigeria", "perPage": 100})


def resolve_account(account_number, bank_code):
    return request(
        "GET",
        "bank/resolve",
        params={"account_number": account_number, "bank_code": bank_code},
    )


def create_subaccount(*, business_name, bank_code, account_number, percentage_charge):
    return request(
        "POST",
        "subaccount",
        json={
            "business_name": business_name,
            "settlement_bank": bank_code,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
        },
    )


def is_valid_webhook_signature(payload: bytes, signature: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"), payload, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
