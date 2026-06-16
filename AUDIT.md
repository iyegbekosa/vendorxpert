# VendorXprt Codebase Audit

Full audit of the Django REST API codebase. Issues are grouped by severity and category.
Fixes already applied are marked **[FIXED]**.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2 |
| High | 5 |
| Medium | 23 |
| Low | 10 |
| **Total** | **40** |

---

## Critical

### 1. DEBUG = True hardcoded
- **File**: `vendorxpert/settings.py:27`
- **Issue**: `DEBUG = True` is hardcoded. In production this exposes full stack traces, settings values, and internal paths to anyone who triggers a 500 error.
- **Fix**: Use an environment variable — `DEBUG = config("DEBUG", default=False, cast=bool)`

### 2. Wildcard in ALLOWED_HOSTS **[FIXED]**
- **File**: `vendorxpert/settings.py:29-33`
- **Issue**: `"*"` in `ALLOWED_HOSTS` disables Django's Host header validation entirely, enabling Host header injection attacks.
- **Fix applied**: Replaced with explicit entries for `vendorxprt.com`, `.vendorxprt.com` (covers all subdomains), `localhost`, and `127.0.0.1`. PythonAnywhere hostnames kept.

---

## High

### 3. No rate limiting on auth endpoints
- **Files**: `userprofile/api_views.py` — `signup_api` (~line 157), `forgot_password_api` (~line 420), `login_api` (~line 868)
- **Issue**: Unlimited attempts on signup, login, and password reset. Enables brute force and credential enumeration.
- **Fix**: Add DRF throttle classes (`AnonRateThrottle`, `UserRateThrottle`) or `django-ratelimit` to these views.

### 4. Password reset token is not single-use
- **File**: `userprofile/api_views.py:560-567`
- **Issue**: The reset token is stored in `EmailVerification.payload` and the `is_used` flag is only set after a successful password change. If the link is intercepted, it can be replayed before the user acts on it.
- **Fix**: Mark the token as used (or delete the record) immediately when the reset page is loaded, not only after the password is changed.

### 5. Paystack webhook returns 401 instead of 403 on invalid signature
- **File**: `userprofile/api_views.py:3208-3221`
- **Issue**: Signature failures return HTTP 401 (Unauthorized) which implies authentication is possible. The correct code is 403 (Forbidden). Failed attempts are also not logged with enough detail to detect replay attacks.
- **Fix**: Change status to `HTTP_403_FORBIDDEN`. Add a `logger.warning` with the source IP on every failed signature check.

### 6. Missing bank account whitelist validation
- **File**: `userprofile/serializers.py:235-252`
- **Issue**: `account_number` is validated to 10 digits but `bank_code` is only checked for format, not against a whitelist of actual Nigerian bank codes. An invalid bank code will pass validation and only fail at the Paystack API call.
- **Fix**: Maintain a `VALID_BANK_CODES` set in settings or a lookup table and validate against it in the serializer.

### 7. Paystack subaccount cleanup is not reliable after Paystack succeeds
- **File**: `userprofile/serializers.py:386-472` (VendorRegisterSerializer.create)
- **Issue**: If Paystack subaccount creation succeeds but a subsequent operation fails, the manual cleanup block (`vendor.delete()`, `user.is_vendor = False`) may itself fail silently, leaving the DB and Paystack in inconsistent states.
- **Fix**: Wrap cleanup in its own try/except with explicit logging. Consider a background reconciliation job for orphaned subaccounts.

---

## Medium

### 8. No test coverage **[IN PROGRESS]**
- **Files**: `userprofile/tests.py`, `store/tests.py` — both empty
- **Issue**: Zero tests for payment logic, subscription workflows, webhooks, or any business logic.
- **Fix**: Write Django `TestCase` / `APITestCase` tests for the critical paths (see Task 4).

### 9. api_views.py is 3500+ lines
- **File**: `userprofile/api_views.py`
- **Issue**: A single file containing auth, vendor management, product management, subscriptions, and webhooks is not maintainable or testable in isolation.
- **Fix**: Split into `auth_views.py`, `vendor_views.py`, `subscription_views.py`, `webhook_views.py`.

### 10. Business logic in VendorProfile model (fat model)
- **File**: `userprofile/models.py:368-537`
- **Issue**: `change_plan_with_payment` (169 lines, makes HTTP calls) and `_update_paystack_subscription` live on the model. Models should only contain field definitions, properties, and lightweight helpers.
- **Fix**: Move to `userprofile/services.py` (Task 3 — in progress).

### 11. Business logic in views (vendor KPIs)
- **File**: `userprofile/api_views.py:2642-2745`
- **Issue**: Complex aggregation and date arithmetic for KPIs is inlined in the view function. Hard to test and reuse.
- **Fix**: Extract to a `VendorKPIService` or model method.

### 12. Broad `except Exception` blocks
- **Files**: `userprofile/api_views.py:295-296, 488-497`, `email_utils.py:55, 91, 127`, `userprofile/serializers.py:446-449`
- **Issue**: Catching `Exception` also catches `SystemExit`, `KeyboardInterrupt`, and programming errors, masking bugs.
- **Fix**: Catch specific exceptions (`requests.RequestException`, `ValidationError`, etc.).

### 13. Inconsistent error response shape
- **Files**: Throughout `userprofile/api_views.py` and `store/api_views.py`
- **Issue**: Error responses use `{"error": "..."}` in some places and `{"detail": "..."}` in others. Clients cannot reliably parse errors.
- **Fix**: Standardise on one key (recommend `"error"` for app errors, `"detail"` only for DRF-generated responses).

### 14. Wrong HTTP status codes
- **File**: `userprofile/api_views.py`
- **Examples**:
  - Line 1534: `status=403` as raw integer instead of `status.HTTP_403_FORBIDDEN`
  - Line 2002: Returns 404 for "Product not found **or unauthorized**" — should distinguish 403 from 404
  - Line 3008: Returns 400 for "Cannot pause subscription" — should be 422 Unprocessable Entity
- **Fix**: Use `status.*` constants throughout; separate auth failures from not-found errors.

### 16. Endpoints returning 202 for synchronous operations
- **File**: `userprofile/api_views.py:216, 390, 474`
- **Issue**: `signup_api`, `resend_verification_api`, and `forgot_password_api` return 202 Accepted, which means "processing in the background." Email is actually sent synchronously.
- **Fix**: Return 200 OK.

### 17. N+1 risk in vendor reviews
- **File**: `userprofile/api_views.py:2340-2361`
- **Issue**: Custom loop serialises reviews manually. If prefetching is ever changed, this silently becomes N+1.
- **Fix**: Use `ReviewDetailSerializer` with DRF's `many=True` on a properly prefetched queryset.

### 18. Incomplete transaction handling in vendor registration **[FIXED]**
- **File**: `userprofile/serializers.py` (VendorRegisterSerializer.create)
- **Issue**: Paystack call was inside the `atomic` block. A Paystack timeout would hold the DB connection open. If Paystack succeeded but the block rolled back, a subaccount would exist in Paystack with no matching DB record.
- **Fix applied**: All DB writes wrapped in `with db_transaction.atomic():`; Paystack call moved outside. Orphaned vendor detection via `subaccount_code` field on retry.

### 19. Magic numbers
- **Files**: `userprofile/api_views.py:179, 184, 3290`, `userprofile/models.py:314`, `userprofile/serializers.py:111`
- **Examples**: OTP length `6`, token expiry `timedelta(minutes=15)`, trial period `timedelta(days=14)`, max file size `5 * 1024 * 1024`
- **Fix**: Define as module-level constants (`OTP_LENGTH`, `VERIFICATION_EXPIRY_MINUTES`, etc.).

### 20. `_vendor_subscription_payload` helper not used consistently
- **File**: `userprofile/api_views.py:124-134, 920-921, 1337`
- **Issue**: Helper function exists but some call sites still inline the same logic.
- **Fix**: Replace all inline instances with the helper.

### 21. `Product.created_at` uses `auto_now` instead of `auto_now_add`
- **File**: `store/models.py:59-60`
- **Issue**: `auto_now=True` updates `created_at` on every save, making it identical to `updated_at`. Creation time is lost.
- **Fix**: Change `created_at` to `auto_now_add=True`.

### 22. Missing DB indexes on frequently-queried fields
- **File**: `store/models.py`, `userprofile/models.py`
- **Missing indexes**:
  - `Order.ref` — used in payment callback lookups
  - `OrderItem.fulfilled` — filtered in order list views
  - `Product.status` — filtered on almost every product query
- **Fix**: Add `db_index=True` to these fields.

### 23. Nullable fields that should have values after onboarding
- **File**: `userprofile/models.py`
- **Fields**: `VendorProfile.paystack_subscription_code`, `VendorProfile.subscription_expiry`, `VendorProfile.plan`
- **Issue**: These are nullable but should be set for any vendor with an active subscription. Lack of a NOT NULL constraint lets bad states exist silently.
- **Fix**: Add `null=False` with sensible defaults, or add a model-level `clean()` validation.

### 24. Deep nesting in `change_plan_with_payment`
- **File**: `userprofile/models.py:368-537`
- **Issue**: 169-line method with 4+ levels of nesting makes logic hard to follow.
- **Fix**: Extract into `_handle_upgrade`, `_handle_downgrade`, `_handle_renewal` private methods (part of service layer extraction).

### 25. Product serializer leaks method names as field names
- **File**: `store/serializers.py:24, 28`
- **Issue**: Fields named `get_thumbnail` and `get_stock_display` expose Django's method naming convention to API clients.
- **Fix**: Use `SerializerMethodField` with `source` or rename via `to_representation`.

### 26. Sensitive `subaccount_code` potentially exposed in public vendor endpoint
- **File**: `userprofile/api_views.py:1346-1354`
- **Issue**: `vendor_detail_api` has no `@permission_classes`, making it public. If `VendorSerializer` includes `subaccount_code`, this is a data leak.
- **Fix**: Audit `VendorSerializer` fields; exclude `subaccount_code`, `bank_code`, `account_number` from the public response.

### 27. `verify_signup` broad `except Exception: pass`
- **File**: `userprofile/views.py:253-254`
- **Issue**: Login failure after successful account creation is silently swallowed. User gets no feedback if auto-login fails.
- **Fix**: Log the exception at minimum; surface a message to the user if login fails.

### 28. Missing first/last name validation in CheckoutSerializer
- **File**: `store/serializers.py:80-92`
- **Issue**: `first_name` and `last_name` come from the `Order` model but have no explicit length or character validation in the serializer.
- **Fix**: Add `validate_first_name` / `validate_last_name` or explicit field declarations with constraints.

### 29. Repeated `timezone.now() + timedelta(days=X)` pattern
- **File**: `userprofile/models.py:317-318, 573-584`, `userprofile/api_views.py:3290, 3344`
- **Fix**: Extract to a helper `_subscription_expiry(days)` or constant.

### 30. `login_required` decorator used inconsistently
- **File**: `store/views.py`, `userprofile/views.py`
- **Issue**: Some vendor-only views use `@vendor_required`, others use `@login_required`, and some have no decorator.
- **Fix**: Audit all view decorators; apply `@vendor_required` wherever a vendor context is needed.

---

## Low

### 31. Missing docstrings on complex functions
- **Files**: `userprofile/models.py:368` (`change_plan_with_payment`), `userprofile/api_views.py:3253` (`handle_successful_payment`)
- **Fix**: Add a one-paragraph docstring describing the flow and key side effects.

### 32. Paystack base URL hardcoded in multiple files
- **Files**: `userprofile/api_views.py`, `userprofile/models.py`, `store/utils.py`
- **Fix**: Define `PAYSTACK_BASE_URL = "https://api.paystack.co"` in settings and import it.

### 33. Password reset minimum length inconsistency
- **File**: `userprofile/api_views.py:632`
- **Issue**: Reset flow validates `len(new_password) < 6` but signup relies on `min_length=6` in the serializer. Django's `PASSWORD_VALIDATORS` is not used in either path.
- **Fix**: Use `django.contrib.auth.password_validation.validate_password()` in both paths.

### 34. Unused import — `Product` imported twice in api_views.py
- **File**: `userprofile/api_views.py:14-15`
- **Issue**: `Product` is imported from serializers but also referenced from `store.models`.
- **Fix**: Remove the redundant import.

### 35. Duplicate vendor subscription payload inline in login response
- **File**: `userprofile/api_views.py:920-921`
- **Issue**: `_vendor_subscription_payload` helper exists but login still builds this inline.
- **Fix**: Use the helper.

### 36. Email utils use timezone-unaware `.strftime()`
- **File**: `userprofile/email_utils.py:237`
- **Issue**: Formatting a datetime without ensuring it is localised can produce UTC times in user-facing emails.
- **Fix**: Convert to the project's `TIME_ZONE` before formatting.

### 37. `Order.ref` generation could collide under load
- **File**: `store/models.py` (Order model)
- **Issue**: `ref` is generated with `uuid.uuid4()` but collision handling is not present.
- **Fix**: Add `unique=True` with a retry loop, or use `uuid4().hex` which is already UUID-collision-resistant (the existing `unique=True` DB constraint is enough — just verify it exists).

### 38. Django admin not secured for production
- **File**: `vendorxpert/urls.py`
- **Issue**: Admin is at the default `/admin/` path. Should be moved to a non-obvious path in production.
- **Fix**: Change to `path("site-admin-xprt/", admin.site.urls)` or similar.

### 39. `CartItem.__str__` is overly complex
- **File**: `store/models.py:289`
- **Issue**: `__str__` does a DB query or complex string build — these should be simple.
- **Fix**: Return something like `f"{self.quantity}x {self.product.title}"`.

### 40. `vendor_detail` (non-API) view has no 404 handling
- **File**: `userprofile/views.py:113-120`
- **Issue**: Uses `VendorProfile.objects.get(pk=pk)` directly — raises an unhandled `DoesNotExist` exception.
- **Fix**: Replace with `get_object_or_404(VendorProfile, pk=pk)`.

---

## Fixes Applied in This Session

| # | Change | File(s) |
|---|--------|---------|
| 1 | Vendor registration made atomic; orphan cleanup on retry | `userprofile/serializers.py`, `userprofile/api_views.py` |
| 2 | Product slug generated before `full_clean()` to fix blank-slug ValidationError | `store/models.py` |
| 3 | `logger` moved to module top in `userprofile/api_views.py`; duplicate definitions removed in `store/api_views.py` and `store/views.py` | `userprofile/api_views.py`, `store/api_views.py`, `store/views.py` |
| 4 | All debug `print()` statements replaced with `logger` calls or removed | `userprofile/api_views.py`, `userprofile/views.py`, `store/api_views.py`, `store/views.py`, `userprofile/models.py` |
| 5 | Phone validation extracted to `userprofile/phone_utils.py`; 3 duplicate implementations removed | `userprofile/phone_utils.py`, `userprofile/serializers.py`, `store/serializers.py` |
| 6 | Dead fake-data generators deleted (`generate_fake_categories`, `generate_fake_products`) along with `faker`/`random` imports | `store/views.py` |
| 7 | `ALLOWED_HOSTS` wildcard removed; explicit `vendorxprt.com` + `.vendorxprt.com` added | `vendorxpert/settings.py` |
| 8 | 21 root-level debug/test scripts deleted | project root |
| 9 | Dead commented-out view stubs removed (`add_to_cart`, `remove_from_cart`, `change_quantity`) | `store/views.py` |
| 10 | Unused imports cleaned up (`FileResponse`, `Decimal`, `ImageReader`, duplicate `logging`) | `store/views.py`, `store/api_views.py` |

---

## Pending Tasks

1. **Move `change_plan_with_payment` to service layer** — `userprofile/services.py`
2. **Write test suite** — cover vendor registration, phone util, product creation, subscription flows
3. **Set `DEBUG` via environment variable**
4. **Add rate limiting** to auth endpoints
5. **Standardise error response shape** across all endpoints
6. **Fix HTTP status codes** (202 → 200 for sync operations, 401 → 403 for webhook signature failure)
7. **Add DB indexes** on `Order.ref`, `OrderItem.fulfilled`, `Product.status`
8. **Fix `Product.created_at`** to use `auto_now_add=True`
9. **Audit `vendor_detail_api`** to ensure `subaccount_code`/`bank_code` not exposed publicly
10. **Split `userprofile/api_views.py`** into focused modules
