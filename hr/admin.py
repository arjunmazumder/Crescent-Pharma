from django.contrib import admin
from .models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest, UserLocationLog, UserCurrentLocation,
    TAComponent, EmployeeTARate, AllowanceBill, AllowanceBillLine, BonusType
)

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'shift', 'status', 'check_in_time', 'check_out_time', 'check_in_location_name')
    list_filter = ('status', 'shift', 'date')
    search_fields = ('user__username', 'user__employee_id', 'notes')

@admin.register(UserLocationLog)
class UserLocationLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'latitude', 'longitude', 'accuracy', 'speed', 'battery_level', 'is_mock_location', 'recorded_at')
    list_filter = ('is_mock_location', 'recorded_at')
    search_fields = ('user__username', 'user__employee_id')

@admin.register(UserCurrentLocation)
class UserCurrentLocationAdmin(admin.ModelAdmin):
    list_display = ('user', 'latitude', 'longitude', 'is_tracking_active', 'battery_level', 'last_updated_at')
    list_filter = ('is_tracking_active', 'last_updated_at')
    search_fields = ('user__username', 'user__employee_id')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_type', 'start_date', 'end_date', 'total_days', 'status', 'approved_by', 'applied_at')
    list_filter = ('status', 'leave_type', 'start_date')
    search_fields = ('user__username', 'user__employee_id', 'reason', 'rejection_reason')

@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ('user', 'month', 'year', 'amount', 'status', 'base_salary', 'absent_days', 'loan_deduction')
    list_filter = ('status', 'year', 'month')
    search_fields = ('user__username', 'user__employee_id')

@admin.register(PayrollApproval)
class PayrollApprovalAdmin(admin.ModelAdmin):
    list_display = ('payroll', 'approver', 'role', 'status', 'created_at')
    list_filter = ('status', 'role', 'created_at')
    search_fields = ('payroll__user__username', 'approver__username', 'remarks')

@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'emi_amount', 'remaining_amount', 'deduction_start_date', 'status', 'created_at')
    list_filter = ('status', 'deduction_start_date')
    search_fields = ('user__username', 'user__employee_id', 'note')

@admin.register(TourAllowance)
class TourAllowanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'from_location', 'to_location', 'mode_of_journey', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'date')
    search_fields = ('user__username', 'user__employee_id', 'from_location', 'to_location')

@admin.register(TAComponent)
class TAComponentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'display_order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'description')
    ordering = ('display_order', 'code')


@admin.register(EmployeeTARate)
class EmployeeTARateAdmin(admin.ModelAdmin):
    list_display = ('user', 'component', 'daily_amount', 'effective_from', 'is_active')
    list_filter = ('component', 'is_active', 'effective_from')
    search_fields = ('user__username', 'user__employee_id', 'component__code', 'component__name')
    autocomplete_fields = ('component',)
    ordering = ('user', 'component', '-effective_from')


class AllowanceBillLineInline(admin.TabularInline):
    model = AllowanceBillLine
    extra = 0
    readonly_fields = ('source', 'component', 'tour_allowance', 'days', 'rate', 'amount', 'description')
    can_delete = False


@admin.register(AllowanceBill)
class AllowanceBillAdmin(admin.ModelAdmin):
    list_display = ('bill_number', 'user', 'month', 'year', 'eligible_days',
                    'total_daily_ta', 'total_tour_da', 'total_amount', 'status')
    list_filter = ('status', 'year', 'month')
    search_fields = ('bill_number', 'user__username', 'user__employee_id', 'notes')
    readonly_fields = ('bill_number', 'eligible_days', 'total_daily_ta',
                       'total_tour_da', 'total_amount', 'accounting_voucher')
    inlines = [AllowanceBillLineInline]
    ordering = ('-year', '-month', '-id')


@admin.register(BonusType)
class BonusTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'percentage_of_basic', 'display_order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'description')
    ordering = ('display_order', 'code')


admin.site.register(Holiday)
admin.site.register(WeekendConfig)
admin.site.register(OfficeLocation)
admin.site.register(SalaryStructure)

