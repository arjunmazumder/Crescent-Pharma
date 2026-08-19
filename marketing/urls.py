from django.urls import path, include
from rest_framework.routers import DefaultRouter
from marketing.views import SalesTargetViewSet, MarketingReportViewSet

router = DefaultRouter()
router.register(r'marketing/targets', SalesTargetViewSet, basename='marketingtargets')
router.register(r'marketing/reports', MarketingReportViewSet, basename='marketingreports')

urlpatterns = [
    path('', include(router.urls)),
]
