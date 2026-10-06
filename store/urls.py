from django.urls import path

from userprofile.webhook_api import paystack_webhook

from . import api_views

urlpatterns = [
    # Catalogue
    path("api/categories/", api_views.categories_list_api, name="categories_list_api"),
    path("api/products/", api_views.products_list_api, name="products_list_api"),
    path("api/search/", api_views.search_api, name="search_api"),
    # Must come before the category/slug detail route, which would otherwise
    # swallow "<id>/reviews/".
    path(
        "api/product/<int:pk>/reviews/",
        api_views.get_product_reviews_api,
        name="get_product_reviews_api",
    ),
    path(
        "api/product/<slug:category_slug>/<slug:slug>/",
        api_views.product_detail_api,
        name="product_detail_api",
    ),
    path("api/category/<slug:slug>/", api_views.category_detail_api, name="category_detail_api"),
    # Reviews
    path("api/add-review/<int:pk>/", api_views.add_review_api, name="add_review_api"),
    path("api/edit-review/<int:review_id>/", api_views.edit_review_api, name="edit_review_api"),
    path("api/delete-review/<int:review_id>/", api_views.delete_review_api, name="delete_review_api"),
    # Cart
    path("api/cart/", api_views.cart_view_api, name="cart_view_api"),
    path("api/add_to_cart/", api_views.api_add_to_cart, name="add_to_cart"),
    path("api/change_quantity/", api_views.api_change_quantity, name="change_quantity"),
    path("api/set_quantity/", api_views.api_set_quantity, name="set_quantity"),
    path("api/remove_from_cart/", api_views.api_remove_from_cart, name="remove_from_cart"),
    # Checkout & orders
    path("api/checkout/", api_views.checkout_api, name="checkout"),
    path("api/verify-payment/", api_views.verify_payment_api, name="verify_payment_api"),
    path("api/order-history/", api_views.order_history_api, name="order_history_api"),
    path("api/orders/<str:ref>/", api_views.buyer_order_detail_api, name="buyer_order_detail_api"),
    path("api/paystack_webhook/", paystack_webhook, name="paystack_webhook"),
    path("paystack_webhook/", paystack_webhook, name="paystack_webhook_legacy"),
    # Banking (vendor onboarding)
    path("api/banks/", api_views.get_banks_api, name="get_banks_api"),
    path("api/verify-account/", api_views.verify_account_api, name="verify_account_api"),
]
