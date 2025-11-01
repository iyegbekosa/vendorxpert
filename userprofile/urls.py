from django.urls import path
from . import views, api_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),
    path("order_detail/<int:pk>/", views.order_detail, name="order_details"),
    path("my_orders", views.order_list, name="my_orders"),
    path(
        "toggle_fulfillment/<int:pk>/",
        views.toggle_fulfillment,
        name="toggle_fulfillment",
    ),
    path("signup", views.signup, name="signup"),
    path("verify-signup", views.verify_signup, name="verify_signup"),
    path("logout", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "login",
        auth_views.LoginView.as_view(template_name="userprofile/login.html"),
        name="login",
    ),
    path("my_store", views.my_store, name="my_store"),
    path("delete/<int:pk>/", views.delete_product, name="delete"),
    path("edit_product/<int:pk>", views.edit_product, name="edit_product"),
    path("add_product", views.add_product, name="add_product"),
]
urlpatterns += [
    path("api/signup/", api_views.signup_api, name="signup_api"),
    path("api/verify-signup/", api_views.verify_signup_api, name="verify_signup_api"),
    path("api/forgot-password/", api_views.forgot_password_api, name="forgot_password_api"),
    path("api/reset-password/", api_views.reset_password_api, name="reset_password_api"),
    path("api/login", api_views.login_api, name="login_api"),
    path("api/profile/", api_views.profile_api, name="profile_api"),
    path(
        "api/profile/picture/",
        api_views.upload_profile_picture_api,
        name="upload_profile_picture_api",
    ),
    path(
        "api/profile/picture/remove/",
        api_views.remove_profile_picture_api,
        name="remove_profile_picture_api",
    ),
    path(
        "api/register-vendor/",
        api_views.register_vendor_api,
        name="register_vendor_api",
    ),
    path("api/vendors/", api_views.vendors_list_api, name="vendors_list_api"),
    path("api/vendor/<int:pk>/", api_views.vendor_detail_api, name="vendor_detail_api"),
    path(
        "api/vendor/<int:vendor_id>/reviews/",
        api_views.vendor_reviews_public_api,
        name="vendor_reviews_public_api",
    ),
    path("api/my-store/", api_views.my_store_api, name="my_store_api"),
    path("api/add-product/", api_views.add_product_api, name="add_product_api"),
    path(
        "api/edit-product/<int:pk>/",
        api_views.edit_product_api,
        name="edit_product_api",
    ),
    path(
        "api/delete-product/<int:pk>/",
        api_views.delete_product_api,
        name="delete_product_api",
    ),
    path("api/my-order/", api_views.vendor_order_list_api, name="my_order_api"),
    path("api/order/<int:pk>/", api_views.order_detail_api, name="order_detail_api"),
    path("api/my-reviews/", api_views.vendor_reviews_api, name="vendor_reviews_api"),
    path(
        "api/toggle-fulfillment/<int:pk>/",
        api_views.toggle_fulfillment_api,
        name="toggle_fulfillment_api",
    ),
    path("api/vendor-plans/", api_views.vendor_plans_api, name="vendor_plans_api"),
    path("api/vendor-kpis/", api_views.vendor_kpis_api, name="vendor_kpis_api"),
    path(
        "api/my-subscription/",
        api_views.my_subscription_status_api,
        name="my_subscription_status_api",
    ),
    path("api/resubscribe/", api_views.resubscribe_api, name="resubscribe_api"),
    path(
        "api/cancel_subscription/",
        api_views.cancel_subscription_api,
        name="cancel_subscription_api",
    ),
    path(
        "api/pause_subscription/",
        api_views.pause_subscription_api,
        name="pause_subscription_api",
    ),
    path(
        "api/resume_subscription/",
        api_views.resume_subscription_api,
        name="resume_subscription_api",
    ),
    path(
        "api/change_plan/",
        api_views.change_plan_api,
        name="change_plan_api",
    ),
    path(
        "api/subscription_history/",
        api_views.subscription_history_api,
        name="subscription_history_api",
    ),
    path(
        "api/paystack_subscription_webhook/",
        api_views.paystack_webhook,
        name="paystack_subscription_webhook",
    ),
]
