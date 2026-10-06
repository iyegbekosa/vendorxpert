"""Root URL configuration for the VendorXprt API."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("xprt-admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("userprofile.urls")),
    path("", include("store.urls")),
    path("", include("operations.urls")),
]

if settings.ENABLE_API_DOCS:
    from drf_yasg import openapi
    from drf_yasg.views import get_schema_view
    from rest_framework import permissions

    schema_view = get_schema_view(
        openapi.Info(title="VendorXprt API", default_version="v1"),
        public=True,
        permission_classes=(permissions.AllowAny,),
        authentication_classes=[],
    )
    urlpatterns += [
        path("swagger<format>/", schema_view.without_ui(cache_timeout=0), name="schema-json"),
        path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
        path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    ]
