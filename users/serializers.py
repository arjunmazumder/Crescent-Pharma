from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from core.models import Role

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    app_label = serializers.CharField(source='content_type.app_label', read_only=True)
    model = serializers.CharField(source='content_type.model', read_only=True)

    class Meta:
        model = Permission
        fields = ('id', 'name', 'codename', 'app_label', 'model')


class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    user_permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), required=False
    )
    role_permissions = PermissionSerializer(source='role.permissions', many=True, read_only=True)
    extra_permissions_details = PermissionSerializer(source='user_permissions', many=True, read_only=True)
    effective_permissions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'password', 'email', 'is_superuser', 'is_staff',
            'employee_id', 'role', 'role_name',
            'user_permissions', 'role_permissions', 'extra_permissions_details',
            'effective_permissions', 'contact', 'address', 'date_of_birth',
            'joining_date', 'nid_number', 'morning_shift_start', 'morning_shift_end',
            'evening_shift_start', 'evening_shift_end',
            'location_bounded_attendance'
        )
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'employee_id': {'required': False, 'allow_blank': True, 'allow_null': True}
        }

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'employeeId': 'employee_id',
                'dateOfBirth': 'date_of_birth',
                'joiningDate': 'joining_date',
                'nidNumber': 'nid_number',
                'morningShiftStart': 'morning_shift_start',
                'morningShiftEnd': 'morning_shift_end',
                'eveningShiftStart': 'evening_shift_start',
                'eveningShiftEnd': 'evening_shift_end',
                'locationBoundedAttendance': 'location_bounded_attendance',
                'isSuperuser': 'is_superuser',
                'isStaff': 'is_staff',
                'userPermissions': 'user_permissions',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)

    def get_effective_permissions(self, obj):
        return obj.get_effective_permissions()
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user_permissions = validated_data.pop('user_permissions', None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_password('Crescent@123')
        user.save()
        
        if user_permissions is not None:
            user.user_permissions.set(user_permissions)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user_permissions = validated_data.pop('user_permissions', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        if user_permissions is not None:
            user.user_permissions.set(user_permissions)
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        return {
            'message': "Login successful",
            'access': data['access'],
            'refresh': data['refresh'],
            'data': UserSerializer(self.user).data
        }
