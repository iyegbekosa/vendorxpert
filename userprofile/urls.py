from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('vendors/<int:pk>/', views.vendor_detail, name='vendor_detail'),
    path('my_orders', views.order_list, name='my_orders'),
    path('order_detail/<int:pk>/', views.order_detail, name='order_details'),
    path('toggle_fulfillment/<int:pk>/', views.toggle_fulfillment, name='toggle_fulfillment'),
    path('signup', views.signup, name='signup'),
    path('logout', auth_views.LogoutView.as_view(), name="logout"),
    path('login', auth_views.LoginView.as_view(template_name='userprofile/login.html'), name='login'),
    path('my_store', views.my_store, name='my_store'),
    path('delete/<int:pk>/', views.delete_product, name='delete'),
    path('edit_product/<int:pk>', views.edit_product, name='edit_product'),
    path('add_product', views.add_product, name='add_product'),
] 
