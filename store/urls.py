from django.urls import path
from . import views

urlpatterns = [
    path('add_to_cart', views.api_add_to_cart, name='add_to_cart'),
    path('remove_from_cart', views.api_remove_from_cart, name='remove_from_cart'),
    path('change_quantity', views.api_change_quantity, name='change_quantity'),
    path('cart/', views.cart_view, name='cart_view'),
    path('checkout/', views.checkout, name='checkout'),
    path('receipt/', views.receipt, name='receipt'),    
    path('search/', views.search, name='search'),
    path('add_review/<int:pk>/', views.add_review_to_post, name='add_review'),
    path('delete_review/<int:review_id>/', views.delete_review, name='delete_review'),
    path('paystack_callback/', views.paystack_callback, name='paystack_callback'),
    path('paystack_webhook/', views.paystack_webhook, name='paystack_webhook'),

    path('<slug:category_slug>/<slug:slug>/', views.product_detail, name='product_detail'),
    path('<slug:slug>/', views.category_detail, name='category_detail'),
]
