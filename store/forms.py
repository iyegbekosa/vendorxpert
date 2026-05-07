from django import forms 
from .models import Product, Review, Order

class ProductForm(forms.ModelForm):
    
    class Meta:
        model = Product
        fields = ("category","title","description","price","product_image","stock")


class ReviewForm(forms.ModelForm):

    class Meta:
        model = Review
        fields = ('subject','text','rating')


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ("first_name", "last_name", "phone", "pickup_location")

    def clean_phone(self):
        """Normalize Nigerian phone input to +234XXXXXXXXXX and validate."""
        value = self.cleaned_data.get("phone")
        if not value or not str(value).strip():
            raise forms.ValidationError("Phone number is required")

        phone_str = str(value).strip().replace(" ", "").replace("-", "")

        # Convert local Nigerian format to international
        if phone_str.startswith("0") and len(phone_str) == 11:
            phone_str = "+234" + phone_str[1:]

        import re

        if not re.match(r"^\+234[0-9]{10}$", phone_str):
            raise forms.ValidationError(
                "Phone must be in format +2349025144369 or 09025144369"
            )

        return phone_str
        