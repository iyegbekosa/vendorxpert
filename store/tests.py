from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from vendorxpert.testing import (
    make_category,
    make_plan,
    make_product,
    make_user,
    make_vendor,
    signed_webhook,
)

from . import paystack, services
from .models import CartItem, Order, OrderItem, Payment, Product, Review


def paystack_success(reference, amount_kobo, **extra):
    return {"status": "success", "reference": reference, "amount": amount_kobo, "currency": "NGN", **extra}


class ProductSlugTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()

    def test_slug_generated_from_title_and_unique(self):
        first = make_product(self.vendor, title="Blue Bag")
        second = make_product(self.vendor, title="Blue Bag")
        self.assertEqual(first.slug, "blue-bag")
        self.assertNotEqual(first.slug, second.slug)

    def test_stock_status_follows_quantity(self):
        self.assertEqual(make_product(self.vendor, quantity=0).stock, Product.OUT_OF_STOCK)
        self.assertEqual(make_product(self.vendor, quantity=3).stock, Product.IN_STOCK)


class ServiceFeeTests(TestCase):
    def test_fee_makes_net_settlement_equal_subtotal(self):
        for subtotal in (500, 2499, 2500, 10_000, 50_000):
            fee = services.calculate_service_fee(subtotal)
            total = subtotal + fee
            flat = 100 if subtotal >= 2500 else 0
            paystack_cut = min(total * 0.015 + flat, 2000)
            self.assertGreaterEqual(total - paystack_cut, subtotal - 0.01, subtotal)

    def test_fee_is_capped(self):
        self.assertEqual(services.calculate_service_fee(5_000_000), 2000)

    def test_small_orders_skip_flat_fee(self):
        self.assertEqual(services.calculate_service_fee(1000), 16)


class ProductVisibilityTests(APITestCase):
    def setUp(self):
        self.category = make_category()
        self.selling = make_vendor()
        self.lapsed = make_vendor(
            status="trial",
            trial_start=timezone.now() - timedelta(days=40),
            trial_end=timezone.now() - timedelta(days=10),
        )

    def test_listing_hides_lapsed_vendors_sold_out_and_deleted_products(self):
        visible = make_product(self.selling, self.category, title="Visible")
        make_product(self.selling, self.category, title="Sold out", quantity=0)
        make_product(self.selling, self.category, title="Gone", status=Product.DELETED)
        make_product(self.lapsed, self.category, title="Lapsed vendor")

        response = self.client.get("/api/products/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["id"] for p in response.data["results"]], [visible.pk])
        self.assertEqual(response.data["results"][0]["quantity"], 5)

    def test_search_covers_every_page_not_just_the_first(self):
        for i in range(15):
            make_product(self.selling, self.category, title=f"Filler {i}")
        target = make_product(self.selling, self.category, title="Rechargeable lamp")
        # Push the target off the first page of the default ordering.
        Product.objects.filter(pk=target.pk).update(created_at=timezone.now() - timedelta(days=30))

        response = self.client.get("/api/products/", {"search": "lamp"})

        self.assertEqual([p["id"] for p in response.data["results"]], [target.pk])

    def test_category_filter_accepts_slug_and_id(self):
        other = make_category("books")
        book = make_product(self.selling, other, title="Novel")
        make_product(self.selling, self.category, title="Charger")
        for value in ("books", str(other.pk)):
            response = self.client.get("/api/products/", {"category": value})
            self.assertEqual([p["id"] for p in response.data["results"]], [book.pk])

    def test_hidden_product_detail_is_404_but_owner_can_view(self):
        product = make_product(self.lapsed, self.category, title="Hidden")
        url = f"/api/product/{self.category.slug}/{product.slug}/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(self.lapsed.user)
        self.assertEqual(self.client.get(url).status_code, 200)


class CartTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.product = make_product(self.vendor, quantity=3)
        self.buyer = make_user()
        self.client.force_authenticate(self.buyer)

    def add(self, product_id, quantity=1):
        return self.client.post(
            "/api/add_to_cart/", {"product_id": product_id, "quantity": quantity}, format="json"
        )

    def test_add_returns_full_cart_with_fee_and_total(self):
        response = self.add(self.product.pk, 2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subtotal"], 3000)
        self.assertEqual(response.data["total"], 3000 + services.calculate_service_fee(3000))
        self.assertTrue(response.data["can_checkout"])

    def test_cannot_exceed_available_stock(self):
        self.add(self.product.pk, 2)
        response = self.add(self.product.pk, 2)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "insufficient_stock")
        self.assertIn("error", response.data)
        self.assertEqual(CartItem.objects.get(user=self.buyer).quantity, 2)

    def test_vendor_cannot_buy_own_product(self):
        self.client.force_authenticate(self.vendor.user)
        response = self.add(self.product.pk)
        self.assertEqual(response.data["code"], "own_product")

    def test_invalid_quantity_is_a_400_not_a_500(self):
        self.assertEqual(self.add(self.product.pk, "lots").status_code, 400)

    def test_decrease_to_zero_removes_item(self):
        self.add(self.product.pk, 1)
        response = self.client.post(
            "/api/change_quantity/", {"product_id": self.product.pk, "action": "decrease"}, format="json"
        )
        self.assertEqual(response.data["items"], [])

    def test_cart_flags_items_that_became_unavailable(self):
        self.add(self.product.pk, 2)
        Product.objects.filter(pk=self.product.pk).update(quantity=1)
        response = self.client.get("/api/cart/")
        self.assertEqual(response.data["items"][0]["issue"], "insufficient_stock")
        self.assertFalse(response.data["can_checkout"])
        self.assertEqual(response.data["subtotal"], 0)


CHECKOUT = {
    "first_name": "Ada",
    "last_name": "O'Brien",
    "phone": "08031234567",
    "pickup_location": "hall_2",
}


class CheckoutTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.product = make_product(self.vendor, price=2000, quantity=4)
        self.buyer = make_user()
        self.client.force_authenticate(self.buyer)
        services.add_to_cart(self.buyer, self.product.pk, 2)

    @patch.object(paystack, "initialize_transaction")
    def test_checkout_persists_pending_order_and_charges_subtotal_plus_fee(self, init):
        init.return_value = {"authorization_url": "https://pay.example/x", "access_code": "abc"}

        response = self.client.post("/api/checkout/", CHECKOUT, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        order = Order.objects.get(ref=response.data["reference"])
        fee = services.calculate_service_fee(4000)
        self.assertEqual((order.total_cost, order.service_fee, order.is_paid), (4000, fee, False))
        self.assertEqual(init.call_args.kwargs["amount_kobo"], (4000 + fee) * 100)
        split = init.call_args.kwargs["split"]
        self.assertIn({"subaccount": self.vendor.subaccount_code, "share": 400000}, split["subaccounts"])
        self.assertTrue(init.call_args.kwargs["callback_url"].endswith("/success"))

    @patch.object(paystack, "initialize_transaction", side_effect=paystack.PaystackError("down"))
    def test_gateway_failure_marks_payment_failed_and_explains(self, _):
        response = self.client.post("/api/checkout/", CHECKOUT, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertIn("haven't been charged", response.data["error"])
        self.assertEqual(Payment.objects.get().status, Payment.FAILED)

    def test_checkout_blocked_when_cart_needs_attention(self):
        Product.objects.filter(pk=self.product.pk).update(quantity=1)
        response = self.client.post("/api/checkout/", CHECKOUT, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["problems"][0]["issue"], "insufficient_stock")
        self.assertFalse(Order.objects.exists())

    def test_invalid_details_use_the_error_contract(self):
        response = self.client.post("/api/checkout/", {**CHECKOUT, "phone": "123"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.data["fields"])
        self.assertTrue(response.data["error"])


class PaymentConfirmationTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.product = make_product(self.vendor, price=1000, quantity=5)
        self.buyer = make_user()
        services.add_to_cart(self.buyer, self.product.pk, 2)
        with patch.object(paystack, "initialize_transaction", return_value={"authorization_url": "u"}):
            self.result = services.start_checkout(self.buyer, **{**CHECKOUT, "phone": "+2348031234567"})
        self.reference = self.result["reference"]
        self.amount_kobo = self.result["total"] * 100

    def confirm(self, data):
        with patch("store.services.send_receipt_email", return_value=True) as receipt, patch(
            "store.services.send_vendor_order_notification", return_value=True
        ):
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                payment = services.confirm_order_payment(self.reference, data)
        return payment, receipt, callbacks

    def test_success_marks_paid_reduces_stock_and_clears_cart_once(self):
        payment, receipt, _ = self.confirm(paystack_success(self.reference, self.amount_kobo))
        self.assertEqual(payment.status, Payment.PAID)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 3)
        self.assertFalse(CartItem.objects.filter(user=self.buyer).exists())
        receipt.assert_called_once()

        # Webhook arriving after the redirect must not double-apply anything.
        _, receipt_again, callbacks = self.confirm(paystack_success(self.reference, self.amount_kobo))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 3)
        receipt_again.assert_not_called()
        self.assertEqual(callbacks, [])

    def test_amount_mismatch_is_not_accepted(self):
        payment, _, _ = self.confirm(paystack_success(self.reference, 100))
        self.assertEqual(payment.status, Payment.FAILED)
        self.assertFalse(Order.objects.get(ref=self.reference).is_paid)

    def test_abandoned_payment_stays_pending(self):
        payment, _, _ = self.confirm({"status": "abandoned", "reference": self.reference})
        self.assertEqual(payment.status, Payment.PENDING)

    def test_overselling_never_makes_stock_negative(self):
        Product.objects.filter(pk=self.product.pk).update(quantity=1)
        self.confirm(paystack_success(self.reference, self.amount_kobo))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 0)


class PaymentApiTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.product = make_product(self.vendor, price=1000)
        self.buyer = make_user()
        services.add_to_cart(self.buyer, self.product.pk, 1)
        with patch.object(paystack, "initialize_transaction", return_value={"authorization_url": "u"}):
            self.checkout = services.start_checkout(self.buyer, **{**CHECKOUT, "phone": "+2348031234567"})
        self.client.force_authenticate(self.buyer)

    @patch.object(paystack, "verify_transaction")
    def test_verify_reports_paid_with_order(self, verify):
        verify.return_value = paystack_success(self.checkout["reference"], self.checkout["total"] * 100)
        response = self.client.post(
            "/api/verify-payment/", {"reference": self.checkout["reference"]}, format="json"
        )
        self.assertEqual(response.data["status"], "paid")
        self.assertEqual(response.data["order"]["total"], self.checkout["total"])

    @patch.object(paystack, "verify_transaction", side_effect=paystack.PaystackError("timeout"))
    def test_verify_reports_pending_when_gateway_unreachable(self, _):
        response = self.client.post(
            "/api/verify-payment/", {"reference": self.checkout["reference"]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")

    def test_cannot_verify_someone_elses_payment(self):
        self.client.force_authenticate(make_user())
        response = self.client.post(
            "/api/verify-payment/", {"reference": self.checkout["reference"]}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_webhook_confirms_order_payment(self):
        payload = {
            "event": "charge.success",
            "data": paystack_success(self.checkout["reference"], self.checkout["total"] * 100),
        }
        with patch("store.services.send_receipt_email", return_value=True), patch(
            "store.services.send_vendor_order_notification", return_value=True
        ):
            response = signed_webhook(self.client, payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Order.objects.get(ref=self.checkout["reference"]).is_paid)

    def test_webhook_rejects_bad_signature(self):
        response = self.client.post(
            "/api/paystack_webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="nope",
        )
        self.assertEqual(response.status_code, 403)

    def test_order_history_lists_only_paid_orders(self):
        self.assertEqual(self.client.get("/api/order-history/").data["count"], 0)
        Order.objects.filter(ref=self.checkout["reference"]).update(is_paid=True, paid_at=timezone.now())
        history = self.client.get("/api/order-history/").data
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["results"][0]["items"][0]["quantity"], 1)


class ReviewTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.product = make_product(self.vendor)
        self.buyer = make_user()
        order = Order.objects.create(
            created_by=self.buyer, first_name="A", last_name="B", phone="+2348031234567",
            total_cost=1500, ref="ref-review", is_paid=True,
        )
        OrderItem.objects.create(order=order, product=self.product, price=1500, quantity=1)
        self.client.force_authenticate(self.buyer)
        self.url = f"/api/add-review/{self.product.pk}/"

    def test_public_reviews_list_with_stats(self):
        self.client.post(self.url, {"rating": 4, "text": "Good"}, format="json")
        self.client.force_authenticate(None)
        response = self.client.get(f"/api/product/{self.product.pk}/reviews/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["rating_stats"]["average_rating"], 4)

    def test_rating_must_be_between_one_and_five(self):
        self.assertEqual(self.client.post(self.url, {"rating": 9}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"rating": 0}, format="json").status_code, 400)

    def test_one_review_per_buyer(self):
        self.assertEqual(self.client.post(self.url, {"rating": 5}, format="json").status_code, 201)
        second = self.client.post(self.url, {"rating": 1}, format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(Review.objects.count(), 1)

    def test_must_have_bought_the_product(self):
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.post(self.url, {"rating": 5}, format="json").status_code, 403)

    def test_only_author_can_edit(self):
        review_id = self.client.post(self.url, {"rating": 4}, format="json").data["id"]
        self.client.force_authenticate(make_user())
        response = self.client.put(f"/api/edit-review/{review_id}/", {"rating": 1}, format="json")
        self.assertEqual(response.status_code, 404)


class VendorOrderTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor(
            status="trial",
            trial_start=timezone.now() - timedelta(days=40),
            trial_end=timezone.now() - timedelta(days=10),
        )
        self.product = make_product(self.vendor)
        buyer = make_user()
        for ref, paid in (("paid-1", True), ("unpaid-1", False)):
            order = Order.objects.create(
                created_by=buyer, first_name="A", last_name="B", phone="+2348031234567",
                total_cost=1500, ref=ref, is_paid=paid,
            )
            OrderItem.objects.create(order=order, product=self.product, price=1500, quantity=1)
        self.client.force_authenticate(self.vendor.user)

    def test_lapsed_vendor_still_sees_and_fulfils_paid_orders_only(self):
        response = self.client.get("/api/my-order/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["order_ref"] for row in response.data["results"]], ["paid-1"])

        item_id = response.data["results"][0]["id"]
        toggled = self.client.post(f"/api/toggle-fulfillment/{item_id}/", {"fulfilled": True}, format="json")
        self.assertTrue(toggled.data["fulfilled"])
        again = self.client.post(f"/api/toggle-fulfillment/{item_id}/", {"fulfilled": True}, format="json")
        self.assertTrue(again.data["fulfilled"])

    def test_cannot_fulfil_unpaid_order(self):
        unpaid = OrderItem.objects.get(order__ref="unpaid-1")
        response = self.client.post(f"/api/toggle-fulfillment/{unpaid.pk}/", {"fulfilled": True}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_lapsed_vendor_cannot_add_products(self):
        response = self.client.post("/api/add-product/", {"title": "x"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("plan", response.data["error"])

    def test_my_products_includes_sold_out_listings(self):
        make_product(self.vendor, title="Sold out", quantity=0)
        titles = {p["title"] for p in self.client.get("/api/my-products/").data["results"]}
        self.assertIn("Sold out", titles)


class ProductWriteTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor(plan=make_plan(max_products=2))
        self.client.force_authenticate(self.vendor.user)

    def test_vendor_cannot_self_feature_or_change_status(self):
        product = make_product(self.vendor)
        response = self.client.patch(
            f"/api/edit-product/{product.pk}/",
            {"featured": True, "status": "active", "price": 2500},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual((product.featured, product.price), (False, 2500))

    @patch("store.models.Product.full_clean")
    def test_description_is_optional(self, _full_clean):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from io import BytesIO
        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (10, 10), "orange").save(buffer, format="PNG")
        image = SimpleUploadedFile("p.png", buffer.getvalue(), content_type="image/png")
        def fake_upload(field, instance, add):
            # Mimic Cloudinary: upload, then store the resulting public id.
            setattr(instance, field.attname, "https://example.com/p.png")
            return "https://example.com/p.png"

        with patch("cloudinary.models.CloudinaryField.pre_save", fake_upload):
            response = self.client.post("/api/add-product/", {
                "title": "No description", "price": 1000, "quantity": 2,
                "category": make_category().pk, "product_image": image,
            })
        self.assertEqual(response.status_code, 201, response.data)

    def test_model_allows_blank_description(self):
        self.assertTrue(Product._meta.get_field("description").blank)

    def test_plan_product_limit_enforced(self):
        make_product(self.vendor)
        make_product(self.vendor)
        response = self.client.post("/api/add-product/", {"title": "Second"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "product_limit_reached")

    def test_cannot_edit_another_vendors_product(self):
        other = make_product(make_vendor())
        response = self.client.patch(f"/api/edit-product/{other.pk}/", {"price": 1}, format="json")
        self.assertEqual(response.status_code, 404)
