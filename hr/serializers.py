import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from hr.models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest, UserLocationLog, UserCurrentLocation,
    TAComponent, EmployeeTARate, AllowanceBill, AllowanceBillLine, BonusType
)
from hr.services import AllowanceEligibilityService


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
            'bonus_type',
            'bonus_percentage',
            'total_bonus',
            'created_at',
        )


class LoanSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = Loan
        fields = '__all__'

    def validate(self, attrs):
        """
        ModelSerializer does not call Model.clean(), so the loan rules are invoked
        here. Without this the one-open-loan constraint would only surface as a
        database IntegrityError (HTTP 500) instead of a field error.
        """
        candidate = copy.copy(self.instance) if self.instance is not None else Loan()
        for field, value in attrs.items():
            setattr(candidate, field, value)

        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc))

        return attrs


class TourAllowanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    is_payable = serializers.SerializerMethodField(read_only=True)
    non_payable_reason = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TourAllowance
        fields = '__all__'

    def _calendar(self):
        # Cached on the serializer instance, so a list response loads the
        # holiday and weekend tables once rather than once per row.
        if not hasattr(self, '_calendar_cache'):
            self._calendar_cache = AllowanceEligibilityService.get_calendar()
        return self._calendar_cache

    def get_non_payable_reason(self, obj):
        """Shown to the approver so a holiday tour is visible before approval."""
        holidays, weekend_days = self._calendar()
        return AllowanceEligibilityService.get_non_payable_reason(obj.date, holidays, weekend_days)

    def get_is_payable(self, obj):
        return self.get_non_payable_reason(obj) is None


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




class TAComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TAComponent
        fields = '__all__'


class EmployeeTARateSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    component_code = serializers.CharField(source='component.code', read_only=True, default='')
    component_name = serializers.CharField(source='component.name', read_only=True, default='')

    class Meta:
        model = EmployeeTARate
        fields = '__all__'
        extra_kwargs = {
            'component': {'required': False, 'allow_null': True}
        }

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'userId': 'user',
                'componentId': 'component',
                'dailyAmount': 'daily_amount',
                'effectiveFrom': 'effective_from',
                'isActive': 'is_active',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)

    def validate(self, attrs):
        candidate = copy.copy(self.instance) if self.instance is not None else EmployeeTARate()
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc))
        return attrs


class AllowanceBillLineSerializer(serializers.ModelSerializer):
    component_code = serializers.CharField(source='component.code', read_only=True)
    component_name = serializers.CharField(source='component.name', read_only=True)
    tour_date = serializers.DateField(source='tour_allowance.date', read_only=True)

    class Meta:
        model = AllowanceBillLine
        fields = (
            'id', 'source', 'component', 'component_code', 'component_name',
            'tour_allowance', 'tour_date', 'days', 'rate', 'amount', 'description'
        )


class AllowanceBillSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    generated_by_username = serializers.CharField(source='generated_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    voucher_number = serializers.CharField(source='accounting_voucher.voucher_number', read_only=True)
    lines = AllowanceBillLineSerializer(many=True, read_only=True)

    class Meta:
        model = AllowanceBill
        fields = (
            'id', 'bill_number', 'user', 'username', 'employee_id',
            'month', 'year', 'status', 'eligible_days',
            'total_daily_ta', 'total_tour_da', 'total_amount',
            'accounting_voucher', 'voucher_number',
            'notes', 'rejection_reason',
            'generated_by', 'generated_by_username',
            'approved_by', 'approved_by_username', 'approved_at', 'paid_at',
            'created_at', 'updated_at', 'lines'
        )


class AllowanceBillGenerateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, help_text="Omit on generate-all")
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2000, max_value=2200)


class AllowanceBillRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class BonusTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BonusType
        fields = '__all__'

    def validate(self, attrs):
        candidate = copy.copy(self.instance) if self.instance is not None else BonusType()
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc))
        return attrs
