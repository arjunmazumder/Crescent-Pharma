from rest_framework import viewsets, permissions
from drf_spectacular.utils import extend_schema
from django.contrib.auth.models import Permission
from core.models import Lookup, Role
from core.serializers import LookupSerializer, RoleSerializer
from users.serializers import PermissionSerializer


@extend_schema(tags=['Core / Lookups'])
class LookupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Lookup.objects.filter(is_active=True).order_by('name', 'value')
    serializer_class = LookupSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'value']
    filterset_fields = ['name', 'is_active']
    ordering_fields = ['id', 'name', 'value', 'created_at']
    ordering = ['name', 'value']


@extend_schema(tags=['Core / Roles & Permissions'])
class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().prefetch_related('permissions').order_by('role_name')
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['role_name']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'role_name', 'created_at']
    ordering = ['role_name']


@extend_schema(tags=['Core / Roles & Permissions'])
class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all().select_related('content_type').order_by('content_type__app_label', 'codename')
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'codename', 'content_type__app_label', 'content_type__model']
    filterset_fields = ['content_type__app_label', 'content_type__model']
    ordering_fields = ['id', 'name', 'codename', 'content_type__app_label']
    ordering = ['content_type__app_label', 'codename']
