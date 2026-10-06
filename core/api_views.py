from django.conf import settings
from django.db import connection
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from store.models import Category
from store.serializers import CategorySerializer


def root(request):
    """The API host has no pages of its own; send visitors to the marketplace."""
    return HttpResponseRedirect(settings.FRONTEND_URL)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_api(request):
    """Liveness/readiness probe for uptime monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return Response({"status": "error", "database": "unavailable"}, status=503)
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])
def frontpage_api(request):
    categories = Category.objects.order_by("title")
    return Response({"categories": CategorySerializer(categories, many=True).data})
