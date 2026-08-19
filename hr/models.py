from django.db import models
from django.conf import settings
from core.models import Lookup, Role

class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'holidays'

class WeekendConfig(models.Model):
    # 0 = Monday, 1 = Tuesday ... 6 = Sunday (Django default weekday mapping or 1-7)
    day_of_week = models.IntegerField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'weekend_configs'

class OfficeLocation(models.Model):
    name = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=10, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    radius_meters = models.IntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'office_locations'

class Attendance(models.Model):
    STATUS_CHOICES = {
        'PRESENT': 'Present',
        'ABSENT': 'Absent',
        'LATE': 'Late',
        'HALF_DAY': 'Half Day',
        'ON_LEAVE': 'On Leave',
    }

    CHECK_IN_METHOD_CHOICES = {
        'GPS': 'GPS',
        'BIOMETRIC_FINGERPRINT': 'Biometric Fingerprint',
        'DUAL_VERIFIED': 'Dual Verified (GPS + Fingerprint)',
        'MANUAL': 'Manual Entry',
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField()
    shift = models.IntegerField(default=1) # 1 Morning, 2 Evening
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['PRESENT']
    )
    check_in_method = models.CharField(
        max_length=50,
        choices=[(value, value) for value in CHECK_IN_METHOD_CHOICES.values()],
        default=CHECK_IN_METHOD_CHOICES['GPS']
    )
    biometric_device_id = models.CharField(max_length=100, null=True, blank=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    check_in_location_name = models.CharField(max_length=255, null=True, blank=True)
    check_out_location_name = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'attendances'
        unique_together = ('user', 'date', 'shift')

class SalaryStructure(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_structures')
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medical_benefits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    utility_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_ta_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'salary_structures'

class Payroll(models.Model):
    STATUS_CHOICES = {
        'DRAFT': 'Draft',
        'PENDING_APPROVAL': 'Pending Approval',
        'APPROVED': 'Approved',
        'PAID': 'Paid',
        'REJECTED': 'Rejected',
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payrolls')
    month = models.IntegerField()
    year = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['DRAFT']
    )
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='generated_payrolls')
    current_approver_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    absent_days = models.IntegerField(default=0)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medical_benefits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    utility_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    per_day_salary = models.DecimalField(max_digits=12, decimal_places=2)
    per_hour_salary = models.DecimalField(max_digits=12, decimal_places=2)
    unpaid_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_ta_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_tour_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loan_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payrolls'
        unique_together = ('user', 'month', 'year')

class PayrollApproval(models.Model):
    STATUS_CHOICES = {
        'PENDING': 'Pending',
        'APPROVED': 'Approved',
        'REJECTED': 'Rejected',
    }

    payroll = models.ForeignKey(Payroll, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['PENDING']
    )
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payroll_approvals'

class Loan(models.Model):
    STATUS_CHOICES = {
        'ACTIVE': 'Active',
        'CLOSED': 'Closed',
        'SUSPENDED': 'Suspended',
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loans')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    emi_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_months = models.IntegerField()
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    deduction_start_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['ACTIVE']
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'loans'

class TourAllowance(models.Model):
    STATUS_CHOICES = {
        'PENDING': 'Pending',
        'APPROVED': 'Approved',
        'REJECTED': 'Rejected',
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tour_allowances')
    date = models.DateField()
    from_location = models.CharField(max_length=255)
    to_location = models.CharField(max_length=255)
    mode_of_journey = models.CharField(max_length=100)
    da_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    file_url = models.URLField(max_length=500, null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['PENDING']
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tour_allowances'


class LeaveRequest(models.Model):
    LEAVE_TYPE_CHOICES = {
        'CASUAL': 'Casual Leave',
        'SICK': 'Sick Leave',
        'ANNUAL': 'Annual Leave',
        'MATERNITY': 'Maternity Leave',
        'PATERNITY': 'Paternity Leave',
        'UNPAID': 'Unpaid Leave (LWP)',
        'SPECIAL': 'Special Leave',
    }

    STATUS_CHOICES = {
        'PENDING': 'Pending',
        'APPROVED': 'Approved',
        'REJECTED': 'Rejected',
        'CANCELLED': 'Cancelled',
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(
        max_length=50,
        choices=[(value, value) for value in LEAVE_TYPE_CHOICES.values()],
        default=LEAVE_TYPE_CHOICES['CASUAL']
    )
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.IntegerField(default=1)
    reason = models.TextField()
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['PENDING']
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_leaves'
    )
    rejection_reason = models.TextField(null=True, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leave_requests'
        ordering = ['-applied_at']

    def __str__(self):
        return f"{self.user.username} - {self.leave_type} ({self.start_date} to {self.end_date}) [{self.status}]"

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            delta = (self.end_date - self.start_date).days + 1
            self.total_days = max(1, delta)
        super().save(*args, **kwargs)
