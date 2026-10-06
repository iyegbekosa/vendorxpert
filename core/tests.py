from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from store.models import Order, Product
from userprofile.models import UserProfile


class SeedDemoTests(TestCase):
    def seed(self, *args):
        call_command("seed_demo", *args, stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_seeds_rerun_cleanly_and_clear_removes_everything(self):
        self.seed()
        self.seed()  # re-running replaces rather than duplicates
        demo_users = UserProfile.objects.filter(email__endswith="@demo.vendorxprt.test")
        self.assertEqual(demo_users.count(), 8)
        self.assertTrue(Product.objects.purchasable().exists())
        self.assertTrue(Order.objects.filter(is_paid=True).exists())

        self.seed("--clear")
        self.assertFalse(demo_users.exists())
        self.assertFalse(Order.objects.exists())

    @override_settings(DEBUG=False)
    def test_refuses_to_run_in_production(self):
        with self.assertRaises(CommandError):
            self.seed()
