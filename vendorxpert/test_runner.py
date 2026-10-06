"""Test runner that forbids real network calls.

Tests must never reach Paystack or ZeptoMail with real credentials; any test
that forgets to mock an outbound HTTP call fails loudly instead.
"""

from unittest import mock

import requests
from django.test.runner import DiscoverRunner


class NetworkBlockedError(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlockedError("Outbound HTTP is disabled in tests; mock the call instead.")


class NoNetworkTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # Tests render admin pages without running collectstatic, so the
        # hashed-manifest storage used in production has no manifest to read.
        from django.conf import settings

        settings.STORAGES = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }

    def run_tests(self, *args, **kwargs):
        with mock.patch.object(requests.Session, "request", _blocked):
            return super().run_tests(*args, **kwargs)
