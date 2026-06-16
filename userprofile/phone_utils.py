"""Shared Nigerian phone-number validation helpers.

All validators in this project use the same format rules:
  - Accept 11-digit local format: 09012345678
  - Accept international format: +2349012345678
  - Return the normalised +234XXXXXXXXXX string
"""
import re
from rest_framework import serializers

_NIGERIAN_PHONE_RE = re.compile(r"^\+234[0-9]{10}$")


def normalize_and_validate_nigerian_phone(value: str, field_label: str = "phone number") -> str:
    """Normalize and validate a Nigerian phone number.

    Converts local 090... format to +234... and validates the result.
    Raises ``serializers.ValidationError`` if the number is invalid.

    Args:
        value: Raw phone string from user input.
        field_label: Human-readable field name used in error messages.

    Returns:
        Normalised ``+234XXXXXXXXXX`` string.
    """
    phone_str = str(value).strip().replace(" ", "").replace("-", "")

    if phone_str.startswith("0") and len(phone_str) == 11:
        phone_str = "+234" + phone_str[1:]

    if not _NIGERIAN_PHONE_RE.match(phone_str):
        raise serializers.ValidationError(
            f"Enter a valid 11-digit {field_label}."
        )

    return phone_str
