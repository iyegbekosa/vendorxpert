# Frontend Integration — Breaking Changes & Implementation Notes

This document covers every API behaviour change from the recent backend audit that the frontend **must** update to handle correctly. Changes are ordered by priority.

---

## 1. Error Response Shape — Standardised to `{"error": "..."}` (Breaking)

**All** application-generated error responses now use a single key: `"error"`.

Previously the backend was inconsistent — some endpoints returned `{"detail": "..."}`, others `{"error": "..."}`. Now the rule is:

| Source | Key |
|--------|-----|
| App logic errors (400, 403, 404, 409, 500) | `"error"` |
| DRF authentication/permission failures | `"detail"` (DRF default, unchanged) |

**Action required:** Update all error-handling code to read `response.error` for app errors. Keep handling `response.detail` for 401 Unauthorized (token expired / not provided) since those still come from DRF.

**Example:**
```json
// Before (inconsistent)
{"detail": "User is already registered as a vendor"}
{"error": "User is already registered as a vendor"}

// Now (consistent)
{"error": "User is already registered as a vendor"}
```

---

## 2. HTTP Status Codes — 202 → 200 (Breaking)

Three endpoints that previously returned `202 Accepted` now return `200 OK`. They always processed synchronously, so `202` was incorrect.

| Endpoint | Method | Old | New |
|----------|--------|-----|-----|
| `POST /api/signup/` | POST | 202 | 200 |
| `POST /api/resend-verification/` | POST | 202 | 200 |
| `POST /api/forgot-password/` | POST | 202 | 200 |

**Action required:** If your code checks `response.status === 202` on these endpoints, change to `response.status === 200`.

---

## 3. Rate Limiting on Auth Endpoints (New Behaviour)

The following endpoints now enforce per-IP rate limits:

| Endpoint | Limit |
|----------|-------|
| `POST /api/signup/` | 5 requests / hour |
| `POST /api/login` | 10 requests / hour |
| `POST /api/forgot-password/` | 5 requests / hour |

**When the limit is hit**, the API returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <seconds>
```

```json
{"detail": "Request was throttled. Expected available in X seconds."}
```

**Action required:**
- Handle `429` status codes on these endpoints.
- Show a user-friendly message: e.g. _"Too many attempts. Please try again in a few minutes."_
- Optionally, read the `Retry-After` header to show a countdown.

---

## 4. Vendor Registration — Bank Code Validation (New Error)

`POST /api/register-vendor/` now validates `bank_code` against a whitelist of Nigerian bank codes before contacting Paystack.

**New error response (400):**
```json
{
  "bank_code": [
    "'999' is not a recognised Nigerian bank code. Please check your bank code and try again."
  ]
}
```

This error arrives in the serializer errors object under the `bank_code` field (same shape as other field validation errors).

**Action required:**
- Display `bank_code` validation errors on the bank code field in the registration form.
- Reference list of valid codes below for any client-side dropdown.

### Supported Nigerian Bank Codes

| Code | Bank |
|------|------|
| `044` | Access Bank |
| `063` | Access Bank (Diamond) |
| `035A` | ALAT by Wema |
| `023` | Citibank Nigeria |
| `050` | Ecobank Nigeria |
| `214` | First City Monument Bank (FCMB) |
| `011` | First Bank of Nigeria |
| `070` | Fidelity Bank |
| `058` | Guaranty Trust Bank (GTBank) |
| `030` | Heritage Bank |
| `301` | Jaiz Bank |
| `082` | Keystone Bank |
| `526` | Parallex Bank |
| `076` | Polaris Bank |
| `101` | Providus Bank |
| `221` | Stanbic IBTC Bank |
| `068` | Standard Chartered Bank |
| `232` | Sterling Bank |
| `032` | Union Bank of Nigeria |
| `033` | United Bank for Africa (UBA) |
| `215` | Unity Bank |
| `035` | Wema Bank |
| `057` | Zenith Bank |
| `304` | OPay |
| `999991` | PalmPay |
| `50515` | MoniePoint MFB |
| `90267` | Kuda Bank |
| `566` | VFD MFB (VBank) |
| `120001` | 9PSB (9 Payment Service Bank) |
| `090405` | Prospa MFB |

> The full list is maintained in `userprofile/bank_codes.py`. If you need it added as an API endpoint (`GET /api/bank-codes/`) to avoid hardcoding it in the frontend, let us know.

---

## 5. Vendor Registration — Retry After Paystack Failure (Behaviour Change)

If vendor registration fails at the Paystack step (e.g. wrong bank details), the backend now:

1. Rolls back the vendor DB record
2. Resets `is_vendor = False` on the user

This means the user can **retry the registration form** without getting _"already registered as a vendor"_ errors. Previously, a Paystack failure left a partial vendor record and blocked retries.

**No frontend change required** — but if your UX previously told users to contact support after a Paystack failure, you can now tell them to simply retry the form with corrected bank details.

---

## 6. Webhook Signature Failure — 403 not 401 (Minor)

The Paystack webhook endpoint now returns `403 Forbidden` (was `401 Unauthorized`) when the HMAC signature does not match.

This only affects internal Paystack integration — no frontend change required unless you are testing webhooks manually.

---

## 7. Vendor Trial Period — 30 Days (Behaviour Change)

New vendor registrations now start a **30-day** free trial (previously 14 days).

- `trial_start`: set at registration
- `trial_end`: 30 days after registration
- `subscription_status`: `"trial"`

**Action required:** If your UI displays trial days remaining or trial end date, recalculate using 30 days. Any hardcoded "14-day trial" copy in the frontend should be updated to "30-day trial".

---

## 8. Subscription Renewal Window — 30 Days

All subscription renewals (including trial-to-paid conversion and free plan activation) set `subscription_expiry` to **30 days** from the payment date. This was already the intended behaviour but is now enforced consistently across all code paths.

No frontend change required — just confirming the data contract.

---

## 9. Subscription State Errors — 422 not 400 (Breaking)

The following endpoints now return `422 Unprocessable Entity` instead of `400 Bad Request` when the requested operation is not valid in the current subscription state:

| Endpoint | Trigger | Old | New |
|----------|---------|-----|-----|
| `POST /api/cancel_subscription/` | Subscription already cancelled | 400 | 422 |
| `POST /api/pause_subscription/` | Cannot pause in current state | 400 | 422 |
| `POST /api/resume_subscription/` | Cannot resume in current state | 400 | 422 |

**Action required:** If your error handling differentiates 400 from other errors on these endpoints, add a `422` case. The body is still `{"error": "..."}`.

---

## 10. Password Reset — Full Password Validation (Behaviour Change)

`POST /api/reset-password/` now runs Django's full password validators (minimum length, common password check, numeric-only check) instead of only checking `len >= 6`.

**New error response (400):**
```json
{"error": ["This password is too short. It must contain at least 8 characters.", "This password is too common."]}
```

Note: `error` is now an **array of strings** on this endpoint (one message per failing validator).

**Action required:** Display all error strings, not just the first one.

---

## General Error Handling Reference

```
400 Bad Request               — Validation error; body is {"error": "..."} or {"field": ["..."]}
401 Unauthorized              — Missing/expired JWT; body is {"detail": "..."}
403 Forbidden                 — Authenticated but not allowed; body is {"error": "..."}
404 Not Found                 — Resource not found; body is {"error": "..."}
422 Unprocessable Entity      — Request valid but current state prevents it; body is {"error": "..."}
429 Too Many Requests         — Rate limit hit; handle with Retry-After header
500 Internal Server Error     — Unexpected server error; body is {"error": "An unexpected error occurred. Please try again."}
```

---

*Last updated: 2026-06-16. Backend branch: `audit/codebase-improvements`.*
