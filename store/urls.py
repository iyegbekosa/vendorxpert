from django.urls import path
from . import views
urlpatterns = [
    path('search/', views.search, name='search'),
    path('<slug:slug>/', views.category_detail, name='category_detail'),
    path('add_review/<int:pk>/', views.add_review_to_post, name='add_review'),
    path('<slug:category_slug>/<slug:slug>/', views.product_detail, name='product_detail'),
    path('generate_fake_categories', views.generate_fake_categories, name='generate_fake_categories'),
    path('generate_fake_products', views.generate_fake_products, name='generate_fake_products'),
]