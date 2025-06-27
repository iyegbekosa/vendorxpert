from django.urls import path
from . import views, api_views
urlpatterns = [
    path('', views.frontpage, name='frontpage'),
    path('frontpage/', api_views.frontpage_api, name='frontpage_api'),
]