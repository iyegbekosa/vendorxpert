from django.urls import path
from . import views, api_views

urlpatterns = [
    path("add_to_cart", views.api_add_to_cart, name="add_to_cart"),
    path("remove_from_cart", views.api_remove_from_cart, name="remove_from_cart"),
    path("change_quantity", views.api_change_quantity, name="change_quantity"),
    path("cart/", views.cart_view, name="cart_view"),
    path("checkout/", views.checkout, name="checkout"),
    path("receipt/", views.receipt, name="receipt"),
    path("search/", views.search, name="search"),
    path("add_review/<int:pk>/", views.add_review_to_post, name="add_review"),
    path("delete_review/<int:review_id>/", views.delete_review, name="delete_review"),
    path("paystack_callback/", views.paystack_callback, name="paystack_callback"),
    path("paystack_webhook/", views.paystack_webhook, name="paystack_webhook"),
    path(
        "store/<slug:category_slug>/<slug:slug>/",
        views.product_detail,
        name="product_detail",
    ),
    path("store/<slug:slug>/", views.category_detail, name="category_detail"),
]

urlpatterns += [
    path("api/categories/", api_views.categories_list_api, name="categories_list_api"),
    path("api/products/", api_views.products_list_api, name="products_list_api"),
    path(
        "api/product/<slug:category_slug>/<slug:slug>/",
        api_views.product_detail_api,
        name="product_detail_api",
    ),
    path(
        "api/category/<slug:slug>/",
        api_views.category_detail_api,
        name="category_detail_api",
    ),
    path("api/search/", api_views.search_api, name="search_api"),
    path("api/add-review/<int:pk>/", api_views.add_review_api, name="add_review_api"),
    path(
        "api/delete-review/<int:review_id>/",
        api_views.delete_review_api,
        name="delete_review_api",
    ),
    path("api/cart/", api_views.cart_view_api, name="cart_view_api"),
    path("api/add_to_cart/", api_views.api_add_to_cart, name="add_to_cart"),
    path(
        "api/remove_from_cart/", api_views.api_remove_from_cart, name="remove_from_cart"
    ),
    path("api/change_quantity/", api_views.api_change_quantity, name="change_quantity"),
    path(
        "api/clear_cart/",
        api_views.clear_cart_after_payment_api,
        name="clear_cart_after_payment_api",
    ),
    path("api/checkout/", api_views.checkout_api, name="checkout"),
    path("api/receipt/", api_views.receipt_api, name="receipt_api"),
    path(
        "api/paystack/callback/",
        api_views.paystack_callback_api,
        name="paystack_callback_api",
    ),
    path(
        "api/paystack_webhook/", api_views.paystack_webhook_api, name="paystack_webhook"
    ),
]
