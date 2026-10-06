from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from store import paystack, services as store_services
from store.models import Order, OrderItem, Payment, Product, Review
from vendorxpert.testing import make_product, make_user, make_vendor, signed_webhook

from . import config
from .models import AuditLog, PickupLocation, PlatformSettings, SupportTicket
from .roles import ROLES


def make_staff(role=None, superuser=False):
    user = make_user(is_staff=True, is_superuser=superuser)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def paid_order(buyer, product, ref="ord-1"):
    order = Order.objects.create(
        created_by=buyer, first_name="Ada", last_name="Obi", phone="+2348031234567",
        total_cost=product.price, service_fee=20, ref=ref, is_paid=True, pickup_location="hall_2",
    )
    OrderItem.objects.create(order=order, product=product, price=product.price, quantity=1)
    Payment.objects.create(user=buyer, order=order, ref=ref, amount=product.price + 20, status=Payment.PAID)
    return order


class AdminPagesTests(TestCase):
    """Every admin page renders for a superuser and for each role."""

    def setUp(self):
        cache.clear()
        self.vendor = make_vendor()
        self.product = make_product(self.vendor)
        self.buyer = make_user()
        self.order = paid_order(self.buyer, self.product)
        Review.objects.create(product=self.product, author=self.buyer, rating=4, text="Nice")
        SupportTicket.objects.create(kind="other", subject="Help", description="Please help me", reporter=self.buyer)

    def test_superuser_can_open_every_changelist_and_change_page(self):
        self.client.force_login(make_staff(superuser=True))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200, url)
            obj = model.objects.first()
            if obj is not None:
                change_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
                self.assertEqual(self.client.get(change_url).status_code, 200, change_url)

    def test_each_role_sees_its_dashboard(self):
        for role in ROLES:
            self.client.force_login(make_staff(role))
            response = self.client.get(reverse("admin:index"))
            self.assertEqual(response.status_code, 200, role)


class RoleEnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.vendor = make_vendor()
        self.product = make_product(self.vendor)
        self.order = paid_order(make_user(), self.product)

    def post_action(self, url, action, pks, **extra):
        return self.client.post(url, {"action": action, "_selected_action": pks, **extra}, follow=True)

    def test_support_cannot_refund_even_by_posting_the_action(self):
        self.client.force_login(make_staff("Support"))
        url = reverse("admin:store_order_changelist")
        with patch.object(paystack, "refund_transaction") as refund:
            self.post_action(url, "refund_orders", [self.order.pk], apply="1", reason="x")
        refund.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.refund_status, "")

    def test_moderator_cannot_suspend_vendors(self):
        self.client.force_login(make_staff("Moderator"))
        url = reverse("admin:userprofile_vendorprofile_changelist")
        self.post_action(url, "suspend_vendors", [self.vendor.pk], apply="1", reason="x")
        self.vendor.refresh_from_db()
        self.assertFalse(self.vendor.is_suspended)

    def test_non_superuser_cannot_grant_staff_access(self):
        operations = make_staff("Operations")
        self.client.force_login(operations)
        target = make_user()
        response = self.client.get(reverse("admin:userprofile_userprofile_change", args=[target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="is_superuser"')


class ActionEffectTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin_user = make_staff(superuser=True)
        self.client.force_login(self.admin_user)
        self.vendor = make_vendor()
        self.product = make_product(self.vendor)
        self.api = APIClient()

    def act(self, model, action, obj, **extra):
        url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        return self.client.post(url, {"action": action, "_selected_action": [obj.pk], "apply": "1", **extra}, follow=True)

    def test_confirmation_page_is_shown_before_acting(self):
        url = reverse("admin:userprofile_vendorprofile_changelist")
        response = self.client.post(url, {"action": "suspend_vendors", "_selected_action": [self.vendor.pk]})
        self.assertContains(response, "What happens")
        self.vendor.refresh_from_db()
        self.assertFalse(self.vendor.is_suspended)

    def test_reason_is_required(self):
        self.act(type(self.vendor), "suspend_vendors", self.vendor, reason="")
        self.vendor.refresh_from_db()
        self.assertFalse(self.vendor.is_suspended)

    def test_suspending_a_vendor_hides_listings_but_keeps_order_access(self):
        self.act(type(self.vendor), "suspend_vendors", self.vendor, reason="Counterfeit goods")
        self.vendor.refresh_from_db()
        self.assertTrue(self.vendor.is_suspended)
        self.assertEqual(self.api.get("/api/products/").data["count"], 0)

        self.api.force_authenticate(self.vendor.user)
        self.assertEqual(self.api.get("/api/my-order/").status_code, 200)
        add = self.api.post("/api/add-product/", {"title": "x"})
        self.assertEqual(add.status_code, 403)
        self.assertIn("Counterfeit goods", add.data["error"])

        entry = AuditLog.objects.get(action="vendor.suspend")
        self.assertEqual((entry.actor, entry.reason), (self.admin_user, "Counterfeit goods"))

    def test_suspended_user_is_told_why_they_cannot_sign_in(self):
        buyer = make_user(email="sus@example.com")
        self.act(type(buyer), "suspend_users", buyer, reason="Fraud")
        response = self.api.post("/api/login", {"email": "sus@example.com", "password": "Str0ng-pass-123"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "account_suspended")

    def test_hidden_listing_shows_the_vendor_why(self):
        self.act(Product, "hide_listings", self.product, reason="Prohibited item")
        self.assertEqual(self.api.get("/api/products/").data["count"], 0)
        self.api.force_authenticate(self.vendor.user)
        mine = self.api.get("/api/my-products/").data["results"][0]
        self.assertEqual((mine["status"], mine["moderation_note"]), ("hidden", "Prohibited item"))

    def test_hidden_review_stops_counting(self):
        review = Review.objects.create(product=self.product, author=make_user(), rating=1, text="spam")
        self.act(Review, "hide_reviews", review, reason="Spam")
        stats = self.api.get(f"/api/product/{self.product.pk}/reviews/").data
        self.assertEqual(stats["count"], 0)

    @patch.object(paystack, "refund_transaction", return_value={"status": "pending"})
    def test_refund_goes_pending_then_processed_by_webhook(self, refund):
        order = paid_order(make_user(), self.product, ref="refund-me")
        self.act(Order, "refund_orders", order, reason="Vendor never delivered", restock="on")
        refund.assert_called_once()
        order.refresh_from_db()
        self.assertEqual(order.refund_status, Order.REFUND_PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 6)

        signed_webhook(self.api, {"event": "refund.processed", "data": {"transaction_reference": "refund-me"}})
        order.refresh_from_db()
        self.assertEqual(order.refund_status, Order.REFUND_PROCESSED)

        self.act(Order, "refund_orders", order, reason="again")
        self.assertEqual(refund.call_count, 1)  # can't refund twice

    def test_settings_changes_are_enforced_and_audited(self):
        url = reverse("admin:operations_platformsettings_change", args=[1])
        form = self.client.get(url).context["adminform"].form
        data = {name: value for name, value in form.initial.items() if value is not None}
        data.update(accepting_orders="", orders_paused_message="Back at 6pm", announcement="Exams week!")
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        buyer = make_user()
        store_services.add_to_cart(buyer, self.product.pk, 1)
        self.api.force_authenticate(buyer)
        checkout = self.api.post("/api/checkout/", {
            "first_name": "Ada", "last_name": "Obi", "phone": "08031234567", "pickup_location": "hall_2",
        }, format="json")
        self.assertEqual(checkout.data["code"], "orders_paused")
        self.assertEqual(checkout.data["error"], "Back at 6pm")
        self.assertEqual(self.api.get("/api/site-config/").data["announcement"], "Exams week!")
        self.assertTrue(AuditLog.objects.filter(action="settings.change").exists())

    def test_inactive_pickup_location_cannot_be_chosen(self):
        PickupLocation.objects.filter(code="hall_2").update(is_active=False)
        config.invalidate()
        buyer = make_user()
        store_services.add_to_cart(buyer, self.product.pk, 1)
        self.api.force_authenticate(buyer)
        cart = self.api.get("/api/cart/").data
        self.assertNotIn("hall_2", [loc["value"] for loc in cart["pickup_locations"]])
        response = self.api.post("/api/checkout/", {
            "first_name": "Ada", "last_name": "Obi", "phone": "08031234567", "pickup_location": "hall_2",
        }, format="json")
        self.assertIn("pickup_location", response.data["fields"])


class SafetyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_audit_log_is_immutable(self):
        entry = AuditLog.objects.create(actor_label="a", action="x", target_type="t", target_id="1", target_label="t")
        entry.reason = "edited"
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()
        self.client.force_login(make_staff(superuser=True))
        url = reverse("admin:operations_auditlog_delete", args=[entry.pk])
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_settings_singleton_cannot_be_deleted(self):
        with self.assertRaises(ValidationError):
            PlatformSettings.objects.get(pk=1).delete()

    def test_admin_login_locks_after_repeated_failures(self):
        staff = make_staff(superuser=True)
        url = reverse("admin:login")
        for _ in range(5):
            self.client.post(url, {"username": staff.email, "password": "wrong"})
        response = self.client.post(url, {"username": staff.email, "password": "Str0ng-pass-123"})
        self.assertContains(response, "Too many failed sign-in attempts")


class SupportApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.vendor = make_vendor()
        self.product = make_product(self.vendor)
        self.buyer = make_user()
        self.order = paid_order(self.buyer, self.product)

    def test_buyer_can_raise_ticket_on_own_order(self):
        self.api.force_authenticate(self.buyer)
        response = self.api.post("/api/support/tickets/", {
            "kind": "order_problem", "order_ref": self.order.ref, "message": "The vendor hasn't replied for two days.",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        ticket = SupportTicket.objects.get(reference=response.data["reference"])
        self.assertEqual((ticket.order, ticket.reporter), (self.order, self.buyer))
        self.assertEqual(len(self.api.get("/api/support/tickets/").data["results"]), 1)

    def test_cannot_attach_someone_elses_order(self):
        self.api.force_authenticate(make_user())
        response = self.api.post("/api/support/tickets/", {
            "kind": "order_problem", "order_ref": self.order.ref, "message": "Let me see this order please.",
        }, format="json")
        self.assertEqual(response.status_code, 404)

    def test_report_listing_links_vendor(self):
        self.api.force_authenticate(self.buyer)
        response = self.api.post("/api/support/tickets/", {
            "kind": "report_listing", "product_id": self.product.pk, "message": "This looks like a fake product.",
        }, format="json")
        ticket = SupportTicket.objects.get(reference=response.data["reference"])
        self.assertEqual(ticket.vendor, self.vendor)
