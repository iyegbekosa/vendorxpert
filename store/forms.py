from django import forms 
from .models import Product, Review

class ProductForm(forms.ModelForm):
    
    class Meta:
        model = Product
        fields = ("category","title","description","price","product_image","stock")


class ReviewForm(forms.ModelForm):

    class Meta:
        model = Review
        fields = ('subject','text','rating')
