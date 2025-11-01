from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import UserProfile, VendorProfile
from .custom_dec import vendor_required
from store.models import Product, OrderItem, Order
from .forms import UserProfileSignupForm
from django.contrib.auth import login
from django.contrib import messages
from store.forms import ProductForm
from django.utils.text import slugify
from .email_utils import (
    send_welcome_email,
    send_vendor_welcome_email,
    send_verification_email,
)
from .models import EmailVerification
from django.contrib.auth.hashers import make_password
import random
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)
from store.utils import create_paystack_subaccount
from django.db import transaction
from django.views.decorators.http import require_POST


# Create your views here.


@login_required
def activate_vendor(request):
    if not request.user.is_vendor:
        # Integrate payment confirmation logic here
        request.user.is_vendor = True
        request.user.save()
    return redirect("userprofile/vendor_dashboard")


@vendor_required
def my_store(request):
    vendor_profile = request.user.vendor_profile
    product = Product.objects.filter(vendor=vendor_profile).exclude(
        status=Product.DELETED
    )

    return render(
        request,
        "userprofile/my_store.html",
        {
            "product": product,
        },
    )


@vendor_required
def add_product(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            title = request.POST.get("title")
            product = form.save(commit=False)
            product.vendor = request.user.vendor_profile
            product.save()  # Slug will be auto-generated in the model's save method
            messages.success(request, f"{title} was added successfully")

            return redirect("my_store")
    else:
        form = ProductForm()

    return render(
        request, "userprofile/product_form.html", {"form": form, "title": "Add Product"}
    )


@vendor_required
def edit_product(request, pk):
    product = Product.objects.get(vendor=request.user.vendor_profile, pk=pk)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)

        if form.is_valid():
            query = form.cleaned_data["title"]
            print(query)
            form.save()
            messages.success(request, f"{query} was changed successfully")

            return redirect("my_store")
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "userprofile/product_form.html",
        {"form": form, "title": "Edit Product", "product": product},
    )


@vendor_required
def delete_product(request, pk):
    product = Product.objects.get(vendor=request.user.vendor_profile, pk=pk)
    product.status = Product.DELETED
    product.save()
    title = product.title

    messages.success(request, f"{title} was deleted successfully")

    return redirect("my_store")


def vendor_detail(request, pk):
    user = VendorProfile.objects.get(pk=pk)
    product = Product.objects.filter(
        vendor=user, status=Product.ACTIVE, stock=Product.IN_STOCK
    )
    return render(
        request, "userprofile/vendor_detail.html", {"user": user, "product": product}
    )


@transaction.atomic
def register_vendor(request):
    if request.method == "POST":
        # Save vendor basic details
        vendor = VendorProfile.objects.create(
            user=request.user,
            store_name=request.POST["store_name"],
            account_number=request.POST["account_number"],
            bank_code=request.POST["bank_code"],
        )
        try:
            create_paystack_subaccount(
                vendor, request.POST["account_number"], request.POST["bank_code"]
            )
        except Exception as e:
            # Optional: rollback or log
            print("Subaccount error:", e)

        # Send vendor welcome email
        try:
            send_vendor_welcome_email(vendor)
            messages.success(
                request,
                f"Vendor account created successfully! Welcome email sent to {vendor.user.email}",
            )
        except Exception as e:
            logger.error(
                f"Failed to send vendor welcome email to {vendor.user.email}: {str(e)}"
            )
            messages.success(request, "Vendor account created successfully!")

        return redirect("frontpage")  # or wherever vendors should go after registration

    # Handle GET request - show registration form
    return render(request, "userprofile/register_vendor.html")


def signup(request):
    if request.method == "POST":
        form = UserProfileSignupForm(request.POST)
        if form.is_valid():
            # New flow: create verification record and send 6-digit code to email
            data = form.cleaned_data
            email = data.get("email")

            if UserProfile.objects.filter(email=email).exists():
                messages.error(request, "Email is already registered.")
                return render(request, "userprofile/signup.html", {"form": form})

            code = "".join(random.choices("0123456789", k=6))
            hashed = make_password(data.get("password"))
            expires_at = timezone.now() + timedelta(minutes=15)

            payload = {
                "user_name": data.get("user_name"),
                "first_name": data.get("first_name"),
                "last_name": data.get("last_name"),
                "password_hashed": hashed,
            }

            EmailVerification.objects.update_or_create(
                email=email,
                verification_type="signup",
                is_used=False,
                defaults={
                    "code": code,
                    "payload": payload,
                    "expires_at": expires_at,
                },
            )

            try:
                send_verification_email(email, code, expires_at=expires_at)
                messages.success(request, "Verification code sent to your email.")
            except Exception as e:
                logger.error(f"Failed to send verification email to {email}: {str(e)}")
                messages.error(request, "Could not send verification email right now.")

            # Render a simple page where user can enter the verification code
            return render(request, "userprofile/verify_signup.html", {"email": email})
    else:
        form = UserProfileSignupForm()

    return render(request, "userprofile/signup.html", {"form": form})


def verify_signup(request):
    """Handle verification code submission from web signup flow."""
    if request.method == "POST":
        email = request.POST.get("email")
        code = request.POST.get("code")

        if not email or not code:
            messages.error(request, "Email and code are required.")
            return render(request, "userprofile/verify_signup.html", {"email": email})

        try:
            ev = EmailVerification.objects.get(
                email=email, verification_type="signup", is_used=False
            )
        except EmailVerification.DoesNotExist:
            messages.error(request, "No pending verification found for this email.")
            return render(request, "userprofile/verify_signup.html", {"email": email})

        if ev.is_expired():
            messages.error(request, "Verification code has expired.")
            return render(request, "userprofile/verify_signup.html", {"email": email})

        if ev.code != code:
            messages.error(request, "Invalid verification code.")
            return render(request, "userprofile/verify_signup.html", {"email": email})

        payload = ev.payload
        if UserProfile.objects.filter(email=email).exists():
            ev.mark_used()
            messages.error(request, "Email already registered.")
            return redirect("login")

        user = UserProfile(
            user_name=payload.get("user_name"),
            email=email,
            first_name=payload.get("first_name", ""),
            last_name=payload.get("last_name", ""),
        )
        user.password = payload.get("password_hashed")
        user.save()

        ev.mark_used()

        try:
            login(request, user)
        except Exception:
            pass

        try:
            send_welcome_email(user)
        except Exception as e:
            logger.error(
                f"Failed to send welcome email after verification to {email}: {str(e)}"
            )

        messages.success(
            request, "Account created successfully. You are now logged in."
        )
        return redirect("frontpage")

    # GET: show a blank verification form
    email = request.GET.get("email")
    return render(request, "userprofile/verify_signup.html", {"email": email})


@require_POST
@login_required
def toggle_fulfillment(request, pk):
    order_item = get_object_or_404(
        OrderItem, pk=pk, product__vendor=request.user.vendor_profile
    )

    if order_item.order.is_paid:
        order_item.fulfilled = not order_item.fulfilled
        order_item.save()

    return redirect("my_orders")


@login_required
def order_list(request):
    vendor = request.user.vendor_profile
    order_items = OrderItem.objects.filter(product__vendor=vendor).select_related(
        "order", "product"
    )

    return render(request, "userprofile/order_list.html", {"order_items": order_items})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)

    return render(request, "userprofile/order_detail.html", {"order": order})
