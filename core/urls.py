from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    LookupViewSet, RoleViewSet, PermissionViewSet,
    CompanyProfileViewSet, DashboardViewSet
)

router = DefaultRouter()
router.register(r'core/lookups', LookupViewSet, basename='lookups')
router.register(r'core/roles', RoleViewSet, basename='roles')
router.register(r'core/permissions', PermissionViewSet, basename='permissions')
router.register(r'core/company-profile', CompanyProfileViewSet, basename='companyprofile')
router.register(r'core/dashboard', DashboardViewSet, basename='dashboard')

urlpatterns = [
    path('', include(router.urls)),
]
