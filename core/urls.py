from django.urls import path

from . import api_views

urlpatterns = [
    path("", api_views.root, name="root"),
    path("api/health/", api_views.health_api, name="health_api"),
    path("frontpage/", api_views.frontpage_api, name="frontpage_api"),
]
