from django.contrib import admin
from .models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest
)

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'shift', 'status', 'check_in_time', 'check_out_time', 'check_in_location_name')
    list_filter = ('status', 'shift', 'date')
    search_fields = ('user__username', 'user__employee_id', 'notes')

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
    search_fields = ('user__username', 'user__employee_id')

@admin.register(TourAllowance)
class TourAllowanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'from_location', 'to_location', 'mode_of_journey', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'date')
    search_fields = ('user__username', 'user__employee_id', 'from_location', 'to_location')

admin.site.register(Holiday)
admin.site.register(WeekendConfig)
admin.site.register(OfficeLocation)
admin.site.register(SalaryStructure)
