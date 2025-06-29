# store/api_views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from .models import Product, Category, Payment, OrderItem
from .serializers import ProductSerializer, ReviewSerializer, Review, CartItemSerializer, CheckoutSerializer
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
logger = logging.getLogger(__name__)




@api_view(['GET'])
def product_detail_api(request, category_slug, slug):
    product = get_object_or_404(Product, slug=slug, category__slug=category_slug)
    serializer = ProductSerializer(product)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
def category_detail_api(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = category.product.filter(status=Product.ACTIVE, stock=Product.IN_STOCK, vendor__subscription_status__in=['active', 'grace'])

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(products, request)

    serializer = ProductSerializer(result_page, many=True)

    return paginator.get_paginated_response(serializer.data)

@api_view(['GET'])
def search_api(request):
    query = request.GET.get('query', '')

    products = Product.objects.filter(
        status=Product.ACTIVE,
        stock=Product.IN_STOCK,
        vendor__subscription_status__in=['active', 'grace']
    ).filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    )

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(products, request)

    serializer = ProductSerializer(result_page, many=True)

    return paginator.get_paginated_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_review_api(request, pk):
    product = get_object_or_404(Product, pk=pk)
    serializer = ReviewSerializer(data=request.data)

    if serializer.is_valid():
        review = serializer.save(commit=False)
        user_profile = get_object_or_404(UserProfile, email=request.user.email)
        review.product = product
        review.author = user_profile
        review.save()
        return Response({'success': True}, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_review_api(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    if review.author != request.user:
        return Response({'error': 'You are not authorized to delete this review.'}, status=status.HTTP_403_FORBIDDEN)

    review.delete()
    return Response({'success': 'Review deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
def cart_view_api(request):
    cart = Cart(request)

    items = []
    for item in cart:
        items.append({
            'product': {
                'id': item['product'].id,
                'title': item['product'].title,
                'thumbnail': item['product'].get_thumbnail(),
                'price': item['product'].display_price(),
            },
            'quantity': item['quantity'],
            'total_price': item['total_price']
        })

    serializer = CartItemSerializer(cart, many=True)
    return Response({
        'cart_items': serializer.data,
        'cart_total': cart.get_total_cost(),
        'cart_count': len(cart)
    })


@api_view(['POST'])
def api_add_to_cart(request):
    product_id = request.data.get('product_id')
    quantity = request.data.get('quantity', 1)

    if not product_id:
        return Response({'success': False, 'error': 'Missing product_id'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        cart = Cart(request)
        cart.add(product_id, quantity=int(quantity), update_quantity=True)

        return Response({
            'success': True,
            'cart_total_items': len(cart),
            'cart_count': len(cart),
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['POST'])
def api_remove_from_cart(request):
    product_id = request.data.get('product_id')

    if not product_id:
        return Response({'success': False, 'error': 'Missing product_id'}, status=status.HTTP_400_BAD_REQUEST)

    cart = Cart(request)
    cart.remove(product_id)

    return Response({
        'success': True,
        'message': 'Item removed',
        'cart_count': len(cart)
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def api_change_quantity(request):
    product_id = request.data.get('product_id')
    action = request.data.get('action')

    if not product_id or action not in ['increase', 'decrease']:
        return Response({'success': False, 'error': 'Invalid data'}, status=status.HTTP_400_BAD_REQUEST)

    cart = Cart(request)
    quantity = 1 if action == 'increase' else -1
    cart.add(product_id, quantity, update_quantity=True)

    return Response({
        'success': True,
        'message': f'{action.title()}d item',
        'cart_count': len(cart)
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def checkout_api(request):
    cart = Cart(request)
    user = request.user

    if len(cart) == 0:
        return Response({"detail": "Cart is empty. Cannot proceed to checkout."}, status=400)

    serializer = CheckoutSerializer(data=request.data)
    if serializer.is_valid():
        total_price = sum(item['product'].price * int(item['quantity']) for item in cart)

        order = serializer.save(commit=False)
        order.created_by = user
        order.total_cost = total_price
        ref = str(uuid.uuid4()).replace('-', '')[:20]
        order.ref = ref
        order.save()


        for item in cart:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                price=item['product'].price * int(item['quantity'])
            )

        estimated_fee_kobo = int(min(0.015 * total_price * 100 + 10000, 200000))
        amount_kobo = int(total_price * 100) + estimated_fee_kobo

        vendor_totals = defaultdict(int)
        for item in cart:
            product = item['product']
            quantity = int(item['quantity'])
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
            ]
        }

        payment = Payment.objects.create(
            user=user,
            order=order,
            amount=total_price,
            ref=ref,
            status='pending'
        )

        protocol = 'https' if request.is_secure() else 'http'
        callback_url = f"{protocol}://{request.get_host()}{reverse('paystack_callback_api')}"

        if not split["subaccounts"]:
            return Response({"detail": "No vendor subaccounts were found. Payment cannot proceed."}, status=400)

        payload = {
            "email": user.email,
            "amount": amount_kobo,
            "reference": payment.ref,
            "callback_url": callback_url,
            "split": split
        }

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers)

        try:
            res_data = response.json()
            payment.paystack_init_response = res_data
            payment.save()
        except ValueError:
            return Response({"detail": "Paystack returned an invalid response."}, status=502)

        if response.status_code == 200 and res_data.get("status"):
            return Response({
                "authorization_url": res_data["data"]["authorization_url"],
                "access_code": res_data["data"]["access_code"],
                "reference": res_data["data"]["reference"]
            }, status=200)
        else:
            return Response({"detail": res_data.get("message", "Unknown Paystack error")}, status=400)

    return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([AllowAny])
def paystack_callback_api(request):
    ref = request.GET.get('reference')
    if not ref:
        return Response({"detail": "No transaction reference provided"}, status=400)

    url = f"https://api.paystack.co/transaction/verify/{ref}"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
    }

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
        if hasattr(order, 'status'):
            order.status = "completed"
        order.save()

        cart = Cart(request)
        cart.clear()

        return Response({"detail": "Payment verified and order marked as paid"}, status=200)
    
    payment.status = "failed"
    payment.save()
    return Response({"detail": "Payment failed or was not successful"}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
@api_view(['POST'])
@permission_classes([AllowAny])
def paystack_webhook_api(request):
    signature = request.headers.get('x-paystack-signature')
    if not signature:
        logger.warning("Paystack webhook called without signature")
        return Response(status=400)

    secret_key = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    payload = request.body
    computed_hash = hmac.new(secret_key, payload, hashlib.sha512).hexdigest()

    if not hmac.compare_digest(computed_hash, signature):
        logger.warning("Invalid Paystack signature")
        return Response(status=401)

    try:
        data = json.loads(payload.decode('utf-8'))
    except ValueError as e:
        logger.error(f"Invalid JSON in Paystack webhook: {e}")
        return Response(status=400)

    event = data.get('event')
    if event == 'charge.success':
        reference = data.get('data', {}).get('reference')
        if reference:
            try:
                payment = Payment.objects.get(ref=reference)
            except Payment.DoesNotExist:
                logger.error(f"No Payment found for ref {reference}")
            else:
                if payment.status != 'paid':
                    payment.status = 'paid'
                    payment.save()
                    order = payment.order
                    if order:
                        order.is_paid = True
                        order.status = 'completed'
                        order.save()
                    logger.info(f"Payment {reference} marked as paid")
                else:
                    logger.info(f"Payment {reference} was already marked paid")

    return Response(status=200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def receipt_api(request):
    try:
        payment = Payment.objects.filter(user=request.user, status='paid').latest('created_at')
        order = payment.order
    except Payment.DoesNotExist:
        return Response({"detail": "No recent successful payment found."}, status=status.HTTP_404_NOT_FOUND)

    order_items = order.items.all()

    order_data = {
        'order_id': order.id,
        'ref': order.ref,
        'total_cost': order.total_cost,
        'pickup_location': order.pickup_location,
        'is_paid': order.is_paid,
        'created_at': order.created_at,
        'items': [
            {
                'product_title': item.product.title,
                'quantity': item.quantity,
                'price': item.price,
                'fulfilled': item.fulfilled,
            } for item in order_items
        ]
    }

    payment_data = {
        'amount': payment.amount,
        'status': payment.status,
        'ref': payment.ref,
        'created_at': payment.created_at,
    }

    return Response({
        'order': order_data,
        'payment': payment_data
    }, status=status.HTTP_200_OK)