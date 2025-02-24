from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Product, Category, Review
from .forms import ReviewForm
from userprofile.models import VendorProfile
from faker import Faker
import random
fake = Faker()



def product_detail(request, category_slug, slug):
    product = get_object_or_404(Product, slug=slug)
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
            review.save()
            return redirect('product_detail', category_slug=product.category.slug, slug=product.slug)
    else:
        form = ReviewForm()
    return render(request, 'store/review_form.html', {'form': form})


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
    
