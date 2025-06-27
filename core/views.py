from django.shortcuts import render, redirect
from store.models import Product, Review
from .models import Faq
from .forms import ContactForm


def frontpage(request):
    product = Product.objects.all()
    sponsored = Product.objects.filter(featured=True)
    return render(request, 'core/frontpage.html', {
        'product':product,
        'sponsored':sponsored,
    })


def about_view(request):
    return render(request, 'core/about.html')


def faq_view(request):
    faq = Faq.objects.filter(approved=True)
    context = {
        'faq':faq
    }
    return render(request, 'core/faq.html', context)


def contact_view(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.save()
            return redirect('contact')   
    else:
        form = ContactForm()   
    return render(request, 'core/contact.html', {'form': form})

