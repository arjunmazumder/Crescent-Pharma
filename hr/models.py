import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
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
    daily_ta_allowance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=(
            "DEPRECATED. Superseded by per-employee, per-component rates in EmployeeTARate. "
            "Retained for historical reference only; payroll no longer reads this field."
        )
    )
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'salary_structures'


class TAComponent(models.Model):
    """
    Catalogue of travelling-allowance heads an employee can be paid per working
    day, e.g. Transport, Meal, Hotel. Admin-managed, so new heads can be added
    without a schema change.
    """
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Short stable identifier, e.g. TRANSPORT, MEAL, HOTEL"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ta_components'
        ordering = ['display_order', 'code']
        verbose_name = "TA Component"
        verbose_name_plural = "TA Components"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper().replace(' ', '_')
        super().save(*args, **kwargs)


class EmployeeTARate(models.Model):
    """
    The daily amount a specific employee earns for a specific TA component.
    Effective-dated the same way SalaryStructure is, so raising a rate keeps
    the earlier one intact for past months.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ta_rates'
    )
    component = models.ForeignKey(
        TAComponent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_rates'
    )
    daily_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Amount earned per eligible working day for this component"
    )
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'employee_ta_rates'
        unique_together = ('user', 'component', 'effective_from')
        ordering = ['user', 'component', '-effective_from']
        verbose_name = "Employee TA Rate"
        verbose_name_plural = "Employee TA Rates"

    def __str__(self):
        comp_name = self.component.code if self.component else "General TA"
        return f"{self.user.username} - {comp_name}: {self.daily_amount}/day from {self.effective_from}"

    def clean(self):
        if self.daily_amount is not None and self.daily_amount < 0:
            raise ValidationError({'daily_amount': "Daily amount cannot be negative."})


class AllowanceBill(models.Model):
    """
    One month's TA and DA for one employee, paid separately from the payslip.

    TA comes from the employee's configured component rates multiplied by the
    days actually worked; DA comes from approved tour allowances. Holidays and
    weekly off-days earn neither.
    """

    STATUS_CHOICES = {
        'DRAFT': 'Draft',
        'PENDING_APPROVAL': 'Pending Approval',
        'APPROVED': 'Approved',
        'PAID': 'Paid',
        'REJECTED': 'Rejected',
    }

    # Statuses that must never be silently overwritten by regeneration.
    SETTLED_STATUSES = ('Approved', 'Paid')

    bill_number = models.CharField(max_length=50, unique=True, blank=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='allowance_bills'
    )
    month = models.IntegerField()
    year = models.IntegerField()
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['DRAFT']
    )
    eligible_days = models.IntegerField(
        default=0,
        help_text="Days actually worked, excluding holidays, off-days, leave and absence"
    )
    total_daily_ta = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_tour_da = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    accounting_voucher = models.ForeignKey(
        'accounting.Voucher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='allowance_bill_vouchers'
    )
    notes = models.TextField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='generated_allowance_bills'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_allowance_bills'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'allowance_bills'
        unique_together = ('user', 'month', 'year')
        ordering = ['-year', '-month', '-id']
        verbose_name = "TA/DA Bill"
        verbose_name_plural = "TA/DA Bills"

    def __str__(self):
        return f"{self.bill_number} - {self.user.username} ({self.month}/{self.year}) [{self.status}]"

    @property
    def is_settled(self):
        return self.status in self.SETTLED_STATUSES

    def save(self, *args, **kwargs):
        if not self.bill_number:
            year = self.year or timezone.now().year
            prefix = f"TADA-{year}-"
            with transaction.atomic():
                # Single aggregate rather than scanning the table in Python,
                # which is how the older models in this project do it.
                last = (
                    AllowanceBill.objects
                    .select_for_update()
                    .filter(bill_number__startswith=prefix)
                    .aggregate(highest=models.Max('bill_number'))['highest']
                )
                next_number = 1
                if last:
                    match = re.search(r'TADA-\d+-(\d+)$', last)
                    if match:
                        next_number = int(match.group(1)) + 1

                candidate = f"{prefix}{next_number:04d}"
                while AllowanceBill.objects.filter(bill_number=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.bill_number = candidate

        super().save(*args, **kwargs)


class AllowanceBillLine(models.Model):
    """A single readable row on the bill: one TA component, or one tour."""

    SOURCE_CHOICES = {
        'DAILY_RATE': 'Daily TA Component',
        'TOUR': 'Tour Allowance (DA)',
    }

    bill = models.ForeignKey(
        AllowanceBill,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    source = models.CharField(
        max_length=50,
        choices=[(value, value) for value in SOURCE_CHOICES.values()],
        default=SOURCE_CHOICES['DAILY_RATE']
    )
    component = models.ForeignKey(
        TAComponent,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='bill_lines',
        help_text="Set for daily TA lines; empty for tour lines"
    )
    tour_allowance = models.ForeignKey(
        # String reference: TourAllowance is declared later in this module.
        'hr.TourAllowance',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='bill_lines',
        help_text="Set for tour DA lines; empty for daily TA lines"
    )
    days = models.IntegerField(default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    description = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'allowance_bill_lines'
        ordering = ['source', 'id']
        verbose_name = "TA/DA Bill Line"
        verbose_name_plural = "TA/DA Bill Lines"

    def __str__(self):
        return f"{self.bill.bill_number}: {self.description or self.source} = {self.amount}"

class BonusType(models.Model):
    """
    A festival bonus, paid as a percentage of basic salary.

    Eid dates move with the lunar calendar, so there is no fixed month. The
    admin decides at payroll generation time whether that month's payroll
    carries a bonus and which one.
    """
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Short stable identifier, e.g. EID_UL_FITR, EID_UL_ADHA"
    )
    name = models.CharField(max_length=150)
    percentage_of_basic = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('100.00'),
        help_text="Percentage of basic salary paid as bonus, e.g. 100.00"
    )
    description = models.TextField(null=True, blank=True)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bonus_types'
        ordering = ['display_order', 'code']
        verbose_name = "Bonus Type"
        verbose_name_plural = "Bonus Types"

    def __str__(self):
        return f"{self.name} ({self.percentage_of_basic}% of basic)"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper().replace(' ', '_')
        super().save(*args, **kwargs)

    def clean(self):
        if self.percentage_of_basic is not None and self.percentage_of_basic < 0:
            raise ValidationError({'percentage_of_basic': "Percentage cannot be negative."})


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
    total_ta_allowance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="DEPRECATED. TA is paid on AllowanceBill; always 0 on new payrolls."
    )
    total_tour_allowance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="DEPRECATED. Tour DA is paid on AllowanceBill; always 0 on new payrolls."
    )
    loan_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bonus_type = models.ForeignKey(
        BonusType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payrolls',
        help_text="Set when this payroll was generated with a festival bonus"
    )
    bonus_percentage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text="Rate used at generation time. Kept as a snapshot so changing "
                  "the BonusType later does not rewrite past payslips."
    )
    total_bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)
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
    emi_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Fixed amount deducted from the employee's salary every month. Set by the admin."
    )
    total_months = models.IntegerField()
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    deduction_start_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=[(value, value) for value in STATUS_CHOICES.values()],
        default=STATUS_CHOICES['ACTIVE']
    )
    note = models.TextField(
        null=True,
        blank=True,
        help_text="Reason for the loan, agreed terms, or any administrative remarks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'loans'
        constraints = [
            # An employee may hold only one open loan at a time. Enforced in the
            # database so two concurrent requests cannot both pass the check.
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(remaining_amount__gt=0),
                name='unique_open_loan_per_user'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.amount} (Remaining: {self.remaining_amount}) [{self.status}]"

    def clean(self):
        errors = {}

        if self.amount is not None and self.amount <= 0:
            errors['amount'] = "Loan amount must be greater than zero."

        if self.emi_amount is not None and self.emi_amount <= 0:
            errors['emi_amount'] = "Monthly deduction amount must be greater than zero."

        if self.amount is not None and self.emi_amount is not None and self.emi_amount > self.amount:
            errors['emi_amount'] = (
                f"Monthly deduction ({self.emi_amount}) cannot be greater than the loan amount ({self.amount})."
            )

        if self.amount is not None and self.remaining_amount is not None and self.remaining_amount > self.amount:
            errors['remaining_amount'] = (
                f"Remaining amount ({self.remaining_amount}) cannot be greater than the loan amount ({self.amount})."
            )

        # One open loan per employee. Mirrors the database constraint above, but
        # produces a readable message instead of an IntegrityError.
        if self.user_id and (self.remaining_amount is None or self.remaining_amount > 0):
            open_loans = Loan.objects.filter(user_id=self.user_id, remaining_amount__gt=0)
            if self.pk:
                open_loans = open_loans.exclude(pk=self.pk)
            existing = open_loans.first()
            if existing:
                errors['user'] = (
                    f"This employee already has an open loan of {existing.amount} "
                    f"with {existing.remaining_amount} still outstanding. "
                    "A new loan can only be issued once the existing one is fully repaid."
                )

        if errors:
            raise ValidationError(errors)

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


# -----------------------------------------------------------------------------
# Live GPS Tracking Models (Field Marketing / MPO Live Tracking)
# -----------------------------------------------------------------------------

class UserLocationLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='location_logs'
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    location_name = models.CharField(max_length=255, null=True, blank=True, help_text="Human-readable reverse geocoded place name")
    accuracy = models.FloatField(null=True, blank=True, help_text="Accuracy radius in meters")
    speed = models.FloatField(null=True, blank=True, help_text="Movement speed in m/s")
    battery_level = models.IntegerField(null=True, blank=True, help_text="Device battery percentage")
    is_mock_location = models.BooleanField(default=False, help_text="True if fake/mock GPS app detected")
    recorded_at = models.DateTimeField(help_text="Device timestamp when GPS coordinate was captured")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_location_logs'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['user', 'recorded_at']),
        ]

    def __str__(self):
        return f"{self.user.username} @ ({self.latitude}, {self.longitude}) [{self.location_name or 'Unknown'}] at {self.recorded_at}"


class UserCurrentLocation(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='current_location'
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    location_name = models.CharField(max_length=255, null=True, blank=True, help_text="Human-readable reverse geocoded place name")
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    battery_level = models.IntegerField(null=True, blank=True)
    is_tracking_active = models.BooleanField(default=False, db_index=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_current_locations'

    def __str__(self):
        status_str = "ACTIVE" if self.is_tracking_active else "STOPPED"
        return f"{self.user.username} - {status_str} @ ({self.latitude}, {self.longitude}) [{self.location_name or 'Unknown'}]"


