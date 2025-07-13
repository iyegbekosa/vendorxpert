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


def signup(request):
    if request.method == "POST":
        form = UserProfileSignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            login(request, user)
            UserProfile.objects.create(user=user)  # If you want an associated profile

            return redirect("frontpage")
    else:
        form = UserProfileSignupForm()

    return render(request, "userprofile/signup.html", {"form": form})


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
