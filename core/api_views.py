from rest_framework.decorators import api_view
from rest_framework.response import Response
from store.models import Product, Category
from store.serializers import ProductSerializer, CategorySerializer
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi


@swagger_auto_schema(
    method="get",
    operation_description="Get all categories for the frontpage",
    responses={
        200: openapi.Response(
            description="List of all categories",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "categories": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT),
                    )
                },
            ),
        )
    },
    tags=["Core"],
)
@api_view(["GET"])
def frontpage_api(request):
    """
    Get all categories for the frontpage display.

    Returns a list of all available categories in the system.
    """
    categories = Category.objects.all()
    serializer = CategorySerializer(categories, many=True)
    return Response({"categories": serializer.data})
