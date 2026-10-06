"""Cached access to admin-managed settings."""

from django.core.cache import cache

SETTINGS_CACHE_KEY = "operations:platform-settings:v1"
PICKUP_CACHE_KEY = "operations:pickup-locations:v1"
CACHE_SECONDS = 60


def get_settings():
    from .models import PlatformSettings

    cached = cache.get(SETTINGS_CACHE_KEY)
    if cached is None:
        cached, _ = PlatformSettings.objects.get_or_create(pk=1)
        cache.set(SETTINGS_CACHE_KEY, cached, CACHE_SECONDS)
    return cached


def pickup_locations(active_only=True):
    """[(code, label)] in display order."""
    from .models import PickupLocation

    locations = cache.get(PICKUP_CACHE_KEY)
    if locations is None:
        locations = list(PickupLocation.objects.values_list("code", "label", "is_active"))
        cache.set(PICKUP_CACHE_KEY, locations, CACHE_SECONDS)
    return [(code, label) for code, label, active in locations if active or not active_only]


def pickup_label(code):
    return dict(pickup_locations(active_only=False)).get(code, code)


def invalidate():
    cache.delete_many([SETTINGS_CACHE_KEY, PICKUP_CACHE_KEY])
