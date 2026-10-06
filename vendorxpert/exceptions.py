"""A single error contract for every API response.

Every 4xx/5xx JSON response produced by this API has the shape::

    {"error": "Human readable message", "fields": {"field": ["message", ...]}}

``fields`` is only present for validation errors. Clients can always show
``error`` to the user and optionally map ``fields`` onto form inputs.

The contract is applied in two places so that no view can bypass it:

* ``api_exception_handler`` handles exceptions raised inside DRF views
  (validation, authentication, permission, throttling, 404s).
* ``ApiJSONRenderer`` normalises error payloads that views return directly,
  e.g. ``Response(serializer.errors, status=400)``.
"""

from rest_framework.renderers import JSONRenderer
from rest_framework.views import exception_handler

GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."


def _first_message(value):
    """Return the first human-readable string found in a DRF error structure."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            message = _first_message(item)
            if message:
                return message
        return ""
    if isinstance(value, dict):
        for item in value.values():
            message = _first_message(item)
            if message:
                return message
    return str(value) if value else ""


def _as_message_list(value):
    if isinstance(value, (list, tuple)):
        return [_first_message(item) for item in value if _first_message(item)]
    message = _first_message(value)
    return [message] if message else []


def normalize_error_payload(data):
    """Convert any DRF/legacy error payload into the documented contract."""
    if data is None:
        return {"error": GENERIC_ERROR_MESSAGE}

    if isinstance(data, (str, list, tuple)):
        return {"error": _first_message(data) or GENERIC_ERROR_MESSAGE}

    if not isinstance(data, dict):
        return {"error": GENERIC_ERROR_MESSAGE}

    payload = dict(data)
    error = payload.pop("error", None)
    detail = payload.pop("detail", None)
    message = payload.pop("message", None)
    fields = payload.pop("fields", None)
    # Legacy envelope keys that carry no information for the client.
    payload.pop("success", None)
    payload.pop("status", None)

    passthrough = {}
    for key in ("code", "retry_after"):
        if key in payload:
            passthrough[key] = payload.pop(key)

    # Whatever is left is a field -> errors mapping from a serializer.
    if fields is None and payload:
        fields = {key: _as_message_list(value) for key, value in payload.items()}

    summary = _first_message(error) or _first_message(detail) or _first_message(message)
    if not summary and fields:
        non_field = fields.get("non_field_errors")
        summary = _first_message(non_field) or _first_message(fields)

    result = {"error": summary or GENERIC_ERROR_MESSAGE, **passthrough}
    if fields:
        result["fields"] = fields
    return result


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    response.data = normalize_error_payload(response.data)
    if response.status_code == 404 and "matches the given query" in response.data["error"]:
        # Django's default 404 text names internal models; say it plainly.
        response.data["error"] = "We couldn't find that. It may have been removed."
    wait = getattr(exc, "wait", None)
    if wait is not None:
        response.data["retry_after"] = int(wait)
        response.data["error"] = (
            "Too many attempts. Please wait a little and try again."
        )
    return response


class ApiJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        if response is not None and response.status_code >= 400:
            data = normalize_error_payload(data)
        return super().render(data, accepted_media_type, renderer_context)
