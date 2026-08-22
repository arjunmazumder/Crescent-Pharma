from django.urls import path, include
from rest_framework.routers import DefaultRouter
from purchases.views import (
    SupplierViewSet,
    PurchaseOrderViewSet,
    LetterOfCreditViewSet,
    GoodsReceivedNoteViewSet,
    PurchaseReportViewSet
)

router = DefaultRouter()
router.register(r'purchases/suppliers', SupplierViewSet, basename='purchases-suppliers')
router.register(r'purchases/orders', PurchaseOrderViewSet, basename='purchases-orders')
router.register(r'purchases/letters-of-credit', LetterOfCreditViewSet, basename='purchases-letters-of-credit')
router.register(r'purchases/grn', GoodsReceivedNoteViewSet, basename='purchases-grn')
router.register(r'purchases/reports', PurchaseReportViewSet, basename='purchases-reports')

urlpatterns = [
    path('', include(router.urls)),
]
