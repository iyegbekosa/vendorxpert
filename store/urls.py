from django.urls import path
from . import views
urlpatterns = [
    path('add_to_cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('remove_from_cart/<str:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('change_quantity/<str:product_id>/', views.change_quantity, name='change_quantity'),
    path('cart/', views.cart_view, name='cart_view'),
    path('checkout/', views.checkout, name='checkout'),
    path('receipt/', views.receipt, name='receipt'),    
    path('search/', views.search, name='search'),
    path('<slug:slug>/', views.category_detail, name='category_detail'),
    path('add_review/<int:pk>/', views.add_review_to_post, name='add_review'),
    path('<slug:category_slug>/<slug:slug>/', views.product_detail, name='product_detail'),
    path('delete_review/<int:review_id>/', views.delete_review, name='delete_review'),
]