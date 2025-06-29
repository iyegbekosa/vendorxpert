from django.urls import path
from . import views, api_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('vendors/<int:pk>/', views.vendor_detail, name='vendor_detail'),
    path('order_detail/<int:pk>/', views.order_detail, name='order_details'),
    path('my_orders', views.order_list, name='my_orders'),
    path('toggle_fulfillment/<int:pk>/', views.toggle_fulfillment, name='toggle_fulfillment'),
    path('signup', views.signup, name='signup'),
    path('logout', auth_views.LogoutView.as_view(), name="logout"),
    path('login', auth_views.LoginView.as_view(template_name='userprofile/login.html'), name='login'),
    path('my_store', views.my_store, name='my_store'),
    path('delete/<int:pk>/', views.delete_product, name='delete'),
    path('edit_product/<int:pk>', views.edit_product, name='edit_product'),
    path('add_product', views.add_product, name='add_product'),
] 
urlpatterns += [
    path('api/signup/', api_views.signup_api, name='signup_api'),
    path('api/register-vendor/', api_views.register_vendor_api, name='register_vendor_api'),
    path('api/vendor/<int:pk>/', api_views.vendor_detail_api, name='vendor_detail_api'),
    path('api/my-store/', api_views.my_store_api, name='my_store_api'),
    path('api/add-product/', api_views.add_product_api, name='add_product_api'),
    path('api/edit-product/<int:pk>/', api_views.edit_product_api, name='edit_product_api'),
    path('api/delete-product/<int:pk>/', api_views.delete_product_api, name='delete_product_api'),
    path('api/my-order/', api_views.vendor_order_list_api, name='my_order_api'),
    path('api/order/<int:pk>/', api_views.order_detail_api, name='order_detail_api'),
    path('api/toggle-fulfillment/<int:pk>/', api_views.toggle_fulfillment_api, name='toggle_fulfillment_api'),
    path('api/resubscribe/', api_views.resubscribe_api, name='resubscribe_api'),
    path('api/cancel_subscription/', api_views.cancel_subscription_api, name='cancel_subscription_api'),
    path('api/paystack_subscription_webhook', api_views.paystack_webhook, name='paystack_subscription_webhook'),

] 