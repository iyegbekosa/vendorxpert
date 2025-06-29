from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import login
from .serializers import SignupSerializer, VendorRegisterSerializer, VendorProfileSerializer, Product, ProductSerializer, ProductCreateSerializer, VendorOrderDetailSerializer, VendorOrderItemSerializer
from .models import VendorProfile, VendorPlan
from store.utils import create_paystack_subaccount
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from store.models import OrderItem, Order, Payment
from .views import get_object_or_404
from store.pagination import StandardResultsPagination
from .permissions import can_create_product, HasActiveSubscription, VendorFeatureAccess
import requests
from django.conf import settings
import uuid
from datetime import timedelta, timezone
from django.urls import reverse
import json
import hmac
import hashlib
import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse




@api_view(['POST'])
def signup_api(request):
    serializer = SignupSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        login(request, user)
        return Response({'success': True, 'user_id': user.id}, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def register_vendor_api(request):
    serializer = VendorRegisterSerializer(data=request.data, context={'request': request})

    if serializer.is_valid():
        vendor = serializer.save()
        return Response({'success': True, 'vendor_id': vendor.id}, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def vendor_detail_api(request, pk):
    try:
        vendor = VendorProfile.objects.get(pk=pk)
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = VendorProfileSerializer(vendor)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def my_store_api(request):
    try:
        vendor_profile = request.user.vendor_profile
    except AttributeError:
        return Response({'error': 'User is not a vendor.'}, status=403)

    products = Product.objects.filter(vendor=vendor_profile).exclude(status=Product.DELETED)

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(products, request)


    serializer = ProductSerializer(result_page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
@parser_classes([MultiPartParser, FormParser])
def add_product_api(request):
    if not can_create_product(request.user):
        return Response({'detail': 'Product limit reached for your plan.'}, status=403)
    serializer = ProductCreateSerializer(data=request.data)
    if serializer.is_valid():
        product = serializer.save(vendor=request.user.vendor_profile)
        return Response({'success': True, 'product_id': product.id})
    return Response(serializer.errors, status=400)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
@parser_classes([MultiPartParser, FormParser])
def edit_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProductCreateSerializer(product, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True, 'message': 'Product updated successfully'})
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, HasActiveSubscription, VendorFeatureAccess])
def delete_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

    product.status = Product.DELETED
    product.save()
    return Response({'success': True, 'message': f'{product.title} was deleted successfully'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def vendor_order_list_api(request):
    if not hasattr(request.user, 'vendor_profile'):
        return Response({'detail': 'Only vendors can access this endpoint.'}, status=status.HTTP_403_FORBIDDEN)

    vendor = request.user.vendor_profile
    order_items = OrderItem.objects.filter(
        product__vendor=vendor
    ).select_related('order', 'product').order_by('-order__created_at')

    paginator = StandardResultsPagination()
    result_page = paginator.paginate_queryset(order_items, request)

    serializer = VendorOrderItemSerializer(result_page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def order_detail_api(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if not hasattr(request.user, 'vendor_profile'):
        return Response({'detail': 'Only vendors can access this view.'}, status=status.HTTP_403_FORBIDDEN)

    vendor = request.user.vendor_profile

    if not order.items.filter(product__vendor=vendor).exists():
        return Response({'detail': 'You are not authorized to view this order.'}, status=status.HTTP_403_FORBIDDEN)

    vendor_items = order.items.filter(product__vendor=vendor)

    serializer = VendorOrderDetailSerializer({
        'order': order,
        'items': vendor_items
    })

    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, VendorFeatureAccess])
def toggle_fulfillment_api(request, pk):
    try:
        order_item = OrderItem.objects.get(
            pk=pk,
            product__vendor=request.user.vendor_profile
        )
    except OrderItem.DoesNotExist:
        return Response({'detail': 'Order item not found or unauthorized.'}, status=status.HTTP_404_NOT_FOUND)

    if order_item.order.is_paid:
        order_item.fulfilled = not order_item.fulfilled
        order_item.save()
        return Response({'success': True, 'fulfilled': order_item.fulfilled}, status=status.HTTP_200_OK)

    return Response({'success': False, 'message': 'Order not paid.'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resubscribe_api(request):
    user = request.user

    try:
        vendor = user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=400)

    plan_id = request.data.get("plan_id")

    if not plan_id:
        return Response({"error": "Plan ID is required."}, status=400)

    try:
        selected_plan = VendorPlan.objects.get(id=plan_id, is_active=True)
    except VendorPlan.DoesNotExist:
        return Response({"error": "Invalid or inactive plan."}, status=404)

    if not selected_plan.paystack_plan_code:
        return Response({"error": "Selected plan is not linked to Paystack."}, status=400)

    ref = str(uuid.uuid4()).replace('-', '')[:20]

    callback_url = f"{request.scheme}://{request.get_host()}{reverse('paystack_callback')}"

    payload = {
        "email": user.email,
        "plan": selected_plan.paystack_plan_code,
        "reference": ref,
        "callback_url": callback_url,
    }

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers)

    try:
        res_data = response.json()
    except ValueError:
        return Response({"error": "Invalid response from Paystack"}, status=502)

    if response.status_code == 200 and res_data.get("status"):
        vendor.pending_ref = ref  
        vendor.plan = selected_plan
        vendor.save()

        return Response({
            "authorization_url": res_data["data"]["authorization_url"],
            "access_code": res_data["data"]["access_code"],
            "reference": res_data["data"]["reference"]
        }, status=200)
    else:
        return Response({"error": res_data.get("message", "Paystack error")}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_subscription_api(request):
    user = request.user

    try:
        vendor = user.vendor_profile
    except VendorProfile.DoesNotExist:
        return Response({"error": "User is not a vendor."}, status=403)

    if vendor.subscription_status == 'cancelled':
        return Response({"message": "Subscription already cancelled."}, status=400)

    subscription_code = getattr(vendor, 'paystack_subscription_code', None)
    if subscription_code:
        url = f"https://api.paystack.co/subscription/disable"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "code": subscription_code,
            "token": vendor.user.email
        }

        res = requests.post(url, json=payload, headers=headers)
        if res.status_code != 200:
            return Response({"error": "Failed to cancel subscription on Paystack"}, status=502)

    # Update vendor status
    vendor.subscription_status = 'cancelled'
    vendor.save()

    return Response({"message": "Subscription cancelled successfully."}, status=200)



logger = logging.getLogger(__name__)

@csrf_exempt
def paystack_webhook(request):
    signature = request.headers.get('x-paystack-signature')
    if not signature:
        return HttpResponse(status=400)

    payload = request.body
    computed_hash = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        payload,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, signature):
        logger.warning("Invalid Paystack signature")
        return HttpResponse(status=401)

    try:
        event_data = json.loads(payload.decode('utf-8'))
    except Exception as e:
        logger.error(f"Webhook JSON error: {e}")
        return HttpResponse(status=400)

    event = event_data.get('event')

    if event in ['charge.success', 'invoice.payment_success']:
        reference = event_data.get('data', {}).get('reference')
        subscription_code = event_data.get('data', {}).get('subscription')

        if not reference:
            logger.warning("Missing reference in webhook.")
            return HttpResponse(status=400)

        try:
            vendor = VendorProfile.objects.get(pending_ref=reference)
        except VendorProfile.DoesNotExist:
            logger.warning(f"No vendor with ref: {reference}")
            return HttpResponse(status=404)

        now = timezone.now()
        if vendor.subscription_expiry and vendor.subscription_expiry > now:
            logger.info(f"Subscription for vendor {vendor.id} already active, skipping.")
            return HttpResponse(status=200)

        if not subscription_code:
            logger.warning(f"Subscription code missing in webhook for vendor {vendor.id}")
            return HttpResponse(status=400)

        vendor.paystack_subscription_code = subscription_code
        vendor.subscription_status = 'active'
        vendor.subscription_expiry = now + timezone.timedelta(days=30)
        vendor.last_payment_date = now
        vendor.pending_ref = None
        vendor.save()

        logger.info(f"Subscription updated for vendor: {vendor.id} | New expiry: {vendor.subscription_expiry}")

    return HttpResponse(status=200)
