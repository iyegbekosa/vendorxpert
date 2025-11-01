# Vendor Subscription API Documentation

## Overview

The VendorXprt platform provides a subscription system that allows vendors to choose from different pricing tiers based on their business needs. Each tier offers different product limits and features.

## Available Plans

| Plan    | Price        | Max Products | Description                       |
| ------- | ------------ | ------------ | --------------------------------- |
| Basic   | ₦2,500/month | 6 products   | Starter plan for small vendors    |
| Pro     | ₦3,500/month | 15 products  | Growing business plan             |
| Premium | ₦5,000/month | 50 products  | Enterprise plan for large vendors |

## API Endpoints

### 1. List Vendor Plans

**GET** `/userprofile/api/vendor-plans/`

Get all available vendor subscription plans.

**Response:**

```json
[
  {
    "id": 1,
    "name": "basic",
    "price": 2500.0,
    "max_products": 6,
    "is_active": true
  },
  {
    "id": 2,
    "name": "pro",
    "price": 3500.0,
    "max_products": 15,
    "is_active": true
  },
  {
    "id": 3,
    "name": "premium",
    "price": 5000.0,
    "max_products": 50,
    "is_active": true
  }
]
```

### 2. Initialize/Renew Subscription

**POST** `/userprofile/api/resubscribe/`

Start a new subscription or renew/upgrade existing subscription.

**Headers:**

```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**

```json
{
  "plan_id": 2
}
```

**Response (Paid Plans):**

```json
{
  "authorization_url": "https://checkout.paystack.com/...",
  "access_code": "access_code_here",
  "reference": "payment_reference_here"
}
```

**Response (Free Plans):**

```json
{
  "message": "Successfully subscribed to free plan",
  "plan": "basic",
  "expiry": "2025-08-20T00:25:47.123456Z"
}
```

### 3. Cancel Subscription

**POST** `/userprofile/api/cancel_subscription/`

Cancel the vendor's active subscription.

**Headers:**

```
Authorization: Bearer <token>
```

**Response:**

```json
{
  "message": "Subscription cancelled successfully."
}
```

### 4. Get Vendor Store Info (includes subscription)

**GET** `/userprofile/api/my-store/`

Returns vendor profile including current subscription status.

**Headers:**

```
Authorization: Bearer <token>
```

**Response:**

```json
{
  "vendor_id": 1,
  "store_name": "My Store",
  "subscription_expiry": "2025-08-20T00:25:47.123456Z",
  "subscription_status": "active",
  "plan": {
    "name": "pro",
    "price": 3500,
    "max_products": 15
  }
}
```

### 5. Paystack Webhook (Internal)

**POST** `/userprofile/api/paystack_subscription_webhook/`

Internal webhook endpoint for Paystack payment notifications.

## Subscription Status Values

- **active** - Subscription is active and vendor has full access
- **grace** - 7-day grace period after expiry
- **defaulted** - Payment failed, limited access
- **cancelled** - User cancelled subscription

## Error Responses

### 400 Bad Request

```json
{
  "error": "Plan ID is required."
}
```

### 403 Forbidden

```json
{
  "error": "User is not a vendor."
}
```

### 404 Not Found

```json
{
  "error": "Invalid or inactive plan."
}
```

## Subscription Flow

1. **List Available Plans** - GET `/userprofile/api/vendor-plans/`
2. **Choose Plan** - Vendor selects desired plan
3. **Initialize Subscription** - POST `/userprofile/api/resubscribe/` with plan_id
4. **Complete Payment** - Vendor completes payment via Paystack URL
5. **Automatic Activation** - Webhook processes payment and activates subscription
6. **Access Features** - Vendor can now create products up to plan limits

## Integration Notes

- All subscription endpoints require authentication
- Vendor endpoints require `HasActiveSubscription` permission
- Free plans are activated immediately
- Paid plans require Paystack payment completion
- Webhooks handle automatic subscription renewal
- Grace period allows 7 days of continued access after expiry

## Swagger Documentation

All endpoints are fully documented in Swagger/OpenAPI format with:

- Request/response schemas
- Error codes and messages
- Authentication requirements
- Parameter descriptions

Access Swagger UI at: `/swagger/` when running the Django server.
