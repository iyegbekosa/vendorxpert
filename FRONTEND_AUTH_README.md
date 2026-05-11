# Frontend Auth Integration Guide

This document describes the backend authentication contract for the frontend auth upgrade.

The backend still returns JWTs as JSON. The frontend or Next.js server layer is responsible for storing those JWTs in HttpOnly cookies and sending them back as needed.

## Overview

The auth model has three moving parts:

- `POST /api/login` authenticates email/password and returns the first token pair.
- `POST /api/token/refresh` rotates a refresh token and returns a new token pair.
- `POST /api/logout` revokes refresh tokens server-side.

Protected backend APIs require:

```http
Authorization: Bearer <access_token>
```

Recommended frontend storage model:

- Store the access token in an HttpOnly cookie.
- Store the refresh token in an HttpOnly cookie.
- Never store either token in `localStorage`.
- Next.js Middleware should read cookies server-side and protect routes.
- API calls from the browser should go through a Next.js route handler or server action that can read the HttpOnly cookies and attach the `Authorization` header.

## Token Lifetimes

Current backend settings:

- Access token TTL: 15 minutes
- Refresh token TTL: 7 days
- Refresh token rotation: enabled
- Refresh token blacklist/revocation: enabled

Every successful refresh invalidates the previous refresh token. If an old refresh token is reused, the backend treats that as suspicious reuse and revokes all outstanding refresh tokens for that user.

## Endpoint Summary

| Endpoint | Auth Required | Purpose |
| --- | --- | --- |
| `POST /api/login` | No | Authenticate email/password and return initial tokens |
| `POST /api/token/refresh` | No | Rotate refresh token and return new tokens |
| `POST /api/logout` | Yes, access token | Revoke refresh tokens server-side |

Trailing slash support:

- `/api/token/refresh` and `/api/token/refresh/` are both supported.
- `/api/logout` and `/api/logout/` are both supported.
- `/api/login` is currently defined without a trailing slash.

## Login

```http
POST /api/login
Content-Type: application/json
```

### Request

```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

### Success Response

```json
{
  "success": true,
  "user_id": 1,
  "email": "user@example.com",
  "is_vendor": false,
  "refresh": "<refresh_token>",
  "access": "<access_token>"
}
```

If the user is a vendor, the response also includes:

```json
{
  "vendor_id": 10,
  "store_details": {
    "store_name": "Example Store",
    "store_logo_url": "https://...",
    "store_description": "Store description",
    "phone_number": "+234...",
    "whatsapp_number": "+234...",
    "instagram_handle": "example",
    "tiktok_handle": "example",
    "is_verified": true,
    "subscription_status": "trial",
    "subscription_expiry": null
  }
}
```

### Error Response

```json
{
  "error": "Invalid email or password"
}
```

### Frontend Handling

The login endpoint intentionally keeps the existing response field names:

- Access token field: `access`
- Refresh token field: `refresh`

The Next.js layer should map those into HttpOnly cookies.

Recommended cookie names:

- `vendorxprt_access_token`
- `vendorxprt_refresh_token`

Recommended cookie attributes:

```ts
{
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax",
  path: "/",
}
```

Recommended cookie max ages:

- Access token cookie: 15 minutes
- Refresh token cookie: 7 days

## Refresh Token

```http
POST /api/token/refresh
Content-Type: application/json
```

### Request

```json
{
  "refresh_token": "<refresh_token>"
}
```

### Success Response

```json
{
  "access_token": "<new_access_token>",
  "refresh_token": "<new_refresh_token>"
}
```

### Error Response

Status: `401`

```json
{
  "detail": "Refresh token expired or invalid."
}
```

### Frontend Handling

On successful refresh:

- Replace the access token cookie with `access_token`.
- Replace the refresh token cookie with `refresh_token`.
- Retry the original protected request if refresh happened because of a `401`.

On refresh failure:

- Clear both auth cookies.
- Treat the user as logged out.
- Redirect to login for protected routes.

Do not retry refresh repeatedly. A single failed refresh should end the session.

## Logout

```http
POST /api/logout
Content-Type: application/json
Authorization: Bearer <access_token>
```

### Request

```json
{
  "refresh_token": "<refresh_token>"
}
```

### Success Response

```json
{
  "detail": "Logged out successfully."
}
```

### Error Response

Status: `401`

```json
{
  "detail": "Refresh token expired or invalid."
}
```

### Frontend Handling

The logout flow should:

1. Read the access token and refresh token from HttpOnly cookies in a Next.js route handler or server action.
2. Call `POST /api/logout` with the access token in the `Authorization` header and refresh token in the body.
3. Clear both cookies regardless of backend response.
4. Redirect the user to the public/login route.

The backend revokes the submitted refresh token and all outstanding refresh tokens for that user.

The access token is not stored server-side and is allowed to expire naturally.

## Protected API Requests

Protected backend endpoints require an access token:

```http
Authorization: Bearer <access_token>
```

Example:

```http
GET /api/profile/
Authorization: Bearer <access_token>
```

If the access token is expired, the backend returns `401`.

Recommended frontend flow:

1. Try the protected request with the current access token.
2. If response is `401`, call `/api/token/refresh` with the refresh token.
3. If refresh succeeds, update cookies and retry the protected request once.
4. If refresh fails, clear cookies and redirect to login.

## Vendor Feature Authorization

Some authenticated vendor endpoints also require an active vendor subscription.

Example:

```http
GET /api/vendor-kpis/
Authorization: Bearer <access_token>
```

This endpoint requires:

- A valid access token.
- The authenticated user must have a vendor profile.
- The vendor account must be verified unless the vendor is currently in a trial period.
- The vendor subscription must be active, in trial, paused, or within the configured grace period.

Important: the backend returns effective subscription fields for frontend decisions. A valid trial window can grant access even when old paid-subscription fields are stale.

For example, a vendor with a valid trial should be treated as a trial user:

```json
{
  "subscription_status": "trial",
  "subscription_expiry": "2026-05-21T13:23:00+00:00",
  "raw_subscription_status": "active",
  "raw_subscription_expiry": "2025-08-21T06:16:28.133654+00:00",
  "trial_start": "2026-05-07T13:23:00+00:00",
  "trial_end": "2026-05-21T13:23:00+00:00"
}
```

Use `subscription_status` and `subscription_expiry` for UI access decisions. The `raw_*` fields are included only for debugging/admin visibility.

Possible authorization failures:

```json
{
  "detail": "Vendor subscription has expired. Please renew to continue."
}
```

```json
{
  "detail": "Vendor account is not verified."
}
```

```json
{
  "detail": "User is not registered as a vendor."
}
```

Frontend handling:

- `401` means the access token is missing, invalid, or expired. Try refresh once.
- `403` means the user is authenticated but not allowed to access that vendor feature.
- For subscription-related `403` responses, route the user to renewal/resubscription instead of logging them out.

## Next.js Middleware Route Protection

Middleware can read HttpOnly cookies because it runs server-side.

Suggested route behavior:

- Public routes: allow when no tokens exist.
- Auth pages such as login/signup: redirect authenticated users away if a valid access token exists.
- Protected routes: require an access token cookie.
- If access token is missing but refresh token exists, call an internal Next.js refresh route that talks to the backend, updates cookies, and continues or redirects.

Important: Middleware should not expose token values to the browser.

## Suggested Next.js API Proxy Pattern

Use frontend route handlers for auth-aware backend calls:

```ts
const accessToken = cookies().get("vendorxprt_access_token")?.value;

const response = await fetch(`${BACKEND_URL}/api/profile/`, {
  headers: {
    Authorization: `Bearer ${accessToken}`,
  },
});
```

For browser requests, call your own Next.js API route instead of calling the backend directly when the request needs an HttpOnly token.

## CORS

The backend is configured for credentialed browser requests.

Allowed origins:

- `https://vendorxprt.com`
- `https://www.vendorxprt.com`
- `https://staging.vendorxprt.com`
- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://192.168.0.114:3000`

Credentialed requests are enabled:

```http
Access-Control-Allow-Credentials: true
```

Allowed methods:

```http
DELETE, GET, OPTIONS, PATCH, POST, PUT
```

Allowed headers include:

```http
Authorization, Content-Type, X-CSRFToken, X-Requested-With
```

When using browser `fetch` directly against the backend, include:

```ts
fetch(url, {
  credentials: "include",
});
```

However, if the tokens are only in HttpOnly cookies on the frontend domain, direct browser calls to the backend will not automatically add an `Authorization` header. Use a Next.js server-side proxy for protected calls unless the backend also owns the auth cookies.

## Signup And Password Reset

These flows are unchanged.

Signup:

- `POST /api/signup/`
- `POST /api/verify-signup/`
- `POST /api/resend-verification/`

Password reset:

- `POST /api/forgot-password/`
- `POST /api/verify-reset-code/`
- `POST /api/reset-password/`

These endpoints do not require authentication.

## Deployment Requirement

The backend uses SimpleJWT's blacklist tables to store outstanding and revoked refresh tokens.

Run this in every backend environment:

```bash
python manage.py migrate token_blacklist
```

Without these tables, refresh rotation and logout revocation will fail.

## Curl Examples

Login:

```bash
curl -X POST "$BACKEND_URL/api/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'
```

Refresh:

```bash
curl -X POST "$BACKEND_URL/api/token/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

Logout:

```bash
curl -X POST "$BACKEND_URL/api/logout" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"refresh_token":"<refresh_token>"}'
```

Protected profile request:

```bash
curl "$BACKEND_URL/api/profile/" \
  -H "Authorization: Bearer <access_token>"
```

## Important Notes

- `/api/login` response uses `access` and `refresh`.
- `/api/token/refresh` response uses `access_token` and `refresh_token`.
- Refresh tokens are one-time-use after rotation.
- Reusing an old refresh token revokes all outstanding refresh tokens for that user.
- Logout revokes all outstanding refresh tokens for the authenticated user.
- Access tokens are short-lived and not immediately revoked server-side.
- The backend does not set HttpOnly cookies itself.
- The frontend/Next.js layer owns cookie creation, refresh orchestration, and route protection.
