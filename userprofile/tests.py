from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APITestCase

from store import paystack
from store.utils import PaystackError
from vendorxpert.testing import make_plan, make_user, make_vendor, signed_webhook

from . import services
from .models import EmailVerification, SubscriptionHistory, UserProfile, VendorProfile, selling_access_q
from .phone_utils import normalize_and_validate_nigerian_phone


class PhoneUtilsTests(TestCase):
    def test_local_and_international_formats_normalise(self):
        for raw in ("09012345678", "+2349012345678", "090 1234 5678", "090-1234-5678"):
            self.assertEqual(normalize_and_validate_nigerian_phone(raw), "+2349012345678")

    def test_invalid_numbers_rejected(self):
        for raw in ("0901234567", "090123456789", "not-a-phone"):
            with self.assertRaises(serializers.ValidationError):
                normalize_and_validate_nigerian_phone(raw)


class SellingAccessTests(TestCase):
    """``has_selling_access`` and ``selling_access_q`` must always agree."""

    def test_python_and_database_rules_match(self):
        now = timezone.now()
        scenarios = {
            "trial_running": dict(status="trial", trial_start=now - timedelta(days=1), trial_end=now + timedelta(days=5)),
            "trial_over": dict(status="trial", trial_start=now - timedelta(days=40), trial_end=now - timedelta(days=1)),
            "active": dict(status="active", subscription_expiry=now + timedelta(days=3)),
            "in_grace": dict(status="active", subscription_expiry=now - timedelta(days=3)),
            "lapsed": dict(status="active", subscription_expiry=now - timedelta(days=30)),
            "cancelled_paid_up": dict(status="cancelled", subscription_expiry=now + timedelta(days=3)),
            "cancelled_over": dict(status="cancelled", subscription_expiry=now - timedelta(days=1)),
            "defaulted": dict(status="defaulted", subscription_expiry=now - timedelta(days=1)),
        }
        expected = {"trial_running", "active", "in_grace", "cancelled_paid_up"}
        vendors = {name: make_vendor(**kwargs) for name, kwargs in scenarios.items()}

        in_db = set(VendorProfile.objects.filter(selling_access_q()).values_list("pk", flat=True))
        for name, vendor in vendors.items():
            self.assertEqual(vendor.has_selling_access(), name in expected, name)
            self.assertEqual(vendor.pk in in_db, name in expected, name)


@patch("userprofile.auth_api.send_verification_email", return_value=True)
class SignupFlowTests(APITestCase):
    payload = {
        "user_name": "ada",
        "email": "Ada@Example.com",
        "first_name": "Ada",
        "last_name": "Obi",
        "password": "Campus-market-42",
    }

    def test_signup_normalises_email_and_verification_signs_in(self, _):
        response = self.client.post("/api/signup/", self.payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        code = EmailVerification.objects.get(email="ada@example.com").code

        with patch("userprofile.auth_api.send_welcome_email", return_value=True):
            response = self.client.post(
                "/api/verify-signup/", {"email": "ADA@example.com", "code": code}, format="json"
            )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("access", response.data)
        self.assertTrue(UserProfile.objects.filter(email="ada@example.com").exists())

    def test_weak_password_rejected(self, _):
        response = self.client.post("/api/signup/", {**self.payload, "password": "12345678"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data["fields"])

    def test_code_locks_after_too_many_wrong_attempts(self, _):
        self.client.post("/api/signup/", self.payload, format="json")
        verification = EmailVerification.objects.get(email="ada@example.com")
        wrong = "000000" if verification.code != "000000" else "111111"
        for _attempt in range(EmailVerification.MAX_ATTEMPTS):
            self.client.post("/api/verify-signup/", {"email": "ada@example.com", "code": wrong}, format="json")

        response = self.client.post(
            "/api/verify-signup/", {"email": "ada@example.com", "code": verification.code}, format="json"
        )
        self.assertEqual(response.data["code"], "code_locked")
        self.assertFalse(UserProfile.objects.filter(email="ada@example.com").exists())

    def test_email_failure_is_reported_not_hidden(self, send):
        send.return_value = False
        response = self.client.post("/api/signup/", self.payload, format="json")
        self.assertEqual(response.status_code, 503)


class LoginAndResetTests(APITestCase):
    def setUp(self):
        self.user = make_user(email="kemi@example.com")

    def test_login_is_case_insensitive(self):
        response = self.client.post(
            "/api/login", {"email": "KEMI@example.com", "password": "Str0ng-pass-123"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_vendor"])

    def test_wrong_password_uses_error_contract(self):
        response = self.client.post("/api/login", {"email": "kemi@example.com", "password": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_credentials")

    @patch("userprofile.auth_api.send_password_reset_email", return_value=True)
    def test_forgot_password_does_not_reveal_accounts(self, send):
        known = self.client.post("/api/forgot-password/", {"email": "kemi@example.com"}, format="json")
        unknown = self.client.post("/api/forgot-password/", {"email": "nobody@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)
        send.assert_called_once()

    @patch("userprofile.auth_api.send_password_reset_email", return_value=True)
    def test_full_reset_flow_revokes_old_sessions(self, _):
        login = self.client.post(
            "/api/login", {"email": "kemi@example.com", "password": "Str0ng-pass-123"}, format="json"
        )
        old_refresh = login.data["refresh"]

        self.client.post("/api/forgot-password/", {"email": "kemi@example.com"}, format="json")
        code = EmailVerification.objects.get(email="kemi@example.com").code
        token = self.client.post(
            "/api/verify-reset-code/", {"email": "kemi@example.com", "code": code}, format="json"
        ).data["reset_token"]
        response = self.client.post(
            "/api/reset-password/",
            {"email": "kemi@example.com", "reset_token": token, "new_password": "New-campus-pass-9"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        refresh = self.client.post("/api/token/refresh/", {"refresh_token": old_refresh}, format="json")
        self.assertEqual(refresh.status_code, 401)
        replay = self.client.post(
            "/api/reset-password/",
            {"email": "kemi@example.com", "reset_token": token, "new_password": "Another-pass-77"},
            format="json",
        )
        self.assertEqual(replay.status_code, 400)

    def test_token_obtain_endpoint_that_bypassed_throttling_is_gone(self):
        response = self.client.post("/api/token/", {"email": "kemi@example.com", "password": "x"})
        self.assertEqual(response.status_code, 404)


VENDOR_POST_DATA = {
    "store_name": "Test Store",
    "account_number": "1234567890",
    "bank_code": "044",
    "phone_number": "09012345678",
}


@patch("userprofile.vendor_api.send_vendor_welcome_email", return_value=True)
class VendorRegistrationTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        make_plan()
        self.client.force_authenticate(self.user)

    @patch("userprofile.serializers.create_paystack_subaccount", return_value="ACCT_x")
    def test_registration_starts_trial(self, *_):
        response = self.client.post("/api/register-vendor/", VENDOR_POST_DATA, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        vendor = VendorProfile.objects.get(user=self.user)
        self.assertTrue(vendor.has_active_trial())
        self.assertEqual(response.data["store_details"]["subscription_status"], "trial")

    @patch("userprofile.serializers.create_paystack_subaccount", side_effect=PaystackError("bad"))
    def test_paystack_failure_leaves_no_half_created_store(self, *_):
        response = self.client.post("/api/register-vendor/", VENDOR_POST_DATA, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("account_number", response.data["fields"])
        self.assertFalse(VendorProfile.objects.filter(user=self.user).exists())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_vendor)

    def test_logo_url_is_not_fetched_server_side(self, _):
        with patch("userprofile.serializers.create_paystack_subaccount", return_value="ACCT_x"):
            self.client.post(
                "/api/register-vendor/",
                {**VENDOR_POST_DATA, "store_logo": "http://169.254.169.254/latest/meta-data"},
                format="json",
            )
        # The test runner blocks outbound HTTP, so reaching this line means no
        # fetch was attempted; the URL must also never become the logo.
        vendor = VendorProfile.objects.filter(user=self.user).first()
        self.assertTrue(vendor is None or not vendor.store_logo)

    def test_existing_vendor_gets_conflict(self, _):
        make_vendor(user=self.user)
        response = self.client.post("/api/register-vendor/", VENDOR_POST_DATA, format="json")
        self.assertEqual(response.status_code, 409)


class SubscriptionTests(TestCase):
    def setUp(self):
        self.basic = make_plan("basic", 3000, 6, "PLN_basic")
        self.premium = make_plan("premium", 5000, 12, "PLN_premium")
        self.vendor = make_vendor(plan=self.basic)

    @patch.object(paystack, "initialize_transaction", return_value={"authorization_url": "u"})
    def test_starting_payment_does_not_grant_the_plan(self, _):
        result = services.start_subscription_payment(self.vendor, self.premium)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.plan, self.basic)
        self.assertEqual(self.vendor.pending_ref, result["reference"])

    def subscription_charge(self, reference, plan, amount=None, **extra):
        return {
            "status": "success",
            "reference": reference,
            "amount": (amount if amount is not None else plan.price) * 100,
            "metadata": {"type": "subscription", "vendor_id": self.vendor.pk, "plan_id": plan.pk},
            "customer": {"email": self.vendor.user.email, "customer_code": "CUS_1"},
            "authorization": {"authorization_code": "AUTH_1", "reusable": True},
            **extra,
        }

    def test_payment_activates_after_trial_without_losing_trial_days(self):
        trial_end = self.vendor.trial_end
        self.vendor.pending_ref = "sub-1"
        self.vendor.save()

        services.apply_subscription_transaction(self.subscription_charge("sub-1", self.premium))
        services.apply_subscription_transaction(self.subscription_charge("sub-1", self.premium))

        self.vendor.refresh_from_db()
        self.assertEqual((self.vendor.plan, self.vendor.subscription_status), (self.premium, "active"))
        self.assertEqual(self.vendor.subscription_expiry, trial_end + timedelta(days=30))
        self.assertEqual(self.vendor.paystack_authorization_code, "AUTH_1")
        self.assertEqual(
            SubscriptionHistory.objects.filter(payment_reference="sub-1", event_type="payment_success").count(), 1
        )

    def test_underpayment_is_rejected(self):
        services.apply_subscription_transaction(self.subscription_charge("sub-2", self.premium, amount=10))
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.subscription_status, "trial")

    def test_recurring_renewal_found_by_subscription_code(self):
        expiry = timezone.now() + timedelta(days=1)
        VendorProfile.objects.filter(pk=self.vendor.pk).update(
            subscription_status="active", subscription_expiry=expiry, paystack_subscription_code="SUB_1"
        )
        services.apply_subscription_transaction(
            {
                "status": "success",
                "reference": "renewal-1",
                "amount": 300000,
                "subscription": {"subscription_code": "SUB_1"},
                "plan": {"plan_code": "PLN_basic"},
            }
        )
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.subscription_expiry, expiry + timedelta(days=30))

    @patch.object(paystack, "fetch_subscription", return_value={"email_token": "tok_1"})
    @patch.object(paystack, "disable_subscription")
    def test_cancel_uses_paystack_email_token_and_keeps_access(self, disable, _):
        VendorProfile.objects.filter(pk=self.vendor.pk).update(
            subscription_status="active",
            subscription_expiry=timezone.now() + timedelta(days=10),
            paystack_subscription_code="SUB_1",
        )
        self.vendor.refresh_from_db()
        services.cancel_subscription(self.vendor)
        disable.assert_called_once_with("SUB_1", "tok_1")
        self.assertTrue(self.vendor.has_selling_access())

    @patch.object(paystack, "create_subscription", return_value={"subscription_code": "SUB_2", "email_token": "t2"})
    @patch.object(paystack, "disable_subscription")
    def test_downgrade_is_scheduled_for_next_billing_date(self, disable, create):
        VendorProfile.objects.filter(pk=self.vendor.pk).update(
            plan=self.premium,
            subscription_status="active",
            subscription_expiry=timezone.now() + timedelta(days=10),
            paystack_subscription_code="SUB_1",
            subscription_token="t1",
            paystack_customer_code="CUS_1",
            paystack_authorization_code="AUTH_1",
        )
        self.vendor.refresh_from_db()

        result = services.change_plan(self.vendor, self.basic)

        self.assertEqual(result["payment_status"], "scheduled")
        self.vendor.refresh_from_db()
        self.assertEqual((self.vendor.plan, self.vendor.scheduled_plan), (self.premium, self.basic))
        create.assert_called_once()
        disable.assert_called_once_with("SUB_1", "t1")

    def test_subscription_webhook_applies_payment(self):
        self.vendor.pending_ref = "sub-3"
        self.vendor.save()
        response = signed_webhook(
            self.client,
            {"event": "charge.success", "data": self.subscription_charge("sub-3", self.basic)},
            path="/api/paystack_subscription_webhook/",
        )
        self.assertEqual(response.status_code, 200)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.subscription_status, "active")

    def test_unknown_webhook_events_are_acknowledged(self):
        response = signed_webhook(self.client, {"event": "transfer.success", "data": {}})
        self.assertEqual(response.status_code, 200)


class SubscriptionApiTests(APITestCase):
    def setUp(self):
        self.vendor = make_vendor(plan=make_plan())
        self.client.force_authenticate(self.vendor.user)

    @patch.object(paystack, "verify_transaction")
    def test_verify_rejects_references_the_vendor_does_not_own(self, verify):
        response = self.client.post(
            "/api/verify-subscription-payment/", {"reference": "someone-elses"}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        verify.assert_not_called()

    def test_buyers_cannot_use_vendor_billing(self):
        self.client.force_authenticate(make_user())
        response = self.client.get("/api/my-subscription/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.data["error"])
