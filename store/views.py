from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import FileResponse, JsonResponse, HttpResponse
from .models import Product, Category, Review, OrderItem, Order, Payment
from .forms import ReviewForm
from userprofile.models import VendorProfile, UserProfile
from faker import Faker
import random
from .cart import Cart
from .forms import OrderForm
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.conf import settings
from django.urls import reverse
from decimal import Decimal
import requests
import io
import os
from collections import defaultdict
import json, logging, hmac, hashlib
from django.views.decorators.http import require_POST
import uuid

fake = Faker()
logger = logging.getLogger(__name__)


def product_detail(request, category_slug, slug):
    product = get_object_or_404(Product, slug=slug, category__slug=category_slug)
    return render(request, "store/product_detail.html", {"product": product})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    product = category.product.filter(status=Product.ACTIVE, stock=Product.IN_STOCK)
    return render(
        request,
        "store/category_detail.html",
        {"category": category, "product": product},
    )


def search(request):
    query = request.GET.get("query", "")
    product = Product.objects.filter(
        status=Product.ACTIVE, stock=Product.IN_STOCK
    ).filter(Q(title__icontains=query) | Q(description__icontains=query))
    return render(request, "store/search.html", {"query": query, "product": product})


@login_required
def add_review_to_post(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            user_profile = get_object_or_404(UserProfile, email=request.user.email)
            review.author = user_profile
            review.save()
            return redirect(
                "product_detail", category_slug=product.category.slug, slug=product.slug
            )
    else:
        form = ReviewForm()
    return render(request, "store/review_form.html", {"form": form})


@login_required
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    if review.author != request.user:
        messages.error(request, "You are not authorized to delete this review.")
        return redirect("product_detail", pk=review.product.pk)

    product = review.product
    review.delete()

    messages.success(request, "Your review has been deleted successfully.")
    return redirect(
        "product_detail", category_slug=product.category.slug, slug=product.slug
    )


@login_required
def review_approve(request, pk):
    review = get_object_or_404(Review, pk=pk)
    review.approve()
    return redirect(
        "product_detail",
        category_slug=review.product.category.slug,
        slug=review.product.slug,
    )


@login_required
def review_disapprove(request, pk):
    review = get_object_or_404(Review, pk=pk)
    review.disapprove()
    return redirect(
        "product_detail",
        category_slug=review.product.category.slug,
        slug=review.product.slug,
    )


# def add_to_cart(request, product_id):
#     cart = Cart(request)
#     cart.add(product_id)

#     return redirect('frontpage')


# def remove_from_cart(request, product_id):
#     cart = Cart(request)
#     cart.remove(product_id)

#     return redirect('cart_view')


def cart_view(request):
    cart = Cart(request)

    return render(request, "store/cart_view.html", {"cart": cart})


# def change_quantity(request, product_id):
#     action = request.GET.get('action','')
#     if action:
#         quantity = 1

#         if action == 'decrease':
#             quantity = -1

#         cart = Cart(request)
#         cart.add(product_id, quantity, True)

#     return redirect('cart_view')


def generate_fake_categories(request):
    categories = []
    for _ in range(5):
        title = fake.word().capitalize()
        slug = fake.slug()
        category = Category.objects.create(title=title, slug=slug)
        categories.append(
            {"id": category.id, "title": category.title, "slug": category.slug}
        )  # Convert to dict

    return JsonResponse(
        {"categories": categories}
    )  # Returns a JSON-serializable response


def generate_fake_products(
    request, number_of_products=20, categories=None, vendors=None
):
    if not categories:
        categories = Category.objects.all()
    if not vendors:
        vendors = VendorProfile.objects.all()

    for _ in range(number_of_products):
        title = fake.word().capitalize() + " " + fake.word().capitalize()
        description = fake.text(max_nb_chars=300)
        price = random.randint(1000, 50000)  # Price in cents
        status = random.choice(
            [Product.DRAFT, Product.WAITING_APPROVAL, Product.ACTIVE, Product.DELETED]
        )
        stock = random.choice([Product.IN_STOCK, Product.OUT_OF_STOCK])
        featured = random.choice([True, False])
        category = random.choice(categories)
        vendor = random.choice(vendors)

        product = Product.objects.create(
            title=title,
            description=description,
            price=price,
            category=category,
            vendor=vendor,
            status=status,
            stock=stock,
            featured=featured,
        )
        print(f"Created product: {product.title}")


@login_required
def checkout(request):
    cart = Cart(request)
    user = request.user
    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            total_price = sum(
                item["product"].price * int(item["quantity"]) for item in cart
            )

            order = form.save(commit=False)
            order.created_by = user
            order.total_cost = total_price
            ref = str(uuid.uuid4()).replace("-", "")[:20]
            order.ref = ref
            order.save()

            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item["product"],
                    quantity=item["quantity"],
                    price=item["product"].price * int(item["quantity"]),
                )

            estimated_fee_kobo = int(min(0.015 * total_price * 100 + 10000, 200000))
            amount_kobo = int(total_price * 100) + estimated_fee_kobo

            # Build vendor splits
            vendor_totals = defaultdict(int)
            for item in cart:
                product = item["product"]
                quantity = int(item["quantity"])
                price_kobo = int(product.price * quantity * 100)

                subaccount_code = product.vendor.subaccount_code
                if subaccount_code:
                    vendor_totals[subaccount_code] += price_kobo

            admin_subaccount = settings.ADMIN_SUBACCOUNT_CODE
            vendor_totals[admin_subaccount] += estimated_fee_kobo

            split = {
                "type": "flat",
                "bearer_type": "subaccount",
                "bearer_subaccount": admin_subaccount,
                "subaccounts": [
                    {"subaccount": sub, "share": share}
                    for sub, share in vendor_totals.items()
                ],
            }

            payment = Payment.objects.create(
                user=user, order=order, amount=total_price, ref=ref, status="pending"
            )

            # Initialize Paystack payment
            protocol = "https" if request.is_secure() else "http"
            callback_url = (
                f"{protocol}://{request.get_host()}{reverse('paystack_callback')}"
            )

            if not split["subaccounts"]:
                return HttpResponse(
                    "No vendor subaccounts were found. Payment cannot proceed.",
                    status=400,
                )

            payload = {
                "email": user.email,
                "amount": amount_kobo,
                "reference": payment.ref,
                "callback_url": callback_url,
            }
            if split:
                payload["split"] = split

            headers = {
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                "https://api.paystack.co/transaction/initialize",
                json=payload,
                headers=headers,
            )

            try:
                res_data = response.json()
                payment.paystack_init_response = res_data
                payment.save()
            except ValueError:
                return HttpResponse(
                    f"Paystack returned an invalid response: {response.text}",
                    status=502,
                )

            if response.status_code == 200 and res_data.get("status"):
                return redirect(res_data["data"]["authorization_url"])
            else:
                return HttpResponse(
                    f"Paystack error: {res_data.get('message', 'Unknown error')}",
                    status=400,
                )

    else:
        form = OrderForm()

    return render(request, "store/checkout.html", {"cart": cart, "form": form})


@csrf_exempt
def paystack_callback(request):
    ref = request.GET.get("reference")
    if not ref:
        return HttpResponse("No transaction reference provided", status=400)

    url = f"https://api.paystack.co/transaction/verify/{ref}"
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}

    try:
        response = requests.get(url, headers=headers)
        data = response.json()
    except Exception as e:
        return HttpResponse(f"Verification error: {str(e)}", status=503)

    if response.status_code != 200 or not data.get("status"):
        return HttpResponse("Failed to verify payment", status=400)

    payment_data = data["data"]

    # Locate payment record
    payment = get_object_or_404(Payment, ref=ref)

    if payment.status == "paid":
        return redirect("receipt")

    if payment_data["status"] == "success":
        payment.status = "paid"
        payment.save()

        order = payment.order
        order.is_paid = True
        order.status = "completed"

        # Reduce stock for all ordered items
        for item in order.items.all():
            item.product.reduce_stock(item.quantity)

        order.save()

        if "cart" in request.session:
            cart = Cart(request)
            cart.clear()

        return redirect("receipt")
    else:
        payment.status = "failed"
        payment.save()
        return HttpResponse("Payment failed or was not successful", status=400)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        logger.warning("Paystack webhook called without signature")
        return HttpResponse(status=400)

    payload = request.body
    secret_key = settings.PAYSTACK_SECRET_KEY.encode("utf-8")
    computed_hash = hmac.new(secret_key, payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(computed_hash, signature):
        logger.warning("Invalid Paystack signature")
        return HttpResponse(status=401)

    try:
        data = json.loads(payload.decode("utf-8"))
    except ValueError as e:
        logger.error(f"Invalid JSON in Paystack webhook: {e}")
        return HttpResponse(status=400)

    event = data.get("event")
    if event == "charge.success":
        reference = data.get("data", {}).get("reference")
        if reference:
            try:
                payment = Payment.objects.get(ref=reference)
            except Payment.DoesNotExist:
                logger.error(f"No Payment found for ref {reference}")
            else:
                if payment.status != "paid":
                    payment.status = "paid"
                    payment.save()
                    order = payment.order
                    if order:
                        order.is_paid = True
                        order.status = "completed"
                        order.save()
                    logger.info(f"Payment {reference} marked as paid")
                else:
                    logger.info(f"Payment {reference} was already marked paid")

    return HttpResponse(status=200)


def payment_receipt(request, ref):
    order = get_object_or_404(Order, ref=ref)

    if not order.verified:
        return render(request, "error.html", {"error_message": "Payment not verified."})

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    # Insert logo
    # logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.png')
    # if os.path.exists(logo_path):
    #    p.drawImage(ImageReader(logo_path), 230, 750, width=120, height=60, preserveAspectRatio=True)

    # Draw header text
    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(300, 730, "EDO UNIVERSITY IYAMHO MEDICAL STUDENTS ASSOCIATION")

    # Payment info
    p.setFont("Helvetica", 12)
    p.drawString(100, 680, f"Name: {order.user.get_full_name()}")
    p.drawString(100, 660, f"Email: {order.email}")
    p.drawString(100, 640, f"Matriculation Number: {order.user.mat_no}")
    p.drawString(100, 620, f"Amount: NGN {order.amount}")
    p.drawString(100, 600, f"Reference: {order.ref}")
    p.drawString(100, 580, f"Status: SUCCESSFUL")
    p.drawString(100, 560, f"Date: {order.date_created.strftime('%d %B %Y, %I:%M %p')}")
    # p.drawString(100, 540, f"Description: {payment.payment_for.description if payment.payment_for else 'N/A'}")

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="payment_receipt.pdf"'
    return response


@login_required
def receipt(request):
    try:
        payment = Payment.objects.filter(user=request.user, status="paid").latest(
            "created_at"
        )
        order = payment.order
    except Payment.DoesNotExist:
        return HttpResponse("No recent successful payment found.", status=404)

    order_items = order.items.all()  # Assuming related_name='items' on OrderItem model

    return render(
        request,
        "store/receipt.html",
        {
            "order": order,
            "payment": payment,
            "order_items": order_items,
        },
    )


@csrf_exempt
def api_add_to_cart(request):
    if request.method == "POST":
        data = json.loads(request.body)
        product_id = data.get("product_id")

        if product_id:
            cart = Cart(request)
            cart.add(product_id)
            return JsonResponse(
                {
                    "success": True,
                    "cart_total_items": len(cart),
                    "cart_count": len(cart),
                }
            )
    return JsonResponse({"success": False}, status=400)


@csrf_exempt
def api_remove_from_cart(request):
    if request.method == "POST":
        data = json.loads(request.body)
        product_id = data.get("product_id")

        if product_id:
            cart = Cart(request)
            cart.remove(product_id)
            return JsonResponse(
                {"success": True, "message": "Item removed", "cart_count": len(cart)}
            )
    return JsonResponse({"success": False}, status=400)


@csrf_exempt
def api_change_quantity(request):
    if request.method == "POST":
        data = json.loads(request.body)
        product_id = data.get("product_id")
        action = data.get("action")

        if product_id and action:
            cart = Cart(request)
            quantity = 1 if action == "increase" else -1
            cart.add(product_id, quantity, update_quantity=True)

            return JsonResponse(
                {
                    "success": True,
                    "message": f"{action.title()}d item",
                    "cart_count": len(cart),
                }
            )
    return JsonResponse({"success": False}, status=400)
