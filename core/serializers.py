from rest_framework import serializers
from django.contrib.auth.models import Permission
from core.models import Lookup, Role, AuditLog
from users.serializers import PermissionSerializer


class LookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lookup
        fields = '__all__'


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), required=False
    )
    permissions_details = PermissionSerializer(source='permissions', many=True, read_only=True)

    class Meta:
        model = Role
        fields = ('id', 'role_name', 'permissions', 'permissions_details', 'is_active', 'created_at', 'updated_at')


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'
