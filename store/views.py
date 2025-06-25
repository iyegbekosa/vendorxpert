from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Product, Category, Review, OrderItem
from .forms import ReviewForm
from userprofile.models import VendorProfile, UserProfile
from faker import Faker
import random
from .cart import Cart
from .forms import OrderForm
fake = Faker()



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