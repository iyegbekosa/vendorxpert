# Vendor-as-Buyer Support — Backend Changes

## Overview

Users with `is_vendor: true` can now shop as buyers on the same account without restriction.
The only exceptions are self-purchase (a vendor cannot buy their own products) and self-review
(a vendor cannot review their own products).

All changes are confined to `store/api_views.py`.

---

## Changed Endpoints

### `GET /api/cart/`  —  `cart_view_api`

**Before:** No `@permission_classes` decorator (DRF default = `AllowAny`).  
**After:** `@permission_classes([IsAuthenticated])` added.

The cart is user-owned and requires authentication. Vendor accounts are not restricted.

---

### `POST /api/add_to_cart/`  —  `api_add_to_cart`

**Before:** No `@permission_classes` decorator. No vendor checks.  
**After:** Two changes:

1. `@permission_classes([IsAuthenticated])` added.
2. Self-purchase guard added — the product is fetched before adding to the cart, and if
   `product.vendor` matches `request.user.vendor_profile`, the request is rejected:

```json
HTTP 400
{ "error": "You cannot add your own product to your cart." }
```

The `Product.DoesNotExist` case is also now handled explicitly (HTTP 404).

---

### `POST /api/remove_from_cart/`  —  `api_remove_from_cart`

**Before:** No `@permission_classes` decorator.  
**After:** `@permission_classes([IsAuthenticated])` added. No change to business logic.

---

### `POST /api/change_quantity/`  —  `api_change_quantity`

**Before:** No `@permission_classes` decorator.  
**After:** `@permission_classes([IsAuthenticated])` added. No change to business logic.

---

### `POST /api/checkout/`  —  `checkout_api`

**Before:** Already `@permission_classes([IsAuthenticated])`. No vendor payout guard.  
**After:** Defensive self-purchase backstop added inside the cart-item loop that builds
`vendor_totals` for the Paystack split:

```python
buyer_vendor = getattr(request.user, "vendor_profile", None)
for item in cart:
    ...
    if buyer_vendor and product.vendor == buyer_vendor:
        logger.info(f"Payment {ref}: skipping payout for self-purchased product {product.id}")
        continue
    ...
```

When a vendor's own product is in the cart (blocked at add-to-cart, but handled here as a
safety net), the item is excluded from `vendor_totals`. The `admin_amount` formula already
covers the gap:

```
admin_amount = estimated_fee_kobo + (total_price_kobo - sum(vendor_totals.values()))
```

So the admin subaccount absorbs the proceeds for any self-purchased item. No change to
response schema or order creation.

---

### `POST /api/add-review/{product_id}/`  —  `add_review_api`

**Before:** `@permission_classes([IsAuthenticated])`. No vendor or purchase checks.  
**After:** Two guards added before the serializer runs:

**1. Self-review guard:**
```python
vendor_profile = getattr(request.user, "vendor_profile", None)
if vendor_profile and product.vendor == vendor_profile:
    # HTTP 400
    { "error": "You cannot review your own product." }
```

**2. Purchase verification:**
```python
has_purchased = Order.objects.filter(
    created_by=request.user,
    is_paid=True,
    items__product=product,
).exists()
if not has_purchased:
    # HTTP 400
    { "error": "You can only review products you have purchased." }
```

---

## Unchanged Endpoints

The following buyer-side endpoints required no changes — they already used
`@permission_classes([IsAuthenticated])` and contained no `is_vendor` filtering:

| Endpoint | View | Reason |
|---|---|---|
| `GET /api/order-history/` | `order_history_api` | Already queries `Payment.user == request.user` |
| `PUT /api/edit-review/{id}/` | `edit_review_api` | Already open to any authenticated user |
| `GET /api/profile/` | `profile_api` (auth_api.py) | Already `IsAuthenticated` only |
| `PUT /api/profile/` | `profile_api` (auth_api.py) | Already `IsAuthenticated` only |
| `POST /api/checkout/` (auth) | `checkout_api` | Was already `IsAuthenticated` |

Vendor-management endpoints (`/api/my-store/`, `/api/add-product/`, `/api/vendor-kpis/`,
etc.) are unchanged and remain restricted to `VendorFeatureAccess`.

---

## Business Rules Summary

| Rule | Enforced in |
|---|---|
| Vendor cannot add own product to cart | `api_add_to_cart` — HTTP 400 |
| Vendor cannot review own product | `add_review_api` — HTTP 400 |
| Reviewer must have a paid order for the product | `add_review_api` — HTTP 400 |
| No payout generated for self-purchased items | `checkout_api` — silent skip, admin absorbs proceeds |
| Vendor buyer-orders appear in order history | Pre-existing: `order_history_api` queries by `user`, not `is_vendor` |

---

## Files Modified

| File | Nature of change |
|---|---|
| `store/api_views.py` | Added `IsAuthenticated` to 4 cart endpoints; added self-purchase guard, self-review guard, and purchase verification |
