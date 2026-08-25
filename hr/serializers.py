from rest_framework import serializers
from hr.models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest, UserLocationLog, UserCurrentLocation
)


class AttendanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = Attendance
        fields = '__all__'


class PayrollSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    generated_by_username = serializers.CharField(source='generated_by.username', read_only=True)
    current_approver_role_name = serializers.CharField(source='current_approver_role.role_name', read_only=True)

    class Meta:
        model = Payroll
        fields = (
            'id',
            'user',
            'username',
            'employee_id',
            'month',
            'year',
            'amount',
            'status',
            'current_approver_role',
            'current_approver_role_name',
            'generated_by',
            'generated_by_username',
            'absent_days',
            'base_salary',
            'housing_allowance',
            'transport_allowance',
            'medical_benefits',
            'utility_allowance',
            'per_day_salary',
            'per_hour_salary',
            'unpaid_deduction',
            'total_ta_allowance',
            'total_tour_allowance',
            'loan_deduction',
            'created_at',
        )


class LoanSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = Loan
        fields = '__all__'


class TourAllowanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = TourAllowance
        fields = '__all__'


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = '__all__'


class WeekendConfigSerializer(serializers.ModelSerializer):
    day_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WeekendConfig
        fields = ('id', 'day_of_week', 'day_name', 'is_active')

    def get_day_name(self, obj):
        days = {
            0: "Monday",
            1: "Tuesday",
            2: "Wednesday",
            3: "Thursday",
            4: "Friday",
            5: "Saturday",
            6: "Sunday"
        }
        return days.get(obj.day_of_week, "")


class OfficeLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficeLocation
        fields = '__all__'


class SalaryStructureSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = SalaryStructure
        fields = '__all__'


class PayrollApprovalSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    approver_name = serializers.CharField(source='approver.username', read_only=True)

    class Meta:
        model = PayrollApproval
        fields = '__all__'


class LeaveRequestSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ('total_days', 'status', 'approved_by', 'applied_at', 'approved_at')
        extra_kwargs = {
            'user': {'required': False}
        }

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'leaveType': 'leave_type',
                'startDate': 'start_date',
                'endDate': 'end_date',
                'userId': 'user',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)

    def validate(self, attrs):
        start_date = attrs.get('start_date') or (self.instance.start_date if self.instance else None)
        end_date = attrs.get('end_date') or (self.instance.end_date if self.instance else None)

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({"end_date": "End date must be on or after start date."})

        return attrs


# -----------------------------------------------------------------------------
# Live GPS Tracking Serializers
# -----------------------------------------------------------------------------

class UserLocationPingSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
    location_name = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    accuracy = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    battery_level = serializers.IntegerField(required=False, allow_null=True)
    is_mock_location = serializers.BooleanField(required=False, default=False)
    recorded_at = serializers.DateTimeField(required=False, allow_null=True)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'locationName': 'location_name',
                'batteryLevel': 'battery_level',
                'isMockLocation': 'is_mock_location',
                'recordedAt': 'recorded_at',
                'lat': 'latitude',
                'lng': 'longitude',
                'lon': 'longitude',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class LocationPointSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
    location_name = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    accuracy = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    battery_level = serializers.IntegerField(required=False, allow_null=True)
    is_mock_location = serializers.BooleanField(required=False, default=False)
    recorded_at = serializers.DateTimeField(required=False, allow_null=True)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'locationName': 'location_name',
                'batteryLevel': 'battery_level',
                'isMockLocation': 'is_mock_location',
                'recordedAt': 'recorded_at',
                'lat': 'latitude',
                'lng': 'longitude',
                'lon': 'longitude',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class UserLocationBatchSyncSerializer(serializers.Serializer):
    locations = LocationPointSerializer(many=True, required=True)


class UserCurrentLocationSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    full_name = serializers.SerializerMethodField(read_only=True)
    role_name = serializers.CharField(source='user.role.role_name', read_only=True)

    class Meta:
        model = UserCurrentLocation
        fields = (
            'id',
            'user',
            'username',
            'employee_id',
            'full_name',
            'role_name',
            'latitude',
            'longitude',
            'location_name',
            'accuracy',
            'speed',
            'battery_level',
            'is_tracking_active',
            'last_updated_at'
        )

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class UserLocationLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = UserLocationLog
        fields = '__all__'


