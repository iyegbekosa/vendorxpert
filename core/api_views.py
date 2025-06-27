from rest_framework.decorators import api_view
from rest_framework.response import Response
from store.models import Product, Category
from store.serializers import ProductSerializer, CategorySerializer

@api_view(['GET'])
def frontpage_api(request):
    categories = Category.objects.all()
    serializer = CategorySerializer(categories, many=True)
    return Response({'categories': serializer.data})
