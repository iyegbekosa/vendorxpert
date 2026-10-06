"""Validation for user-uploaded images (product photos, logos, avatars)."""

import os

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def validate_image_upload(upload, max_bytes=DEFAULT_MAX_IMAGE_BYTES):
    """Reject anything that is not a real raster image within the size limit.

    The extension check alone is not enough: the file is decoded with Pillow so
    renamed scripts or SVG payloads (which can carry JavaScript) are refused.
    """
    if upload is None:
        return upload

    if getattr(upload, "size", 0) > max_bytes:
        raise serializers.ValidationError(
            f"Image must be smaller than {max_bytes // (1024 * 1024)}MB."
        )

    extension = os.path.splitext(getattr(upload, "name", ""))[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError("Upload a JPG, PNG, WEBP or GIF image.")

    try:
        upload.seek(0)
        with Image.open(upload) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise serializers.ValidationError("This file isn't a valid image.")
    finally:
        upload.seek(0)

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise serializers.ValidationError("Upload a JPG, PNG, WEBP or GIF image.")
    return upload


def media_url(field):
    """Public URL for a Cloudinary image field, or None when empty.

    Values stored as absolute URLs (e.g. seeded demo data or images hosted
    elsewhere) are returned unchanged instead of being treated as Cloudinary
    public IDs.
    """
    if not field:
        return None
    public_id = str(getattr(field, "public_id", None) or field)
    if public_id.startswith(("http://", "https://")):
        # CloudinaryField splits the stored string at the first "." into
        # public_id and format; rejoin them to recover the original URL.
        image_format = getattr(field, "format", None)
        return f"{public_id}.{image_format}" if image_format else public_id
    return field.url
