from django.urls import path, include
from rest_framework.routers import DefaultRouter
from marketing.views import (
    SalesTargetViewSet,
    MarketingReportViewSet,
    DoctorViewSet,
    DoctorSampleDistributionViewSet
)

router = DefaultRouter()
router.register(r'marketing/targets', SalesTargetViewSet, basename='marketingtargets')
router.register(r'marketing/reports', MarketingReportViewSet, basename='marketingreports')
router.register(r'marketing/doctors', DoctorViewSet, basename='marketingdoctors')
router.register(r'marketing/doctor-samples', DoctorSampleDistributionViewSet, basename='marketingdoctorsamples')

urlpatterns = [
    path('', include(router.urls)),
]

