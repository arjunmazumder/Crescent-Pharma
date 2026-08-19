from django.urls import path, include
from rest_framework.routers import DefaultRouter
from inventory.views import (
    CategoryViewSet, AttributeViewSet, AttributeValueViewSet,
    ProductViewSet, WarehouseViewSet, StockLevelViewSet, StockMovementViewSet
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='categories')
router.register(r'attributes', AttributeViewSet, basename='attributes')
router.register(r'attribute-values', AttributeValueViewSet, basename='attributevalues')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'warehouses', WarehouseViewSet, basename='warehouses')
router.register(r'stock-levels', StockLevelViewSet, basename='stocklevels')
router.register(r'stock-movements', StockMovementViewSet, basename='stockmovements')

urlpatterns = [
    path('', include(router.urls)),
]
