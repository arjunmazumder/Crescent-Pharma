from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BOMViewSet, ProductionLineViewSet, ProductionPlanViewSet,
    ProductionBatchViewSet, MaterialIssueSlipViewSet,
    ProductionStageLogViewSet, FinishedGoodsTransferViewSet,
    ProductionReportViewSet
)

router = DefaultRouter()
router.register(r'production/boms', BOMViewSet, basename='production-boms')
router.register(r'production/lines', ProductionLineViewSet, basename='production-lines')
router.register(r'production/plans', ProductionPlanViewSet, basename='production-plans')
router.register(r'production/batches', ProductionBatchViewSet, basename='production-batches')
router.register(r'production/material-slips', MaterialIssueSlipViewSet, basename='production-material-slips')
router.register(r'production/stage-logs', ProductionStageLogViewSet, basename='production-stage-logs')
router.register(r'production/transfers', FinishedGoodsTransferViewSet, basename='production-transfers')
router.register(r'production/reports', ProductionReportViewSet, basename='production-reports')

urlpatterns = [
    path('', include(router.urls)),
]
