# store/api_views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from .models import Product, Category, Payment, OrderItem
from .serializers import (
    ProductSerializer,
    ReviewSerializer,
    Review,
    CartItemSerializer,
    CheckoutSerializer,
)
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .pagination import StandardResultsPagination
from userprofile.models import UserProfile
from .cart import Cart
import uuid, requests
from django.conf import settings
from collections import defaultdict
from django.urls import reverse
import hmac, hashlib, logging, json
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

logger = logging.getLogger(__name__)


@swagger_auto_schema(
    method="get",
    operation_description="Get detailed information about a specific product",
    manual_parameters=[
        openapi.Parameter(
            "category_slug",
            openapi.IN_PATH,
            description="Category slug",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "slug",
            openapi.IN_PATH,
            description="Product slug",
            type=openapi.TYPE_STRING,
        ),
    ],
    responses={
        200: ProductSerializer,
        404: openapi.Response(description="Product not found"),
    },
    tags=["Products"],
)
@api_view(["GET"])
def product_detail_api(request, category_slug, slug):
    """
    Retrieve detailed information about a specific product.

    Returns product details including title, description, price, images, etc.
    """
    product = get_object_or_404(Product, slug=slug, category__slug=category_slug)
    serializer = ProductSerializer(product)
    return Response(serializer.data, status=status.HTTP_200_OK)


@swagger_auto_schema(
    method="get",
    operation_description="Get all products in a specific category",
    manual_parameters=[
        openapi.Parameter(
            "slug",
            openapi.IN_PATH,
            description="Category slug",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Paginated list of products in the category",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                },
            ),
        ),
        404: openapi.Response(description="Category not found"),
    },
    tags=["Products"],
)
@api_view(["GET"])
def category_detail_api(request, slug):
    """
    Get all products in a specific category.

    Returns a paginated list of all active products in the specified category.
    Only products from vendors with active subscriptions are included.
    """
    category = get_object_or_404(Category, slug=slug)
    products = category.product.filter(
        status=Product.ACTIVE,
        stock=Product.IN_STOCK,
        vendor__subscription_status__in=["active", "grace"],
    )

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(products, request)

    serializer = ProductSerializer(result_page, many=True)

    return paginator.get_paginated_response(serializer.data)


@swagger_auto_schema(
    method="get",
    operation_description="Search for products by title or description",
    manual_parameters=[
        openapi.Parameter(
            "query",
            openapi.IN_QUERY,
            description="Search query string",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Paginated list of products matching the search query",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "next": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "previous": openapi.Schema(type=openapi.TYPE_STRING, nullable=True),
                    "results": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                },
            ),
        )
    },
    tags=["Products"],
)
@api_view(["GET"])
def search_api(request):
    """
    Search for products by title or description.

    Returns a paginated list of products that match the search query.
    Only active products from vendors with active subscriptions are returned.
    """
    query = request.GET.get("query", "")

    products = Product.objects.filter(
        status=Product.ACTIVE,
        stock=Product.IN_STOCK,
        vendor__subscription_status__in=["active", "grace"],
    ).filter(Q(title__icontains=query) | Q(description__icontains=query))

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(products, request)

    serializer = ProductSerializer(result_page, many=True)

    return paginator.get_paginated_response(serializer.data)


@swagger_auto_schema(
    method="post",
    operation_description="Add a review for a product",
    request_body=ReviewSerializer,
    manual_parameters=[
        openapi.Parameter(
            "pk",
            openapi.IN_PATH,
            description="Product ID",
            type=openapi.TYPE_INTEGER,
        ),
    ],
    responses={
        201: openapi.Response(
            description="Review successfully created",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                },
            ),
        ),
        400: openapi.Response(description="Validation errors"),
        401: openapi.Response(description="Authentication required"),
        404: openapi.Response(description="Product not found"),
    },
    tags=["Reviews"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_review_api(request, pk):
    """
    Add a review for a specific product.

    Requires authentication. Creates a new review for the specified product.
    """
    product = get_object_or_404(Product, pk=pk)
    serializer = ReviewSerializer(data=request.data)

    if serializer.is_valid():
        review = serializer.save(commit=False)
        user_profile = get_object_or_404(UserProfile, email=request.user.email)
        review.product = product
        review.author = user_profile
        review.save()
        return Response({"success": True}, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@swagger_auto_schema(
    method="delete",
    operation_description="Delete a review",
    manual_parameters=[
        openapi.Parameter(
            "review_id",
            openapi.IN_PATH,
            description="Review ID",
            type=openapi.TYPE_INTEGER,
        ),
    ],
    responses={
        204: openapi.Response(description="Review successfully deleted"),
        401: openapi.Response(description="Authentication required"),
        403: openapi.Response(description="Not authorized to delete this review"),
        404: openapi.Response(description="Review not found"),
    },
    tags=["Reviews"],
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_review_api(request, review_id):
    """
    Delete a specific review.

    Only the author of the review can delete it.
    """
    review = get_object_or_404(Review, id=review_id)

    if review.author != request.user:
        return Response(
            {"error": "You are not authorized to delete this review."},
            status=status.HTTP_403_FORBIDDEN,
        )

    review.delete()
    return Response(
        {"success": "Review deleted successfully."}, status=status.HTTP_204_NO_CONTENT
    )


@swagger_auto_schema(
    method="get",
    operation_description="Get current cart contents",
    responses={
        200: openapi.Response(
            description="Cart contents with items, total cost, and item count",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "cart_items": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    ),
                    "cart_total": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "cart_count": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        )
    },
    tags=["Cart"],
)
@api_view(["GET"])
def cart_view_api(request):
    """
    Get the current cart contents.

    Returns all items in the cart with their details, total cost, and item count.
    """
    cart = Cart(request)

    items = []
    for item in cart:
        items.append(
            {
                "product": {
                    "id": item["product"].id,
                    "title": item["product"].title,
                    "thumbnail": item["product"].get_thumbnail(),
                    "price": item["product"].display_price(),
                },
                "quantity": item["quantity"],
                "total_price": item["total_price"],
            }
        )

    serializer = CartItemSerializer(cart, many=True)
    return Response(
        {
            "cart_items": serializer.data,
            "cart_total": cart.get_total_cost(),
            "cart_count": len(cart),
        }
    )


@swagger_auto_schema(
    method="post",
    operation_description="Add a product to the cart",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["product_id"],
        properties={
            "product_id": openapi.Schema(
                type=openapi.TYPE_INTEGER, description="Product ID to add to cart"
            ),
            "quantity": openapi.Schema(
                type=openapi.TYPE_INTEGER,
                description="Quantity to add (default: 1)",
                default=1,
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Product successfully added to cart",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "cart_total_items": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "cart_count": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        ),
        400: openapi.Response(description="Missing product_id or invalid data"),
        500: openapi.Response(description="Internal server error"),
    },
    tags=["Cart"],
)
@api_view(["POST"])
def api_add_to_cart(request):
    """
    Add a product to the shopping cart.

    Adds the specified product with the given quantity to the cart.
    If the product already exists in the cart, updates the quantity.
    """
    product_id = request.data.get("product_id")
    quantity = request.data.get("quantity", 1)

    if not product_id:
        return Response(
            {"success": False, "error": "Missing product_id"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cart = Cart(request)
        cart.add(product_id, quantity=int(quantity), update_quantity=True)

        return Response(
            {
                "success": True,
                "cart_total_items": len(cart),
                "cart_count": len(cart),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@swagger_auto_schema(
    method="post",
    operation_description="Remove a product from the cart",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["product_id"],
        properties={
            "product_id": openapi.Schema(
                type=openapi.TYPE_INTEGER, description="Product ID to remove from cart"
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Product successfully removed from cart",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "cart_count": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        ),
        400: openapi.Response(description="Missing product_id"),
    },
    tags=["Cart"],
)
@api_view(["POST"])
def api_remove_from_cart(request):
    """
    Remove a product completely from the cart.

    Removes all quantities of the specified product from the cart.
    """
    product_id = request.data.get("product_id")

    if not product_id:
        return Response(
            {"success": False, "error": "Missing product_id"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cart = Cart(request)
    cart.remove(product_id)

    return Response(
        {"success": True, "message": "Item removed", "cart_count": len(cart)},
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Increase or decrease product quantity in cart",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["product_id", "action"],
        properties={
            "product_id": openapi.Schema(
                type=openapi.TYPE_INTEGER, description="Product ID"
            ),
            "action": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Action to perform",
                enum=["increase", "decrease"],
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Quantity successfully updated",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "message": openapi.Schema(type=openapi.TYPE_STRING),
                    "cart_count": openapi.Schema(type=openapi.TYPE_INTEGER),
                },
            ),
        ),
        400: openapi.Response(description="Invalid data provided"),
    },
    tags=["Cart"],
)
@api_view(["POST"])
def api_change_quantity(request):
    """
    Increase or decrease the quantity of a product in the cart.

    Use 'increase' to add 1 to the quantity or 'decrease' to subtract 1.
    """
    product_id = request.data.get("product_id")
    action = request.data.get("action")

    if not product_id or action not in ["increase", "decrease"]:
        return Response(
            {"success": False, "error": "Invalid data"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cart = Cart(request)
    quantity = 1 if action == "increase" else -1
    cart.add(product_id, quantity, update_quantity=True)

    return Response(
        {
            "success": True,
            "message": f"{action.title()}d item",
            "cart_count": len(cart),
        },
        status=status.HTTP_200_OK,
    )


@swagger_auto_schema(
    method="post",
    operation_description="Process checkout and initiate payment",
    request_body=CheckoutSerializer,
    responses={
        200: openapi.Response(
            description="Payment initialized successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "authorization_url": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Paystack payment URL"
                    ),
                    "access_code": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Paystack access code"
                    ),
                    "reference": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Payment reference"
                    ),
                },
            ),
        ),
        400: openapi.Response(description="Validation errors or cart is empty"),
        401: openapi.Response(description="Authentication required"),
        502: openapi.Response(description="Payment gateway error"),
    },
    tags=["Checkout"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout_api(request):
    """
    Process checkout and initiate payment with Paystack.

    Creates an order from the current cart and initiates payment processing.
    Requires authentication and a non-empty cart.
    """
    cart = Cart(request)
    user = request.user

    if len(cart) == 0:
        return Response(
            {"detail": "Cart is empty. Cannot proceed to checkout."}, status=400
        )

    serializer = CheckoutSerializer(data=request.data)
    if serializer.is_valid():
        total_price = sum(
            item["product"].price * int(item["quantity"]) for item in cart
        )

        order = serializer.save(commit=False)
        order.created_by = user
        order.total_cost = total_price
        ref = str(uuid.uuid4()).replace("-", "")[:20]
        order.ref = ref
        order.save()

        for item in cart:
            OrderItem.objects.create(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
                price=item["product"].price * int(item["quantity"]),
            )

        estimated_fee_kobo = int(min(0.015 * total_price * 100 + 10000, 200000))
        amount_kobo = int(total_price * 100) + estimated_fee_kobo

        vendor_totals = defaultdict(int)
        for item in cart:
            product = item["product"]
            quantity = int(item["quantity"])
            price_kobo = int(product.price * quantity * 100)

            subaccount_code = product.vendor.subaccount_code
            if subaccount_code:
                vendor_totals[subaccount_code] += price_kobo

        admin_subaccount = settings.ADMIN_SUBACCOUNT_CODE
        vendor_totals[admin_subaccount] += estimated_fee_kobo

        split = {
            "type": "flat",
            "bearer_type": "subaccount",
            "bearer_subaccount": admin_subaccount,
            "subaccounts": [
                {"subaccount": sub, "share": share}
                for sub, share in vendor_totals.items()
            ],
        }

        payment = Payment.objects.create(
            user=user, order=order, amount=total_price, ref=ref, status="pending"
        )

        protocol = "https" if request.is_secure() else "http"
        callback_url = (
            f"{protocol}://{request.get_host()}{reverse('paystack_callback_api')}"
        )

        if not split["subaccounts"]:
            return Response(
                {"detail": "No vendor subaccounts were found. Payment cannot proceed."},
                status=400,
            )

        payload = {
            "email": user.email,
            "amount": amount_kobo,
            "reference": payment.ref,
            "callback_url": callback_url,
            "split": split,
        }

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers,
        )

        try:
            res_data = response.json()
            payment.paystack_init_response = res_data
            payment.save()
        except ValueError:
            return Response(
                {"detail": "Paystack returned an invalid response."}, status=502
            )

        if response.status_code == 200 and res_data.get("status"):
            return Response(
                {
                    "authorization_url": res_data["data"]["authorization_url"],
                    "access_code": res_data["data"]["access_code"],
                    "reference": res_data["data"]["reference"],
                },
                status=200,
            )
        else:
            return Response(
                {"detail": res_data.get("message", "Unknown Paystack error")},
                status=400,
            )

    return Response(serializer.errors, status=400)


@swagger_auto_schema(
    method="get",
    operation_description="Handle Paystack payment callback",
    manual_parameters=[
        openapi.Parameter(
            "reference",
            openapi.IN_QUERY,
            description="Payment reference from Paystack",
            type=openapi.TYPE_STRING,
            required=True,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Payment verified successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "detail": openapi.Schema(type=openapi.TYPE_STRING),
                    "status": openapi.Schema(type=openapi.TYPE_STRING),
                },
            ),
        ),
        400: openapi.Response(description="Payment verification failed"),
        503: openapi.Response(description="Verification service error"),
    },
    tags=["Payment"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def paystack_callback_api(request):
    """
    Handle payment callback from Paystack.

    Verifies the payment status and updates the order accordingly.
    Called by Paystack after payment completion.
    """
    ref = request.GET.get("reference")
    if not ref:
        return Response({"detail": "No transaction reference provided"}, status=400)

    url = f"https://api.paystack.co/transaction/verify/{ref}"
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}

    try:
        response = requests.get(url, headers=headers)
        data = response.json()
    except Exception as e:
        return Response({"detail": f"Verification error: {str(e)}"}, status=503)

    if response.status_code != 200 or not data.get("status"):
        return Response({"detail": "Failed to verify payment"}, status=400)

    payment_data = data["data"]
    payment = get_object_or_404(Payment, ref=ref)

    if payment.status == "paid":
        return Response({"detail": "Already paid", "status": "success"}, status=200)

    if payment_data["status"] == "success":
        payment.status = "paid"
        payment.save()

        order = payment.order
        order.is_paid = True
        if hasattr(order, "status"):
            order.status = "completed"
        order.save()

        cart = Cart(request)
        cart.clear()

        return Response(
            {"detail": "Payment verified and order marked as paid"}, status=200
        )

    payment.status = "failed"
    payment.save()
    return Response({"detail": "Payment failed or was not successful"}, status=400)


@swagger_auto_schema(
    method="post",
    operation_description="Handle Paystack webhook notifications",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="Webhook payload from Paystack",
    ),
    responses={
        200: openapi.Response(description="Webhook processed successfully"),
        400: openapi.Response(description="Invalid webhook data"),
        401: openapi.Response(description="Invalid webhook signature"),
    },
    tags=["Payment"],
)
@method_decorator(csrf_exempt, name="dispatch")
@api_view(["POST"])
@permission_classes([AllowAny])
def paystack_webhook_api(request):
    """
    Handle webhook notifications from Paystack.

    Processes payment status updates sent by Paystack.
    Validates the webhook signature for security.
    """
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        logger.warning("Paystack webhook called without signature")
        return Response(status=400)

    secret_key = settings.PAYSTACK_SECRET_KEY.encode("utf-8")
    payload = request.body
    computed_hash = hmac.new(secret_key, payload, hashlib.sha512).hexdigest()

    if not hmac.compare_digest(computed_hash, signature):
        logger.warning("Invalid Paystack signature")
        return Response(status=401)

    try:
        data = json.loads(payload.decode("utf-8"))
    except ValueError as e:
        logger.error(f"Invalid JSON in Paystack webhook: {e}")
        return Response(status=400)

    event = data.get("event")
    if event == "charge.success":
        reference = data.get("data", {}).get("reference")
        if reference:
            try:
                payment = Payment.objects.get(ref=reference)
            except Payment.DoesNotExist:
                logger.error(f"No Payment found for ref {reference}")
            else:
                if payment.status != "paid":
                    payment.status = "paid"
                    payment.save()
                    order = payment.order
                    if order:
                        order.is_paid = True
                        order.status = "completed"
                        order.save()
                    logger.info(f"Payment {reference} marked as paid")
                else:
                    logger.info(f"Payment {reference} was already marked paid")

    return Response(status=200)


@swagger_auto_schema(
    method="get",
    operation_description="Get receipt for the most recent successful payment",
    responses={
        200: openapi.Response(
            description="Receipt data for the most recent payment",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "order": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "order_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "ref": openapi.Schema(type=openapi.TYPE_STRING),
                            "total_cost": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "pickup_location": openapi.Schema(type=openapi.TYPE_STRING),
                            "is_paid": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            "created_at": openapi.Schema(
                                type=openapi.TYPE_STRING, format=openapi.FORMAT_DATETIME
                            ),
                            "items": openapi.Schema(
                                type=openapi.TYPE_ARRAY,
                                items=openapi.Schema(type=openapi.TYPE_OBJECT),
                            ),
                        },
                    ),
                    "payment": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "amount": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "status": openapi.Schema(type=openapi.TYPE_STRING),
                            "ref": openapi.Schema(type=openapi.TYPE_STRING),
                            "created_at": openapi.Schema(
                                type=openapi.TYPE_STRING, format=openapi.FORMAT_DATETIME
                            ),
                        },
                    ),
                },
            ),
        ),
        401: openapi.Response(description="Authentication required"),
        404: openapi.Response(description="No recent successful payment found"),
    },
    tags=["Payment"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def receipt_api(request):
    """
    Get receipt for the most recent successful payment.

    Returns detailed information about the order and payment,
    including all order items and their fulfillment status.
    """
    try:
        payment = Payment.objects.filter(user=request.user, status="paid").latest(
            "created_at"
        )
        order = payment.order
    except Payment.DoesNotExist:
        return Response(
            {"detail": "No recent successful payment found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    order_items = order.items.all()

    order_data = {
        "order_id": order.id,
        "ref": order.ref,
        "total_cost": order.total_cost,
        "pickup_location": order.pickup_location,
        "is_paid": order.is_paid,
        "created_at": order.created_at,
        "items": [
            {
                "product_title": item.product.title,
                "quantity": item.quantity,
                "price": item.price,
                "fulfilled": item.fulfilled,
            }
            for item in order_items
        ],
    }

    payment_data = {
        "amount": payment.amount,
        "status": payment.status,
        "ref": payment.ref,
        "created_at": payment.created_at,
    }

    return Response(
        {"order": order_data, "payment": payment_data}, status=status.HTTP_200_OK
    )
