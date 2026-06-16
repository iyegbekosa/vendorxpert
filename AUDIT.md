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

### 1. DEBUG = True hardcoded **[FIXED]**
- **File**: `vendorxpert/settings.py:27`
- **Issue**: `DEBUG = True` is hardcoded. In production this exposes full stack traces, settings values, and internal paths to anyone who triggers a 500 error.
- **Fix applied**: `DEBUG = config("DEBUG", default=False, cast=bool)` — reads from `.env`.

### 2. Wildcard in ALLOWED_HOSTS **[FIXED]**
- **File**: `vendorxpert/settings.py:29-33`
- **Issue**: `"*"` in `ALLOWED_HOSTS` disables Django's Host header validation entirely, enabling Host header injection attacks.
- **Fix applied**: Replaced with explicit entries for `vendorxprt.com`, `.vendorxprt.com` (covers all subdomains), `localhost`, and `127.0.0.1`. PythonAnywhere hostnames kept.

---

## High

### 3. No rate limiting on auth endpoints **[FIXED]**
- **Files**: `userprofile/api_views.py` — `signup_api` (~line 157), `forgot_password_api` (~line 420), `login_api` (~line 868)
- **Issue**: Unlimited attempts on signup, login, and password reset. Enables brute force and credential enumeration.
- **Fix applied**: `userprofile/throttles.py` created with `SignupRateThrottle`, `LoginRateThrottle`, `PasswordResetRateThrottle` (all `AnonRateThrottle` subclasses). Rates configured in `settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` (5/hr signup, 10/hr login, 5/hr password reset). `@throttle_classes` decorator applied to all three endpoints.

### 4. Password reset token is not single-use **[FIXED]**
- **File**: `userprofile/auth_api.py`
- **Issue**: The reset token was stored in `EmailVerification.payload` and the `is_used` flag was only set after a successful password change. The OTP code itself could be replayed to obtain multiple reset tokens.
- **Fix applied**: `verify_reset_code_api` now marks `is_used=True` immediately after OTP verification (prevents OTP replay). `reset_password_api` looks up the record by `is_used=True` and deletes it after successful password change (prevents reset_token replay).

### 5. Paystack webhook returns 401 instead of 403 on invalid signature **[FIXED]**
- **File**: `userprofile/api_views.py:3208-3221`
- **Issue**: Signature failures return HTTP 401 (Unauthorized) which implies authentication is possible. The correct code is 403 (Forbidden).
- **Fix applied**: Changed to `HttpResponse(status=403)` in both `userprofile/api_views.py` and `store/api_views.py`. Signature comparison now uses `hmac.compare_digest()` (constant-time) to prevent timing attacks.

### 6. Missing bank account whitelist validation **[FIXED]**
- **File**: `userprofile/serializers.py:235-252`
- **Issue**: `account_number` is validated to 10 digits but `bank_code` is only checked for format, not against a whitelist of actual Nigerian bank codes. An invalid bank code will pass validation and only fail at the Paystack API call.
- **Fix applied**: `userprofile/bank_codes.py` created with `NIGERIAN_BANK_CODES` dict and `VALID_BANK_CODES` frozenset covering all major commercial banks, digital banks, and fintechs on Paystack. `validate_bank_code()` added to `VendorRegisterSerializer`.

### 7. Paystack subaccount cleanup is not reliable after Paystack succeeds **[FIXED]**
- **File**: `userprofile/serializers.py:386-472` (VendorRegisterSerializer.create)
- **Issue**: If Paystack subaccount creation succeeds but a subsequent operation fails, the manual cleanup block (`vendor.delete()`, `user.is_vendor = False`) may itself fail silently, leaving the DB and Paystack in inconsistent states.
- **Fix applied**: Cleanup wrapped in its own `try/except` with `logger.error` on failure. `store/utils.py` now raises `PaystackError` (custom exception class) for API-level errors instead of bare `Exception`. Serializer catches `(requests.RequestException, PaystackError)` to distinguish network vs API failures.

---

## Medium

### 8. No test coverage **[FIXED]**
- **Files**: `userprofile/tests.py`, `store/tests.py` — both empty
- **Issue**: Zero tests for payment logic, subscription workflows, webhooks, or any business logic.
- **Fix applied**: 24 tests added — `PhoneUtilsTests` (8), `VendorRegistrationAPITests` (6), `ChangePlanServiceTests` (3) in `userprofile/tests.py`; `ProductSlugTests` (7) in `store/tests.py`. All passing.

### 9. api_views.py is 3500+ lines **[FIXED]**
- **File**: `userprofile/api_views.py`
- **Issue**: A single file containing auth, vendor management, product management, subscriptions, and webhooks is not maintainable or testable in isolation.
- **Fix applied**: Split into `auth_api.py` (auth/OTP/profile), `vendor_api.py` (vendor/product/orders/reviews/KPIs), `subscription_api.py` (resubscribe/cancel/pause/resume/change-plan/history), `webhook_api.py` (Paystack webhook handlers). `api_views.py` is now a 5-line re-export shim — `urls.py` required zero changes.

### 10. Business logic in VendorProfile model (fat model) **[FIXED]**
- **File**: `userprofile/models.py:368-537`
- **Issue**: `change_plan_with_payment` (169 lines, makes HTTP calls) and `_update_paystack_subscription` live on the model. Models should only contain field definitions, properties, and lightweight helpers.
- **Fix applied**: `userprofile/services.py` created. Model methods are now thin wrappers that delegate to the service layer. All HTTP calls and business logic live in `services.py`.

### 11. Business logic in views (vendor KPIs)
- **File**: `userprofile/api_views.py:2642-2745`
- **Issue**: Complex aggregation and date arithmetic for KPIs is inlined in the view function. Hard to test and reuse.
- **Fix**: Extract to a `VendorKPIService` or model method.

### 12. Broad `except Exception` blocks **[FIXED]**
- **Files**: `userprofile/api_views.py:295-296, 488-497`, `email_utils.py:55, 91, 127`, `userprofile/serializers.py:446-449`
- **Issue**: Catching `Exception` also catches `SystemExit`, `KeyboardInterrupt`, and programming errors, masking bugs.
- **Fix applied**: `except Exception: pass` on `login()` now logs a warning. JSON decode now catches `json.JSONDecodeError`. Paystack HTTP errors catch `requests.RequestException`. SVG read errors catch `(IOError, UnicodeDecodeError)`. Logo fetch errors catch `requests.RequestException`.

### 13. Inconsistent error response shape **[FIXED]**
- **Files**: Throughout `userprofile/api_views.py` and `store/api_views.py`
- **Issue**: Error responses use `{"error": "..."}` in some places and `{"detail": "..."}` in others. Clients cannot reliably parse errors.
- **Fix applied**: All app-generated error responses standardised to `{"error": "..."}`. `{"detail": "..."}` reserved only for DRF-generated responses.

### 14. Wrong HTTP status codes
- **File**: `userprofile/api_views.py`
- **Examples**:
  - Line 1534: `status=403` as raw integer instead of `status.HTTP_403_FORBIDDEN`
  - Line 2002: Returns 404 for "Product not found **or unauthorized**" — should distinguish 403 from 404
  - Line 3008: Returns 400 for "Cannot pause subscription" — should be 422 Unprocessable Entity
- **Fix**: Use `status.*` constants throughout; separate auth failures from not-found errors.

### 16. Endpoints returning 202 for synchronous operations **[FIXED]**
- **File**: `userprofile/api_views.py:216, 390, 474`
- **Issue**: `signup_api`, `resend_verification_api`, and `forgot_password_api` return 202 Accepted, which means "processing in the background." Email is actually sent synchronously.
- **Fix applied**: All three endpoints now return `HTTP_200_OK`. Raw integer status codes replaced with `status.*` constants throughout `api_views.py`.

### 17. N+1 risk in vendor reviews
- **File**: `userprofile/api_views.py:2340-2361`
- **Issue**: Custom loop serialises reviews manually. If prefetching is ever changed, this silently becomes N+1.
- **Fix**: Use `ReviewDetailSerializer` with DRF's `many=True` on a properly prefetched queryset.

### 18. Incomplete transaction handling in vendor registration **[FIXED]**
- **File**: `userprofile/serializers.py` (VendorRegisterSerializer.create)
- **Issue**: Paystack call was inside the `atomic` block. A Paystack timeout would hold the DB connection open. If Paystack succeeded but the block rolled back, a subaccount would exist in Paystack with no matching DB record.
- **Fix applied**: All DB writes wrapped in `with db_transaction.atomic():`; Paystack call moved outside. Orphaned vendor detection via `subaccount_code` field on retry.

### 19. Magic numbers **[FIXED]**
- **Files**: `userprofile/api_views.py:179, 184, 3290`, `userprofile/models.py:314`, `userprofile/serializers.py:111`
- **Examples**: OTP length `6`, token expiry `timedelta(minutes=15)`, trial period `timedelta(days=14)`, max file size `5 * 1024 * 1024`
- **Fix applied**: `api_views.py` — `OTP_LENGTH = 6`, `OTP_EXPIRY_MINUTES = 15`, `SUBSCRIPTION_RENEWAL_DAYS = 30` at module top. `serializers.py` — `STORE_LOGO_MAX_SIZE = 5 * 1024 * 1024`, `TRIAL_PERIOD_DAYS = 30`. All inline literals replaced.

### 20. `_vendor_subscription_payload` helper not used consistently
- **File**: `userprofile/api_views.py:124-134, 920-921, 1337`
- **Issue**: Helper function exists but some call sites still inline the same logic.
- **Fix**: Replace all inline instances with the helper.

### 21. `Product.created_at` uses `auto_now` instead of `auto_now_add` **[FIXED]**
- **File**: `store/models.py:59-60`
- **Issue**: `auto_now=True` updates `created_at` on every save, making it identical to `updated_at`. Creation time is lost.
- **Fix applied**: Changed to `auto_now_add=True`. Migration `store/migrations/0016_add_indexes_fix_created_at.py` applied.

### 22. Missing DB indexes on frequently-queried fields **[FIXED]**
- **File**: `store/models.py`, `userprofile/models.py`
- **Missing indexes**:
  - `Order.ref` — used in payment callback lookups
  - `OrderItem.fulfilled` — filtered in order list views
  - `Product.status` — filtered on almost every product query
- **Fix applied**: `db_index=True` added to all three fields. Covered by migration `0016_add_indexes_fix_created_at.py`.

### 23. Nullable fields that should have values after onboarding
- **File**: `userprofile/models.py`
- **Fields**: `VendorProfile.paystack_subscription_code`, `VendorProfile.subscription_expiry`, `VendorProfile.plan`
- **Issue**: These are nullable but should be set for any vendor with an active subscription. Lack of a NOT NULL constraint lets bad states exist silently.
- **Fix**: Add `null=False` with sensible defaults, or add a model-level `clean()` validation.

### 24. Deep nesting in `change_plan_with_payment`
- **File**: `userprofile/models.py:368-537`
- **Issue**: 169-line method with 4+ levels of nesting makes logic hard to follow.
- **Fix**: Extract into `_handle_upgrade`, `_handle_downgrade`, `_handle_renewal` private methods (part of service layer extraction).

### 25. Product serializer leaks method names as field names **[FIXED]**
- **File**: `store/serializers.py:24, 28`
- **Issue**: Fields named `get_thumbnail` and `get_stock_display` expose Django's method naming convention to API clients.
- **Fix applied**: Explicit `SerializerMethodField` declarations added. Fields renamed to `thumbnail`, `stock_display`, and `display_price` (breaking change documented in `FRONTEND_CHANGES.md`).

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

### 38. Django admin not secured for production **[FIXED]**
- **File**: `vendorxpert/urls.py`
- **Issue**: Admin is at the default `/admin/` path. Should be moved to a non-obvious path in production.
- **Fix applied**: Changed to `path("xprt-admin/", admin.site.urls)`.

### 39. `CartItem.__str__` is overly complex **[FIXED]**
- **File**: `store/models.py:289`
- **Issue**: `__str__` does a DB query or complex string build — these should be simple.
- **Fix applied**: Simplified to `getattr(self.user, "user_name", None) or getattr(self.user, "email", "unknown")` — two direct attribute lookups, no fallback chain on wrong field name.

### 40. `vendor_detail` (non-API) view has no 404 handling **[FIXED]**
- **File**: `userprofile/views.py:113-120`
- **Issue**: Uses `VendorProfile.objects.get(pk=pk)` directly — raises an unhandled `DoesNotExist` exception.
- **Fix applied**: Replaced with `get_object_or_404(VendorProfile, pk=pk)`.

---

## Fixes Applied

| # | Change | File(s) |
|---|--------|---------|
| 1 | Vendor registration made atomic; orphan cleanup on retry | `userprofile/serializers.py`, `userprofile/api_views.py` |
| 2 | Product slug generated before `full_clean()` to fix blank-slug ValidationError | `store/models.py` |
| 3 | `logger` moved to module top; duplicate definitions removed | `userprofile/api_views.py`, `store/api_views.py`, `store/views.py` |
| 4 | All debug `print()` statements replaced with `logger` calls or removed | `userprofile/api_views.py`, `userprofile/views.py`, `store/api_views.py`, `store/views.py`, `userprofile/models.py` |
| 5 | Phone validation extracted to `phone_utils.py`; 3 duplicate implementations removed | `userprofile/phone_utils.py`, `userprofile/serializers.py`, `store/serializers.py` |
| 6 | Dead fake-data generators deleted along with `faker`/`random` imports | `store/views.py` |
| 7 | `ALLOWED_HOSTS` wildcard removed; explicit domain list with `.vendorxprt.com` | `vendorxpert/settings.py` |
| 8 | 21 root-level debug/test scripts deleted | project root |
| 9 | Dead commented-out view stubs removed | `store/views.py` |
| 10 | Unused imports cleaned up | `store/views.py`, `store/api_views.py` |
| 11 | `DEBUG` set via environment variable | `vendorxpert/settings.py` |
| 12 | Rate limiting added to signup, login, password reset endpoints | `userprofile/throttles.py`, `userprofile/api_views.py`, `vendorxpert/settings.py` |
| 13 | Webhook signature failures return 403; `hmac.compare_digest()` for constant-time comparison | `userprofile/api_views.py`, `store/api_views.py` |
| 14 | Nigerian bank code whitelist — `validate_bank_code()` in serializer | `userprofile/bank_codes.py`, `userprofile/serializers.py` |
| 15 | Paystack cleanup hardened — wrapped in try/except, logs orphan warnings; `PaystackError` custom exception | `store/utils.py`, `userprofile/serializers.py` |
| 16 | 24 tests added covering phone utils, vendor registration, plan changes, product slugs | `userprofile/tests.py`, `store/tests.py` |
| 17 | Business logic extracted from `VendorProfile` to `services.py` | `userprofile/services.py`, `userprofile/models.py` |
| 18 | All error responses standardised to `{"error": "..."}` | `userprofile/api_views.py` |
| 19 | 202 → 200 for synchronous endpoints; raw integer status codes → `status.*` constants | `userprofile/api_views.py` |
| 20 | `OTP_LENGTH`, `OTP_EXPIRY_MINUTES`, `SUBSCRIPTION_RENEWAL_DAYS`, `STORE_LOGO_MAX_SIZE`, `TRIAL_PERIOD_DAYS` constants defined | `userprofile/api_views.py`, `userprofile/serializers.py` |
| 21 | `Product.created_at` → `auto_now_add=True`; DB indexes on `Order.ref`, `OrderItem.fulfilled`, `Product.status` | `store/models.py`, migration `0016` |
| 22 | `vendor_detail` view uses `get_object_or_404` | `userprofile/views.py` |
| 23 | `CartItem.__str__` simplified | `store/models.py` |
| 24 | `except Exception: pass` on `login()` now logs; `json.JSONDecodeError`, `requests.RequestException`, `(IOError, UnicodeDecodeError)` catch specific errors | `userprofile/api_views.py`, `userprofile/serializers.py` |
| 25 | `api_views.py` split into `auth_api.py`, `vendor_api.py`, `subscription_api.py`, `webhook_api.py`; shim re-exports all | `userprofile/` |
| 26 | Password reset OTP now single-use (marked `is_used=True` on verify); reset_token deleted after use | `userprofile/auth_api.py` |
| 27 | Admin URL moved from `/admin/` to `/xprt-admin/` | `vendorxpert/urls.py` |
| 28 | `ProductSerializer` fields renamed to `thumbnail`, `stock_display`, `display_price` with explicit `SerializerMethodField` | `store/serializers.py` |

---

## Still Pending

- **N+1 risk in vendor reviews** (#17) — use `ReviewDetailSerializer` with prefetching instead of manual loop
- **Paystack base URL constant** (#32) — define `PAYSTACK_BASE_URL` in settings; currently hardcoded in 3+ files
- **Business logic in vendor KPI view** (#11) — extract aggregation to `VendorKPIService`
- **Missing first/last name validation in CheckoutSerializer** (#28)
- **`login_required` decorator inconsistency** (#30) — some vendor views use wrong decorator
- **Nullable subscription fields** (#23) — add `clean()` validation for `plan`/`subscription_expiry` on active vendors
