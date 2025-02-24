from django.urls import path
from . import views
urlpatterns = [
    path('', views.frontpage, name='frontpage'),
    path('about', views.about_view, name='about'),
    path('faq', views.faq_view, name='faq'),
    path('contact', views.contact_view, name='contact'),

]