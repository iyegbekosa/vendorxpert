from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from rest_framework import serializers
from rest_framework.test import APITestCase
from rest_framework import status

from .models import UserProfile, VendorProfile, VendorPlan, SubscriptionHistory
from .phone_utils import normalize_and_validate_nigerian_phone
from store.utils import PaystackError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email="test@example.com", username="testuser"):
    return UserProfile.objects.create_user(
        email=email,
        user_name=username,
        first_name="Test",
        last_name="User",
        password="strongpass123",
    )


def make_basic_plan():
    return VendorPlan.objects.create(
        name=VendorPlan.BASIC,
        price=2000,
        is_active=True,
        description="Basic plan",
    )


# ---------------------------------------------------------------------------
# Phone utility
# ---------------------------------------------------------------------------

class PhoneUtilsTests(TestCase):
    """Unit tests for normalize_and_validate_nigerian_phone."""

    def test_local_11_digit_converted_to_international(self):
        result = normalize_and_validate_nigerian_phone("09012345678")
        self.assertEqual(result, "+2349012345678")

    def test_international_format_accepted_unchanged(self):
        result = normalize_and_validate_nigerian_phone("+2349012345678")
        self.assertEqual(result, "+2349012345678")

    def test_spaces_stripped_before_validation(self):
        result = normalize_and_validate_nigerian_phone("090 1234 5678")
        self.assertEqual(result, "+2349012345678")

    def test_dashes_stripped_before_validation(self):
        result = normalize_and_validate_nigerian_phone("090-1234-5678")
        self.assertEqual(result, "+2349012345678")

    def test_too_short_raises_validation_error(self):
        with self.assertRaises(serializers.ValidationError):
            normalize_and_validate_nigerian_phone("0901234567")  # 10 digits (one short)

    def test_too_long_raises_validation_error(self):
        with self.assertRaises(serializers.ValidationError):
            normalize_and_validate_nigerian_phone("090123456789")  # 12 digits (one long)

    def test_non_numeric_raises_validation_error(self):
        with self.assertRaises(serializers.ValidationError):
            normalize_and_validate_nigerian_phone("not-a-phone-number")

    def test_custom_field_label_appears_in_error_message(self):
        try:
            normalize_and_validate_nigerian_phone("bad", "WhatsApp number")
            self.fail("Expected ValidationError")
        except serializers.ValidationError as exc:
            self.assertIn("WhatsApp number", str(exc.detail))


# ---------------------------------------------------------------------------
# Vendor registration API
# ---------------------------------------------------------------------------

VENDOR_POST_DATA = {
    "store_name": "Test Store",
    "account_number": "1234567890",
    "bank_code": "044",
    "phone_number": "09012345678",
    "whatsapp_number": "09012345679",
}


class VendorRegistrationAPITests(APITestCase):
    """Integration tests for POST /api/register-vendor/."""

    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.plan = make_basic_plan()
        self.url = "/api/register-vendor/"

    @patch("userprofile.serializers.create_paystack_subaccount")
    @patch("userprofile.api_views.send_vendor_welcome_email")
    def test_happy_path_creates_vendor_profile(self, mock_email, mock_paystack):
        mock_paystack.return_value = {"subaccount_code": "ACCT_testcode"}
        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["success"])
        self.assertTrue(UserProfile.objects.get(pk=self.user.pk).is_vendor)
        self.assertTrue(VendorProfile.objects.filter(user=self.user).exists())

    def test_unauthenticated_request_rejected(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("userprofile.serializers.create_paystack_subaccount")
    @patch("userprofile.api_views.send_vendor_welcome_email")
    def test_already_registered_with_subaccount_returns_400(self, mock_email, mock_paystack):
        # Create a fully-registered vendor (has subaccount_code).
        VendorProfile.objects.create(
            user=self.user,
            store_name="Existing Store",
            store_description="Desc",
            subaccount_code="ACCT_existing",
        )
        self.user.is_vendor = True
        self.user.save()

        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already registered", str(resp.data).lower())

    @patch("userprofile.serializers.create_paystack_subaccount")
    @patch("userprofile.api_views.send_vendor_welcome_email")
    def test_orphaned_vendor_cleaned_up_and_retry_succeeds(self, mock_email, mock_paystack):
        # Simulate a previous failed registration: VendorProfile exists but
        # subaccount_code is NULL (Paystack setup never completed).
        VendorProfile.objects.create(
            user=self.user,
            store_name="Orphaned Store",
            store_description="Desc",
            subaccount_code=None,
        )
        mock_paystack.return_value = {"subaccount_code": "ACCT_new"}

        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # Only one VendorProfile should exist (the new one, not the orphan).
        self.assertEqual(VendorProfile.objects.filter(user=self.user).count(), 1)

    @patch("userprofile.serializers.create_paystack_subaccount")
    @patch("userprofile.api_views.send_vendor_welcome_email")
    def test_paystack_failure_rolls_back_vendor_creation(self, mock_email, mock_paystack):
        mock_paystack.side_effect = PaystackError("Bank account not found")

        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")

        # View catches DRFValidationError from serializer and returns 400.
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # VendorProfile must have been deleted and is_vendor reset.
        self.assertFalse(VendorProfile.objects.filter(user=self.user).exists())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_vendor)

    @patch("userprofile.serializers.create_paystack_subaccount")
    @patch("userprofile.api_views.send_vendor_welcome_email")
    def test_duplicate_phone_number_from_registered_vendor_blocked(self, mock_email, mock_paystack):
        # Another user with a fully-registered vendor profile using the same phone.
        other_user = make_user("other@example.com", "otheruser")
        VendorProfile.objects.create(
            user=other_user,
            store_name="Other Store",
            store_description="Desc",
            phone_number="+2349012345678",
            subaccount_code="ACCT_other",  # fully registered
        )

        resp = self.client.post(self.url, VENDOR_POST_DATA, format="json")

        self.assertIn(resp.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ])


# ---------------------------------------------------------------------------
# Subscription service layer
# ---------------------------------------------------------------------------

class ChangePlanServiceTests(TestCase):
    """Unit tests for userprofile.services.change_plan_with_payment."""

    def setUp(self):
        self.user = make_user()
        self.basic_plan = make_basic_plan()
        self.pro_plan = VendorPlan.objects.create(
            name=VendorPlan.PRO,
            price=5000,
            is_active=True,
            paystack_plan_code="PLN_pro",
        )
        self.vendor = VendorProfile.objects.create(
            user=self.user,
            store_name="My Store",
            store_description="Great store",
            plan=self.basic_plan,
            subscription_status="active",
            subscription_expiry=timezone.now() + timedelta(days=20),
        )

    def test_same_plan_returns_error(self):
        from .services import change_plan_with_payment
        result = change_plan_with_payment(self.vendor, self.basic_plan)
        self.assertFalse(result["success"])
        self.assertIn("already on this plan", result["error"])

    def test_downgrade_applied_immediately_without_payment(self):
        from .services import change_plan_with_payment

        free_plan = VendorPlan.objects.create(
            name=VendorPlan.FREE, price=0, is_active=True
        )
        # Downgrade: new plan is cheaper, no payment required.
        result = change_plan_with_payment(self.vendor, free_plan)

        self.assertTrue(result["success"])
        self.assertEqual(result["payment_status"], "completed")
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.plan, free_plan)

    @patch("userprofile.services.requests.post")
    def test_trial_upgrade_initialises_paystack_payment(self, mock_post):
        from .services import change_plan_with_payment

        self.vendor.subscription_status = "trial"
        self.vendor.save()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "data": {"authorization_url": "https://paystack.com/pay/test"},
        }
        mock_post.return_value = mock_response

        mock_request = MagicMock()
        mock_request.scheme = "https"
        mock_request.get_host.return_value = "api.vendorxprt.com"

        result = change_plan_with_payment(
            self.vendor, self.pro_plan, request=mock_request
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["payment_status"], "payment_required")
        self.assertIn("authorization_url", result)
        mock_post.assert_called_once()
