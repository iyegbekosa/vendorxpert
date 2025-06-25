from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import FileResponse, JsonResponse, HttpResponse
from .models import Product, Category, Review, OrderItem, Order
from .forms import ReviewForm
from userprofile.models import VendorProfile, UserProfile
from faker import Faker
import random
from .cart import Cart
from .forms import OrderForm
fake = Faker()
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.conf import settings
from django.urls import reverse
from decimal import Decimal
import requests
import io
import os



def product_detail(request, category_slug, slug):
    # product = get_object_or_404(Product, slug=slug)
    product = get_object_or_404(Product, slug=slug, category__slug=category_slug)
    return render(request, 'store/product_detail.html', {
        'product':product
    })


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    product = category.product.filter(status=Product.ACTIVE, stock=Product.IN_STOCK)
    return render(request, 'store/category_detail.html', {
        'category':category,
        'product':product
    }) 


def search(request):
    query = request.GET.get('query','')
    product = Product.objects.filter(status=Product.ACTIVE, stock=Product.IN_STOCK).filter(Q(title__icontains=query) | Q(description__icontains=query))
    return render(request, 'store/search.html', {
        'query':query,
        'product':product
    })


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
            return redirect('product_detail', category_slug=product.category.slug, slug=product.slug)
    else:
        form = ReviewForm()
    return render(request, 'store/review_form.html', {'form': form})


# @login_required
# def delete_review(request, review_id):
#     review = get_object_or_404(Review, id=review_id)

#     if request.user == review.author:
#         # Store product data before deleting the review
#         product_slug = review.product.slug
#         category_slug = review.product.category.slug

#         review.delete()
#         messages.success(request, "Your review has been deleted successfully.")

#         return redirect('product_detail', category_slug=category_slug, slug=product_slug)
    
#     else:
#         messages.error(request, "You are not authorized to delete this review.")
#         return redirect('home')  # Redirect to a safe fallback page



@login_required
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    if review.author != request.user:
        messages.error(request, "You are not authorized to delete this review.")
        return redirect('product_detail', pk=review.product.pk)

    product = review.product
    review.delete()

    messages.success(request, "Your review has been deleted successfully.")
    return redirect('product_detail', pk=product.pk)


@login_required
def review_approve(request, pk):
    review = get_object_or_404(Review, pk=pk)
    review.approve()
    return redirect('product_detail', category_slug=review.product.category.slug, slug=review.product.slug)

@login_required
def review_disapprove(request, pk):
    review = get_object_or_404(Review, pk=pk)
    review.disapprove()
    return redirect('product_detail', category_slug=review.product.category.slug, slug=review.product.slug)


def add_to_cart(request, product_id):
    cart = Cart(request)
    cart.add(product_id)

    return redirect('cart_view')


def remove_from_cart(request, product_id):
    cart = Cart(request)
    cart.remove(product_id)

    return redirect('cart_view')

def cart_view(request):
    cart = Cart(request)

    return render(request, 'store/cart_view.html', {
        'cart':cart
    })

def change_quantity(request, product_id):
    action = request.GET.get('action','')
    if action:
        quantity = 1

        if action == 'decrease':
            quantity = -1
        
        cart = Cart(request)
        cart.add(product_id, quantity, True)
    
    return redirect('cart_view')

@login_required
def checkout(request):
    cart = Cart(request)
    if request.method == 'POST':
        form = OrderForm(request.POST)

        if form.is_valid:
            total_price = 0
            for item in cart:
                product = item['product']
                total_price += product.price * int(item['quantity'])
            
            order = form.save(commit=False)
            order.created_by = request.user
            order.total_cost = total_price
            order.save()

            for item in cart:
                product  = item['product']
                quantity = item['quantity']
                price = product.price * quantity

                item = OrderItem.objects.create(order=order, product=product, quantity=quantity, price=price)

                cart.clear()
                return redirect('receipt')
    else:
        form = OrderForm()
    return render(request, 'store/checkout.html', {
       'cart':cart,
       'form':form
    })




def generate_fake_categories(request):
    categories = []
    for _ in range(5):
        title = fake.word().capitalize()
        slug = fake.slug()
        category = Category.objects.create(title=title, slug=slug)
        categories.append({"id": category.id, "title": category.title, "slug": category.slug})  # Convert to dict

    return JsonResponse({"categories": categories})  # Returns a JSON-serializable response

def generate_fake_products(request, number_of_products=20, categories=None, vendors=None):
    if not categories:
        categories = Category.objects.all()
    if not vendors:
        vendors = VendorProfile.objects.all()

    for _ in range(number_of_products):
        title = fake.word().capitalize() + " " + fake.word().capitalize()
        slug = fake.slug()
        description = fake.text(max_nb_chars=300)
        price = random.randint(1000, 50000)  # Price in cents
        status = random.choice([Product.DRAFT, Product.WAITING_APPROVAL, Product.ACTIVE, Product.DELETED])
        stock = random.choice([Product.IN_STOCK, Product.OUT_OF_STOCK])
        featured = random.choice([True, False])
        category = random.choice(categories)
        vendor = random.choice(vendors)
        
        product = Product.objects.create(
            title=title,
            slug=slug,
            description=description,
            price=price,
            category=category,
            vendor=vendor,
            status=status,
            stock=stock,
            featured=featured,
        )
        print(f"Created product: {product.title}")

def receipt(request):
    return render(request, 'store/receipt.html')

def initialize_split_payment(request):
    if request.method != "POST":
        return HttpResponse("Invalid request method.", status=405)

    try:
        data = request.POST
        name = data.get('payment_type')
        email = data.get('email')
        level = data.get('level')
        amount = float(data.get('amount'))

        user = get_object_or_404(UserProfile, email=email)
        payment_type = data.get('payment_type')  # "fee" or "skill"
        session = data.get('session')
        skill = data.get('skill')

        print("Incoming payment_type:", payment_type)
        print("Incoming session:", session)
        print("Incoming skill:", skill)

        # Get relevant payment object (your model for skill or session fees)
        payment_obj = get_payment_model_instance(payment_type, session if payment_type == "fee" else skill)
        payment_code = payment_obj.payment_code if payment_obj else "GEN"
        print("Resolved payment_code:", payment_code)

        # Set standardized `payment_for` for model field
        if payment_type == "fee":
            payment_for_label = "association_fee"
        elif payment_type == "skill":
            payment_for_label = "skill_acquisition"
        else:
            payment_for_label = None

        # Create payment record in DB
        payment = Order.objects.create(
            user=user,
            level=int(level),
            amount=amount,
            email=user.email,
            name=name,
            payment_for=payment_for_label
        )

        # Prepare Paystack payload
        protocol = 'https' if request.is_secure() else 'http'
        callback_url = f"{protocol}://{request.get_host()}{reverse('paystack_callback')}"
        amount_kobo = int(amount * 100)

        # Prepare split if applicable
        split_info = settings.PAYSTACK_SPLITS.get(payment_code)
        split = None

        if split_info:
            # Compute adjusted share (if needed)
            base_amount = (amount - 200) / 1.015
            new_amount = int(base_amount * 100)

            if payment_code == "SKIL":
                split = {
                    "type": "flat",
                    "currency": "NGN",
                    "subaccounts": [
                        {
                            "subaccount": split_info["main_recipient"],
                            "share": new_amount
                        },
                    ],
                    "bearer_type": "account"
                }

            elif payment_code == "COLL":
                split = {
                    "type": "flat",
                    "currency": "NGN",
                    "subaccounts": [
                        {
                            "subaccount": split_info["flat_recipient"],
                            "share": 1475000
                        },
                        {
                            "subaccount": split_info["sub_recipient"],
                            "share": 25000
                        },
                        {
                            "subaccount": split_info["main_recipient"],
                            "share": 500000
                        }
                    ],
                    "bearer_type": "account"
                }

        # Construct payload
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
            "Content-Type": "application/json"
        }

        # Call Paystack
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers
        )

        try:
            print("Raw response:", response.content)
            res_data = response.json()
        except ValueError:
            return HttpResponse(f"Paystack returned an invalid response: {response.text}", status=502)

        print("Paystack Response:", response.status_code, res_data)

        if response.status_code == 200 and res_data.get("status"):
            return redirect(res_data["data"]["authorization_url"])
        else:
            return HttpResponse(f"Paystack error: {res_data.get('message', 'Unknown error')}", status=400)

    except Exception as e:
        return render(request, "error.html", {
            "error_message": str(e),
        })


@csrf_exempt
def paystack_callback(request):
    ref = request.GET.get('reference')
    if not ref:
        return JsonResponse({"status": False, "message": "No reference found in URL"})

    try:
        payment = Order.objects.get(ref=ref)
    except Order.DoesNotExist:
        return JsonResponse({"status": False, "message": "Invalid reference"})

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
    }
    response = requests.get(f"https://api.paystack.co/transaction/verify/{ref}", headers=headers)
    result = response.json()

    if result['status'] and result['data']['status'] == 'success':
        payment.verified = True
        payment.save()
        return redirect('payment_receipt', ref=payment.ref)
    else:
        return render(request, 'error.html', {"error_message": "Payment not successful."})


def payment_receipt(request, ref):
    payment = get_object_or_404(Order, ref=ref)

    if not payment.verified:
        return render(request, "error.html", {"error_message": "Payment not verified."})

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    # Insert logo
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.png')
    if os.path.exists(logo_path):
        p.drawImage(ImageReader(logo_path), 230, 750, width=120, height=60, preserveAspectRatio=True)

    # Draw header text
    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(300, 730, "EDO UNIVERSITY IYAMHO MEDICAL STUDENTS ASSOCIATION")

    # Payment info
    p.setFont("Helvetica", 12)
    p.drawString(100, 680, f"Name: {payment.user.get_full_name()}")
    p.drawString(100, 660, f"Email: {payment.email}")
    p.drawString(100, 640, f"Matriculation Number: {payment.user.mat_no}")
    p.drawString(100, 620, f"Amount: NGN {payment.amount}")
    p.drawString(100, 600, f"Reference: {payment.ref}")
    p.drawString(100, 580, f"Status: SUCCESSFUL")
    p.drawString(100, 560, f"Date: {payment.date_created.strftime('%d %B %Y, %I:%M %p')}")
    # p.drawString(100, 540, f"Description: {payment.payment_for.description if payment.payment_for else 'N/A'}")

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="payment_receipt.pdf"'
    return response
