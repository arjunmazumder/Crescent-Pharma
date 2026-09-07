import math
from decimal import Decimal, ROUND_HALF_UP
import calendar
from datetime import date, timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from django.contrib.auth import get_user_model
from hr.models import (
    OfficeLocation, Attendance, SalaryStructure,
    Payroll, PayrollApproval, Loan, TourAllowance,
    Holiday, WeekendConfig, LeaveRequest,
    TAComponent, EmployeeTARate, AllowanceBill, AllowanceBillLine,
    BonusType
)
from core.models import Lookup

import json
import urllib.request
import urllib.error

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


def reverse_geocode_coordinates(latitude, longitude):
    """
    Reverse geocodes GPS coordinates into a human-readable real-world address/place name.
    Uses OpenStreetMap Nominatim with graceful timeout and fallback.
    """
    if latitude is None or longitude is None:
        return None

    try:
        lat = float(latitude)
        lon = float(longitude)
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'CrescentPharmaERP/1.0 (admin@crescentpharma.com)'
            }
        )
        with urllib.request.urlopen(req, timeout=3.0) as response:
            if response.status == 200:
                payload = json.loads(response.read().decode('utf-8'))
                address = payload.get('address', {})

                road = address.get('road') or address.get('street')
                suburb = address.get('suburb') or address.get('neighbourhood') or address.get('residential') or address.get('quarter')
                city = address.get('city') or address.get('town') or address.get('county') or address.get('state_district') or address.get('state')

                parts = []
                if road:
                    parts.append(road)
                if suburb and suburb not in parts:
                    parts.append(suburb)
                if city and city not in parts:
                    parts.append(city)

                if parts:
                    return ", ".join(parts[:3])

                display_name = payload.get('display_name')
                if display_name:
                    display_parts = [p.strip() for p in display_name.split(',') if p.strip()]
                    return ", ".join(display_parts[:3])
    except Exception:
        pass

    try:
        return f"Field ({float(latitude):.4f}, {float(longitude):.4f})"
    except Exception:
        return "Field Location"


class AttendanceService:
    @staticmethod
    def process_check_in(user, latitude=None, longitude=None, shift=1, notes="", check_in_method=None, biometric_device_id=None, location_name=None):
        """
        Validates geo-fencing (if enabled for user) and records Check-in or Check-out.
        Supports GPS, Biometric Fingerprint, Dual Verification, and Reverse-Geocoded real location names.
        """
        now = timezone.now()
        today = now.date()

        active_locations = OfficeLocation.objects.filter(is_active=True)

        # 1. Geo-fencing validation if enabled on user profile
        if user.location_bounded_attendance:
            if latitude is None or longitude is None:
                raise ValueError("Location coordinates (latitude and longitude) are required for attendance.")
            
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
            # For remote / field staff:
            if location_name:
                matched_office_name = location_name
            elif latitude is not None and longitude is not None:
                # Check if coords happen to be inside a known office
                is_near_office = False
                for office in active_locations:
                    dist = calculate_haversine_distance(latitude, longitude, office.latitude, office.longitude)
                    if dist <= office.radius_meters:
                        matched_office_name = f"{office.name} (Field Staff)"
                        is_near_office = True
                        break

                # If not inside a known office, reverse geocode to get actual place/area name
                if not is_near_office:
                    matched_office_name = reverse_geocode_coordinates(latitude, longitude)
            else:
                matched_office_name = "Remote / Field"

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
                if latitude is not None and longitude is not None:
                    attendance.latitude = latitude
                    attendance.longitude = longitude
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
    def calculate_user_payroll(
        user, month, year, generated_by=None, current_approver_role=None,
        include_bonus=False, bonus_type=None
    ):
        """
        Computes monthly payroll for a specific user based on SalaryStructure,
        working days, absent days, and active loans.

        TA and DA are not part of salary; they are settled on the AllowanceBill.

        A festival bonus is included only when include_bonus is True, since Eid
        dates move each year and the admin decides which payroll run carries it.
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

        # 5. TA and DA are no longer part of salary.
        # They are paid on their own monthly document (AllowanceBill), which has
        # its own approval and its own ledger voucher. These two fields stay on
        # Payroll as zeros so existing consumers of the payslip response keep
        # working; they are deprecated and will be dropped in a later release.
        total_ta_allowance = Decimal('0.00')
        total_tour_allowance = Decimal('0.00')

        # 6. Check Active Loans & Calculate EMI deduction
        # An employee may hold only one open loan at a time (enforced by a database
        # constraint on Loan), but order explicitly so this stays deterministic.
        active_loan = Loan.objects.filter(
            user=user,
            remaining_amount__gt=0,
            deduction_start_date__lte=date(year, month, total_days_in_month)
        ).order_by('deduction_start_date', 'id').first()

        loan_deduction = Decimal('0.00')
        if active_loan:
            emi = Decimal(str(active_loan.emi_amount))
            remaining = Decimal(str(active_loan.remaining_amount))
            loan_deduction = min(emi, remaining).quantize(Decimal('0.01'))

        # 7. Festival bonus, as a percentage of basic salary. Every employee on
        # the run receives it: there is no length-of-service or attendance test.
        resolved_bonus_type = None
        bonus_percentage = Decimal('0.00')
        total_bonus = Decimal('0.00')

        if include_bonus:
            resolved_bonus_type = bonus_type
            if resolved_bonus_type is None:
                active_types = list(BonusType.objects.filter(is_active=True)[:2])
                if len(active_types) == 1:
                    resolved_bonus_type = active_types[0]
                elif not active_types:
                    raise ValueError(
                        "Cannot include a bonus: no active BonusType is configured."
                    )
                else:
                    raise ValueError(
                        "More than one active BonusType exists. Specify which bonus to pay."
                    )

            bonus_percentage = Decimal(str(resolved_bonus_type.percentage_of_basic or '0.00'))
            total_bonus = (
                base_salary * bonus_percentage / Decimal('100')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 8. Total Payable Salary Amount.
        # TA and DA are deliberately absent: they are settled on the TA/DA bill.
        gross_earnings = (base_salary + housing_allowance + transport_allowance +
                          medical_benefits + utility_allowance + total_bonus)
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
                    'loan_deduction': loan_deduction,
                    'bonus_type': resolved_bonus_type,
                    'bonus_percentage': bonus_percentage,
                    'total_bonus': total_bonus
                }
            )

        return payroll


class AllowanceEligibilityService:
    """
    Decides which days and which tours actually earn an allowance.

    The rule: allowances are earned only on days the employee genuinely worked
    in the field. Public holidays, weekly off-days, approved leave and absences
    all earn nothing.

    Note this counts *observed* attendance rather than deriving a day count from
    the calendar. Deriving is what the old payroll TA calculation did, and it
    quietly paid TA for approved-leave days, because leave is not absence.
    """

    ATTENDED_STATUSES = [
        Attendance.STATUS_CHOICES['PRESENT'],
        Attendance.STATUS_CHOICES['LATE'],
    ]

    @staticmethod
    def get_calendar(year=None, month=None):
        """
        Returns (holiday_dates, active_weekend_weekdays). Restricted to one
        month when year and month are given, otherwise every holiday on record.
        """
        holiday_qs = Holiday.objects.all()
        if year and month:
            holiday_qs = holiday_qs.filter(date__year=year, date__month=month)

        holidays = set(holiday_qs.values_list('date', flat=True))
        weekend_days = set(
            WeekendConfig.objects.filter(is_active=True).values_list('day_of_week', flat=True)
        )
        return holidays, weekend_days

    @staticmethod
    def get_non_payable_reason(target_date, holidays=None, weekend_days=None):
        """
        Returns None when the date earns an allowance, or a readable reason when
        it does not. Pass pre-loaded sets to avoid a query per row.
        """
        if target_date is None:
            return "No date recorded."

        if holidays is None:
            holiday = Holiday.objects.filter(date=target_date).first()
            if holiday:
                return f"{target_date} is a public holiday ({holiday.name})."
        elif target_date in holidays:
            return f"{target_date} is a public holiday."

        if weekend_days is None:
            weekend_days = set(
                WeekendConfig.objects.filter(is_active=True).values_list('day_of_week', flat=True)
            )
        if target_date.weekday() in weekend_days:
            return f"{target_date} is a weekly off-day ({target_date.strftime('%A')})."

        return None

    @staticmethod
    def get_eligible_days(user, month, year):
        """
        The dates in the month on which the employee attended work and which are
        neither a public holiday nor a weekly off-day. Returned sorted.
        """
        holidays, weekend_days = AllowanceEligibilityService.get_calendar(year, month)

        attended = (
            Attendance.objects
            .filter(
                user=user,
                date__year=year,
                date__month=month,
                status__in=AllowanceEligibilityService.ATTENDED_STATUSES
            )
            .values_list('date', flat=True)
            .distinct()
        )

        return [
            day for day in sorted(set(attended))
            if day not in holidays and day.weekday() not in weekend_days
        ]

    @staticmethod
    def filter_payable_tours(user, month, year):
        """Approved tours in the month, excluding any dated on a holiday or off-day."""
        holidays, weekend_days = AllowanceEligibilityService.get_calendar(year, month)

        tours = TourAllowance.objects.filter(
            user=user,
            date__year=year,
            date__month=month,
            status=TourAllowance.STATUS_CHOICES['APPROVED']
        ).order_by('date', 'id')

        return [
            tour for tour in tours
            if AllowanceEligibilityService.get_non_payable_reason(
                tour.date, holidays, weekend_days
            ) is None
        ]


class TAConfigService:
    """
    Resolves which TA rates apply to an employee on a given date.

    Rates are effective-dated, so an employee can have several rows per
    component over time. Only the most recent row on or before the target date
    counts, mirroring how SalaryStructure is resolved for payroll.
    """

    @staticmethod
    def get_effective_rates(user, on_date=None):
        """
        Returns the applicable EmployeeTARate for each active component,
        ordered by the component's display order. Components the employee has
        no rate for are simply absent.
        """
        on_date = on_date or timezone.now().date()

        rows = (
            EmployeeTARate.objects
            .filter(
                user=user,
                is_active=True,
                effective_from__lte=on_date,
            )
            .filter(Q(component__is_active=True) | Q(component__isnull=True))
            .select_related('component')
            .order_by('component__display_order', 'component_id', '-effective_from', '-id')
        )

        # Rows arrive newest-first within each component, so the first row seen
        # for a component is the one in force on that date.
        effective = {}
        for row in rows:
            if row.component_id not in effective:
                effective[row.component_id] = row

        return list(effective.values())

    @staticmethod
    def get_total_daily_rate(user, on_date=None):
        """Sum of every applicable component rate for one working day."""
        rates = TAConfigService.get_effective_rates(user, on_date=on_date)
        total = sum((Decimal(str(r.daily_amount)) for r in rates), Decimal('0.00'))
        return total.quantize(Decimal('0.01'))


class AllowanceBillService:
    """
    Builds and settles the monthly TA/DA bill, which is paid separately from
    the payslip.
    """

    @staticmethod
    def generate(user, month, year, generated_by=None):
        """
        Rebuilds this employee's bill for the month from current attendance,
        rates and approved tours.

        Refuses to touch an APPROVED or PAID bill. Regenerating a settled
        document is how payroll silently reverts a paid month today; this does
        not repeat that.
        """
        month = int(month)
        year = int(year)

        existing = AllowanceBill.objects.filter(user=user, month=month, year=year).first()
        if existing and existing.is_settled:
            raise ValueError(
                f"Bill {existing.bill_number} for {month}/{year} is already {existing.status} "
                "and cannot be regenerated."
            )

        eligible_days = AllowanceEligibilityService.get_eligible_days(user, month, year)
        day_count = len(eligible_days)

        # Rates are resolved as at the last eligible day, so a mid-month raise
        # applies from the month it took effect.
        rate_date = eligible_days[-1] if eligible_days else date(
            year, month, calendar.monthrange(year, month)[1]
        )
        rates = TAConfigService.get_effective_rates(user, on_date=rate_date)
        payable_tours = AllowanceEligibilityService.filter_payable_tours(user, month, year)

        with transaction.atomic():
            bill, _ = AllowanceBill.objects.update_or_create(
                user=user,
                month=month,
                year=year,
                defaults={
                    'status': AllowanceBill.STATUS_CHOICES['DRAFT'],
                    'eligible_days': day_count,
                    'generated_by': generated_by,
                    'rejection_reason': None,
                }
            )

            # Rebuilt from scratch every time, so removing a tour or a rate
            # cannot leave an orphan line behind.
            bill.lines.all().delete()

            total_ta = Decimal('0.00')
            for rate in rates:
                amount = (Decimal(str(rate.daily_amount)) * Decimal(day_count)).quantize(Decimal('0.01'))
                if amount <= Decimal('0.00'):
                    continue
                comp_name = rate.component.name if rate.component else "Daily TA Allowance"
                AllowanceBillLine.objects.create(
                    bill=bill,
                    source=AllowanceBillLine.SOURCE_CHOICES['DAILY_RATE'],
                    component=rate.component,
                    days=day_count,
                    rate=rate.daily_amount,
                    amount=amount,
                    description=f"{comp_name} @ {rate.daily_amount}/day x {day_count} day(s)"
                )
                total_ta += amount

            total_da = Decimal('0.00')
            for tour in payable_tours:
                amount = Decimal(str(tour.total_amount or '0.00')).quantize(Decimal('0.01'))
                if amount <= Decimal('0.00'):
                    continue
                AllowanceBillLine.objects.create(
                    bill=bill,
                    source=AllowanceBillLine.SOURCE_CHOICES['TOUR'],
                    tour_allowance=tour,
                    days=1,
                    rate=amount,
                    amount=amount,
                    description=f"Tour {tour.from_location} to {tour.to_location} on {tour.date} ({tour.mode_of_journey})"
                )
                total_da += amount

            bill.total_daily_ta = total_ta.quantize(Decimal('0.01'))
            bill.total_tour_da = total_da.quantize(Decimal('0.01'))
            bill.total_amount = (total_ta + total_da).quantize(Decimal('0.01'))
            bill.save()

        return bill

    @staticmethod
    def approve(bill, approved_by, notes=""):
        if bill.status == AllowanceBill.STATUS_CHOICES['PAID']:
            raise ValueError(f"Bill {bill.bill_number} is already PAID.")
        if bill.status == AllowanceBill.STATUS_CHOICES['APPROVED']:
            raise ValueError(f"Bill {bill.bill_number} is already APPROVED.")

        bill.status = AllowanceBill.STATUS_CHOICES['APPROVED']
        bill.approved_by = approved_by
        bill.approved_at = timezone.now()
        if notes:
            bill.notes = notes
        bill.save(update_fields=['status', 'approved_by', 'approved_at', 'notes', 'updated_at'])
        return bill

    @staticmethod
    def reject(bill, rejected_by, reason=""):
        if bill.status == AllowanceBill.STATUS_CHOICES['PAID']:
            raise ValueError(f"Bill {bill.bill_number} is already PAID and cannot be rejected.")

        bill.status = AllowanceBill.STATUS_CHOICES['REJECTED']
        bill.approved_by = rejected_by
        bill.approved_at = timezone.now()
        bill.rejection_reason = reason or "Rejected by approver"
        bill.save(update_fields=[
            'status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'
        ])
        return bill

    @staticmethod
    def disburse(bill, user=None):
        """
        Marks the bill PAID and posts it to the General Ledger:
        Debit 6120 Travel & Tour Allowances, Credit 1112 Bank.
        """
        if bill.status == AllowanceBill.STATUS_CHOICES['PAID']:
            raise ValueError(f"Bill {bill.bill_number} is already PAID.")
        if bill.status != AllowanceBill.STATUS_CHOICES['APPROVED']:
            raise ValueError(
                f"Bill {bill.bill_number} must be APPROVED before disbursement. "
                f"Current status: {bill.status}."
            )
        if bill.total_amount <= Decimal('0.00'):
            raise ValueError(f"Bill {bill.bill_number} has no payable amount.")

        with transaction.atomic():
            bill.status = AllowanceBill.STATUS_CHOICES['PAID']
            bill.paid_at = timezone.now()
            bill.save(update_fields=['status', 'paid_at', 'updated_at'])

            try:
                from accounting.services import AccountingIntegrationService
                voucher = AccountingIntegrationService.post_allowance_bill_disbursement(
                    bill=bill, user=user
                )
                bill.accounting_voucher = voucher
                bill.save(update_fields=['accounting_voucher', 'updated_at'])
            except ValueError:
                logger.exception(
                    "Failed to post TA/DA voucher for bill %s (%s, %s/%s). "
                    "The bill was marked PAID but the General Ledger was not updated.",
                    bill.bill_number, bill.user.username, bill.month, bill.year
                )

        return bill


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


# -----------------------------------------------------------------------------
# 4. TrackingService (Live GPS Tracking, Batch Sync & Route Playback)
# -----------------------------------------------------------------------------

class TrackingService:
    @staticmethod
    def record_ping(
        user,
        latitude,
        longitude,
        location_name=None,
        accuracy=None,
        speed=None,
        battery_level=None,
        is_mock_location=False,
        recorded_at=None
    ):
        """
        Records a single live GPS ping from an MPO device.
        Updates UserCurrentLocation and creates a historical UserLocationLog entry.
        """
        from hr.models import UserLocationLog, UserCurrentLocation
        now = timezone.now()
        timestamp = recorded_at or now

        # Reverse geocode place name if not provided
        resolved_location_name = location_name or reverse_geocode_coordinates(latitude, longitude)

        with transaction.atomic():
            # 1. Update or create Current Live Location
            current_loc, _ = UserCurrentLocation.objects.update_or_create(
                user=user,
                defaults={
                    'latitude': latitude,
                    'longitude': longitude,
                    'location_name': resolved_location_name,
                    'accuracy': accuracy,
                    'speed': speed,
                    'battery_level': battery_level,
                    'is_tracking_active': True
                }
            )

            # 2. Insert into historical timeline log
            log = UserLocationLog.objects.create(
                user=user,
                latitude=latitude,
                longitude=longitude,
                location_name=resolved_location_name,
                accuracy=accuracy,
                speed=speed,
                battery_level=battery_level,
                is_mock_location=is_mock_location,
                recorded_at=timestamp
            )

        return current_loc, log

    @staticmethod
    def record_batch_sync(user, locations_data):
        """
        Bulk processes offline cached GPS locations sent in batch when network is restored.
        """
        from hr.models import UserLocationLog, UserCurrentLocation
        now = timezone.now()
        logs_to_create = []
        latest_loc = None

        with transaction.atomic():
            for item in locations_data:
                lat = item.get('latitude') or item.get('lat')
                lon = item.get('longitude') or item.get('lon') or item.get('lng')
                loc_name = item.get('location_name') or item.get('locationName')
                acc = item.get('accuracy')
                spd = item.get('speed')
                bat = item.get('battery_level') or item.get('batteryLevel')
                mock = item.get('is_mock_location', False) or item.get('isMockLocation', False)
                rec = item.get('recorded_at') or item.get('recordedAt') or now

                log_entry = UserLocationLog(
                    user=user,
                    latitude=lat,
                    longitude=lon,
                    location_name=loc_name,
                    accuracy=acc,
                    speed=spd,
                    battery_level=bat,
                    is_mock_location=mock,
                    recorded_at=rec
                )
                logs_to_create.append(log_entry)
                latest_loc = (lat, lon, loc_name, acc, spd, bat)

            if logs_to_create:
                UserLocationLog.objects.bulk_create(logs_to_create)

            # Update latest known current location if available
            if latest_loc:
                resolved_name = latest_loc[2] or reverse_geocode_coordinates(latest_loc[0], latest_loc[1])
                UserCurrentLocation.objects.update_or_create(
                    user=user,
                    defaults={
                        'latitude': latest_loc[0],
                        'longitude': latest_loc[1],
                        'location_name': resolved_name,
                        'accuracy': latest_loc[3],
                        'speed': latest_loc[4],
                        'battery_level': latest_loc[5],
                        'is_tracking_active': True
                    }
                )

        return len(logs_to_create)

    @staticmethod
    def toggle_tracking(user, action=None):
        """
        Starts or stops live tracking for a user.
        action can be 'START', 'STOP', or None (which toggles the state).
        """
        from hr.models import UserCurrentLocation
        current_loc, created = UserCurrentLocation.objects.get_or_create(
            user=user,
            defaults={
                'latitude': Decimal('23.8103310'),
                'longitude': Decimal('90.4125210'),
                'location_name': 'Dhaka Head Office',
                'is_tracking_active': False
            }
        )

        if action:
            new_state = action.upper() in ['START', 'TRUE', '1', 'ACTIVE']
        else:
            new_state = not current_loc.is_tracking_active

        current_loc.is_tracking_active = new_state
        current_loc.save(update_fields=['is_tracking_active'])
        return current_loc

    @staticmethod
    def get_mpo_route(user, date_param=None):
        """
        Retrieves the chronological GPS breadcrumb points for an MPO on a specific date.
        Calculates total distance travelled in Kilometers using Haversine algorithm.
        Includes human-readable reverse-geocoded locationName for each point.
        """
        import math
        from hr.models import UserLocationLog

        target_date = date_param or timezone.now().date()
        logs = UserLocationLog.objects.filter(
            user=user,
            recorded_at__date=target_date
        ).order_by('recorded_at')

        points = []
        total_distance_km = 0.0
        prev_point = None

        for log in logs:
            lat = float(log.latitude)
            lon = float(log.longitude)

            if prev_point is not None:
                # Haversine distance
                lat1, lon1 = prev_point
                lat2, lon2 = lat, lon
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                segment_km = 6371.0 * c
                # Filter out GPS noise / teleport jumps > 50km
                if segment_km < 50.0:
                    total_distance_km += segment_km

            prev_point = (lat, lon)

            loc_name = log.location_name
            if not loc_name:
                loc_name = reverse_geocode_coordinates(log.latitude, log.longitude)
                if loc_name:
                    try:
                        log.location_name = loc_name
                        log.save(update_fields=['location_name'])
                    except Exception:
                        pass

            points.append({
                'id': log.id,
                'latitude': str(log.latitude),
                'longitude': str(log.longitude),
                'locationName': loc_name or f"({log.latitude}, {log.longitude})",
                'accuracy': log.accuracy,
                'speed': log.speed,
                'batteryLevel': log.battery_level,
                'isMockLocation': log.is_mock_location,
                'recordedAt': log.recorded_at.isoformat()
            })

        return {
            'userId': user.id,
            'username': user.username,
            'fullName': user.get_full_name() or user.username,
            'date': str(target_date),
            'totalPoints': len(points),
            'totalDistanceKm': round(total_distance_km, 2),
            'points': points
        }

    @staticmethod
    def get_live_team_status():
        """
        Returns real-time location and tracking status of all active field marketing staff.
        """
        from hr.models import UserCurrentLocation
        active_locations = UserCurrentLocation.objects.select_related('user', 'user__role').all().order_by('-last_updated_at')

        team = []
        for loc in active_locations:
            loc_name = loc.location_name or reverse_geocode_coordinates(loc.latitude, loc.longitude)
            team.append({
                'userId': loc.user.id,
                'username': loc.user.username,
                'fullName': loc.user.get_full_name() or loc.user.username,
                'employeeId': getattr(loc.user, 'employee_id', None),
                'role': loc.user.role.role_name if loc.user.role else 'MPO',
                'contact': getattr(loc.user, 'contact', None),
                'latitude': str(loc.latitude),
                'longitude': str(loc.longitude),
                'locationName': loc_name or f"({loc.latitude}, {loc.longitude})",
                'accuracy': loc.accuracy,
                'speed': loc.speed,
                'batteryLevel': loc.battery_level,
                'isTrackingActive': loc.is_tracking_active,
                'lastUpdatedAt': loc.last_updated_at.isoformat()
            })

        return {
            'totalStaffCount': len(team),
            'activeTrackingCount': sum(1 for t in team if t['isTrackingActive']),
            'staff': team
        }



