from django import forms
from .models import UserProfile

class UserProfileSignupForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['email', 'user_name', 'first_name', 'last_name', 'password']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if UserProfile.objects.filter(email=email).exists():
            raise forms.ValidationError("Email is already taken.")
        return email