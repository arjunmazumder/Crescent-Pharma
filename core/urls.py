from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import LookupViewSet, RoleViewSet, PermissionViewSet

router = DefaultRouter()
router.register(r'core/lookups', LookupViewSet, basename='lookups')
router.register(r'core/roles', RoleViewSet, basename='roles')
router.register(r'core/permissions', PermissionViewSet, basename='permissions')

urlpatterns = [
    path('', include(router.urls)),
]
