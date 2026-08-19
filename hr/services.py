import math
from decimal import Decimal, ROUND_HALF_UP
import calendar
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from hr.models import (
    OfficeLocation, Attendance, SalaryStructure,
    Payroll, PayrollApproval, Loan, TourAllowance,
    Holiday, WeekendConfig, LeaveRequest
)
from core.models import Lookup

User = get_user_model()


def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculates the great-circle distance between two points on Earth in meters
    using the Haversine formula.
    """
    # Earth radius in meters
    R = 6371000.0
    
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    return R * c


class AttendanceService:
    @staticmethod
    def process_check_in(user, latitude=None, longitude=None, shift=1, notes="", check_in_method=None, biometric_device_id=None):
        """
        Validates geo-fencing (if enabled for user) and records Check-in or Check-out.
        Supports GPS, Biometric Fingerprint, and Dual Verification methods.
        """
        now = timezone.now()
        today = now.date()

        # 1. Geo-fencing validation if enabled on user profile
        if user.location_bounded_attendance:
            if latitude is None or longitude is None:
                raise ValueError("Location coordinates (latitude and longitude) are required for attendance.")
            
            active_locations = OfficeLocation.objects.filter(is_active=True)
            if not active_locations.exists():
                raise ValueError("No active office locations configured. Please contact HR.")
            
            is_inside_office = False
            nearest_distance = float('inf')
            matched_office_name = None

            for office in active_locations:
                dist = calculate_haversine_distance(latitude, longitude, office.latitude, office.longitude)
                if dist < nearest_distance:
                    nearest_distance = dist
                if dist <= office.radius_meters:
                    is_inside_office = True
                    matched_office_name = office.name
                    break
            
            if not is_inside_office:
                raise ValueError(
                    f"Geo-fencing failed: You are {nearest_distance:.1f} meters away from the nearest office boundary."
                )
        else:
            matched_office_name = "Remote / Unbounded"

        # Determine method
        method = check_in_method or Attendance.CHECK_IN_METHOD_CHOICES['GPS']
        if biometric_device_id and not check_in_method:
            method = Attendance.CHECK_IN_METHOD_CHOICES['BIOMETRIC_FINGERPRINT']

        # 2. Check existing attendance for today & shift
        attendance = Attendance.objects.filter(user=user, date=today, shift=shift).first()
        if attendance:
            # If already checked in but not checked out, record check out
            if not attendance.check_out_time:
                attendance.check_out_time = now
                attendance.check_out_location_name = matched_office_name
                if notes:
                    attendance.notes = f"{attendance.notes or ''} | Out Note: {notes}".strip()
                if biometric_device_id:
                    attendance.biometric_device_id = biometric_device_id
                attendance.save()
                return attendance, "Check-out recorded successfully."
            else:
                return attendance, "Attendance already completed for this shift today."
        else:
            # New Check-in
            attendance = Attendance.objects.create(
                user=user,
                date=today,
                shift=shift,
                status=Attendance.STATUS_CHOICES['PRESENT'],
                check_in_method=method,
                biometric_device_id=biometric_device_id,
                check_in_time=now,
                latitude=latitude,
                longitude=longitude,
                check_in_location_name=matched_office_name,
                notes=notes or "Normal check-in"
            )
            return attendance, "Check-in recorded successfully."


class PayrollService:
    @staticmethod
    def calculate_user_payroll(user, month, year, generated_by=None, current_approver_role=None):
        """
        Computes monthly payroll for a specific user based on SalaryStructure,
        working days, absent days, active loans, and approved tour allowances.
        """
        # 1. Fetch latest active SalaryStructure
        salary_structure = SalaryStructure.objects.filter(
            user=user,
            effective_from__lte=date(year, month, calendar.monthrange(year, month)[1])
        ).order_by('-effective_from').first()

        if not salary_structure:
            raise ValueError(f"No active SalaryStructure found for user '{user.username}'.")

        base_salary = Decimal(str(salary_structure.base_salary))
        housing_allowance = Decimal(str(salary_structure.housing_allowance))
        transport_allowance = Decimal(str(salary_structure.transport_allowance))
        medical_benefits = Decimal(str(salary_structure.medical_benefits))
        utility_allowance = Decimal(str(salary_structure.utility_allowance))

        # 2. Determine total working days in the month
        _, total_days_in_month = calendar.monthrange(year, month)
        holidays_in_month = set(Holiday.objects.filter(
            date__year=year, date__month=month
        ).values_list('date', flat=True))
        
        active_weekends = set(WeekendConfig.objects.filter(
            is_active=True
        ).values_list('day_of_week', flat=True))

        working_days_count = 0
        for day in range(1, total_days_in_month + 1):
            curr_date = date(year, month, day)
            # Skip if public holiday or weekend
            if curr_date in holidays_in_month:
                continue
            if curr_date.weekday() in active_weekends:
                continue
            working_days_count += 1

        if working_days_count == 0:
            working_days_count = total_days_in_month # Fallback safety

        # 3. Calculate per day & per hour salary
        per_day_salary = (base_salary / Decimal(working_days_count)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        per_hour_salary = (per_day_salary / Decimal('8.0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 4. Count Absent days in this month
        absent_days = Attendance.objects.filter(
            user=user,
            date__year=year,
            date__month=month,
            status=Attendance.STATUS_CHOICES['ABSENT']
        ).values('date').distinct().count()
        unpaid_deduction = (Decimal(absent_days) * per_day_salary).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 5. Aggregate approved Tour Allowances
        tour_qs = TourAllowance.objects.filter(
            user=user,
            date__year=year,
            date__month=month,
            status=TourAllowance.STATUS_CHOICES['APPROVED']
        )
        
        total_tour_allowance = Decimal('0.00')
        for t in tour_qs:
            total_tour_allowance += Decimal(str(t.total_amount))
        total_tour_allowance = total_tour_allowance.quantize(Decimal('0.01'))

        # Daily TA allowance from structure
        daily_ta = Decimal(str(salary_structure.daily_ta_allowance))
        present_days = working_days_count - absent_days
        total_ta_allowance = (daily_ta * Decimal(max(0, present_days))).quantize(Decimal('0.01'))

        # 6. Check Active Loans & Calculate EMI deduction
        active_loan = Loan.objects.filter(
            user=user,
            remaining_amount__gt=0,
            deduction_start_date__lte=date(year, month, total_days_in_month)
        ).first()

        loan_deduction = Decimal('0.00')
        if active_loan:
            emi = Decimal(str(active_loan.emi_amount))
            remaining = Decimal(str(active_loan.remaining_amount))
            loan_deduction = min(emi, remaining).quantize(Decimal('0.01'))

        # 7. Total Payable Salary Amount
        gross_earnings = (base_salary + housing_allowance + transport_allowance +
                          medical_benefits + utility_allowance + total_ta_allowance + total_tour_allowance)
        total_deductions = unpaid_deduction + loan_deduction
        net_payable = max(Decimal('0.00'), gross_earnings - total_deductions).quantize(Decimal('0.01'))

        # Determine default approver role if not specified
        from core.models import Role
        if current_approver_role is None:
            current_approver_role = Role.objects.filter(role_name__icontains='Admin').first() or Role.objects.first()

        with transaction.atomic():
            payroll, created = Payroll.objects.update_or_create(
                user=user,
                month=month,
                year=year,
                defaults={
                    'amount': net_payable,
                    'status': Payroll.STATUS_CHOICES['DRAFT'],
                    'generated_by': generated_by,
                    'current_approver_role': current_approver_role,
                    'absent_days': absent_days,
                    'base_salary': base_salary,
                    'housing_allowance': housing_allowance,
                    'transport_allowance': transport_allowance,
                    'medical_benefits': medical_benefits,
                    'utility_allowance': utility_allowance,
                    'per_day_salary': per_day_salary,
                    'per_hour_salary': per_hour_salary,
                    'unpaid_deduction': unpaid_deduction,
                    'total_ta_allowance': total_ta_allowance,
                    'total_tour_allowance': total_tour_allowance,
                    'loan_deduction': loan_deduction
                }
            )

        return payroll


class LeaveService:
    @staticmethod
    def approve_leave(leave_request, approved_by):
        """
        Marks leave request as Approved, and automatically creates or updates
        Attendance records as 'On Leave' for each working day in the date range.
        """
        now = timezone.now()
        leave_request.status = LeaveRequest.STATUS_CHOICES['APPROVED']
        leave_request.approved_by = approved_by
        leave_request.approved_at = now
        leave_request.save()

        # Iterate through all dates in the range and mark attendance as 'On Leave'
        curr = leave_request.start_date
        while curr <= leave_request.end_date:
            is_holiday = Holiday.objects.filter(date=curr).exists()
            is_weekend = WeekendConfig.objects.filter(day_of_week=curr.weekday(), is_active=True).exists()

            # Only mark working days
            if not is_holiday and not is_weekend:
                Attendance.objects.update_or_create(
                    user=leave_request.user,
                    date=curr,
                    shift=1,
                    defaults={
                        'status': Attendance.STATUS_CHOICES['ON_LEAVE'],
                        'notes': f"Approved {leave_request.leave_type} (Reason: {leave_request.reason})"
                    }
                )
            curr += timedelta(days=1)

        return leave_request

    @staticmethod
    def reject_leave(leave_request, rejected_by, rejection_reason=""):
        """
        Marks leave request as Rejected with optional rejection reason.
        """
        leave_request.status = LeaveRequest.STATUS_CHOICES['REJECTED']
        leave_request.approved_by = rejected_by
        leave_request.rejection_reason = rejection_reason
        leave_request.approved_at = timezone.now()
        leave_request.save()
        return leave_request

