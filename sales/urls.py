from django.urls import path, include
from rest_framework.routers import DefaultRouter
from sales.views import CustomerViewSet, CustomerOrderViewSet

router = DefaultRouter()
router.register(r'customers', CustomerViewSet, basename='customers')
router.register(r'customer-orders', CustomerOrderViewSet, basename='customerorders')
router.register(r'sales/orders', CustomerOrderViewSet, basename='salesorders')
router.register(r'sales/customers', CustomerViewSet, basename='salescustomers')

urlpatterns = [
    path('', include(router.urls)),
]
