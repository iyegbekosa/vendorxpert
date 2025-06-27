from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import login
from .serializers import SignupSerializer, VendorRegisterSerializer, VendorProfileSerializer, Product, ProductSerializer, ProductCreateSerializer, VendorOrderDetailSerializer, VendorOrderItemSerializer
from .models import VendorProfile
from store.utils import create_paystack_subaccount
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from store.models import OrderItem, Order
from .views import get_object_or_404
from store.pagination import StandardResultsPagination



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

        try:
            create_paystack_subaccount(vendor)
        except Exception as e:
            print("Subaccount error:", e)
            return Response({'error': 'Vendor created but Paystack setup failed'}, status=500)

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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def add_product_api(request):
    serializer = ProductCreateSerializer(data=request.data)
    if serializer.is_valid():
        product = serializer.save(vendor=request.user.vendor_profile)
        return Response({'success': True, 'product_id': product.id})
    return Response(serializer.errors, status=400)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
def delete_product_api(request, pk):
    try:
        product = Product.objects.get(pk=pk, vendor=request.user.vendor_profile)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

    product.status = Product.DELETED
    product.save()
    return Response({'success': True, 'message': f'{product.title} was deleted successfully'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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

