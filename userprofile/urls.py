from django.urls import path

from . import auth_api, subscription_api, vendor_api, webhook_api

urlpatterns = [
    # Accounts
    path("api/signup/", auth_api.signup_api, name="signup_api"),
    path("api/verify-signup/", auth_api.verify_signup_api, name="verify_signup_api"),
    path("api/resend-verification/", auth_api.resend_verification_api, name="resend_verification_api"),
    path("api/forgot-password/", auth_api.forgot_password_api, name="forgot_password_api"),
    path("api/verify-reset-code/", auth_api.verify_reset_code_api, name="verify_reset_code_api"),
    path("api/reset-password/", auth_api.reset_password_api, name="reset_password_api"),
    path("api/login", auth_api.login_api, name="login_api"),
    path("api/login/", auth_api.login_api, name="login_api_slash"),
    path("api/token/refresh", auth_api.refresh_token_api, name="custom_token_refresh_api"),
    path("api/token/refresh/", auth_api.refresh_token_api, name="custom_token_refresh_api_slash"),
    path("api/logout", auth_api.logout_api, name="logout_api"),
    path("api/logout/", auth_api.logout_api, name="logout_api_slash"),
    path("api/profile/", auth_api.profile_api, name="profile_api"),
    path("api/profile/picture/", auth_api.upload_profile_picture_api, name="upload_profile_picture_api"),
    path(
        "api/profile/picture/remove/",
        auth_api.remove_profile_picture_api,
        name="remove_profile_picture_api",
    ),
    # Vendor onboarding & public storefronts
    path("api/register-vendor/", vendor_api.register_vendor_api, name="register_vendor_api"),
    path("api/vendors/", vendor_api.vendors_list_api, name="vendors_list_api"),
    path("api/vendor/<int:pk>/", vendor_api.vendor_detail_api, name="vendor_detail_api"),
    path(
        "api/vendor/<int:vendor_id>/reviews/",
        vendor_api.vendor_reviews_public_api,
        name="vendor_reviews_public_api",
    ),
    path("api/vendor-plans/", vendor_api.vendor_plans_api, name="vendor_plans_api"),
    # Vendor dashboard
    path("api/my-store/", vendor_api.my_store_api, name="my_store_api"),
    path("api/update-vendor/", vendor_api.update_vendor_api, name="update_vendor_api"),
    path("api/my-products/", vendor_api.my_products_api, name="my_products_api"),
    path("api/add-product/", vendor_api.add_product_api, name="add_product_api"),
    path("api/edit-product/<int:pk>/", vendor_api.edit_product_api, name="edit_product_api"),
    path("api/delete-product/<int:pk>/", vendor_api.delete_product_api, name="delete_product_api"),
    path("api/my-order/", vendor_api.vendor_order_list_api, name="my_order_api"),
    path("api/order/<int:pk>/", vendor_api.order_detail_api, name="order_detail_api"),
    path(
        "api/toggle-fulfillment/<int:pk>/",
        vendor_api.toggle_fulfillment_api,
        name="toggle_fulfillment_api",
    ),
    path("api/my-reviews/", vendor_api.vendor_reviews_api, name="vendor_reviews_api"),
    path("api/vendor-kpis/", vendor_api.vendor_kpis_api, name="vendor_kpis_api"),
    # Subscriptions
    path("api/my-subscription/", vendor_api.my_subscription_status_api, name="my_subscription_status_api"),
    path("api/resubscribe/", subscription_api.resubscribe_api, name="resubscribe_api"),
    path("api/change_plan/", subscription_api.change_plan_api, name="change_plan_api"),
    path(
        "api/verify-subscription-payment/",
        subscription_api.verify_subscription_payment_api,
        name="verify_subscription_payment_api",
    ),
    path("api/cancel_subscription/", subscription_api.cancel_subscription_api, name="cancel_subscription_api"),
    path(
        "api/subscription_history/",
        subscription_api.subscription_history_api,
        name="subscription_history_api",
    ),
    # Paystack sends every event for the account to a single URL; all
    # historical webhook paths route to the same handler.
    path(
        "api/paystack_subscription_webhook/",
        webhook_api.paystack_webhook,
        name="paystack_subscription_webhook",
    ),
]
