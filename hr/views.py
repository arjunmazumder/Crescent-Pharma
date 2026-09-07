import logging
import datetime
from django.utils.dateparse import parse_date
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import Role
from hr.models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest, UserLocationLog, UserCurrentLocation,
    TAComponent, EmployeeTARate, AllowanceBill, BonusType
)
from hr.services import (
    AttendanceService, PayrollService, LeaveService, TrackingService,
    TAConfigService, AllowanceBillService
)
from hr.serializers import (
    HolidaySerializer, WeekendConfigSerializer,
    OfficeLocationSerializer, SalaryStructureSerializer, PayrollApprovalSerializer,
    AttendanceSerializer, PayrollSerializer, LoanSerializer, TourAllowanceSerializer,
    LeaveRequestSerializer, UserLocationPingSerializer, UserLocationBatchSyncSerializer,
    UserCurrentLocationSerializer, UserLocationLogSerializer,
    TAComponentSerializer, EmployeeTARateSerializer, AllowanceBillSerializer,
    AllowanceBillGenerateSerializer, AllowanceBillRejectSerializer,
    BonusTypeSerializer
)

User = get_user_model()

logger = logging.getLogger(__name__)



def _resolve_bonus_request(request):
    """
    Reads the with-bonus / without-bonus choice off a payroll generate request.
    Returns (include_bonus, bonus_type) or raises ValueError with a readable message.
    """
    raw = request.data.get('includeBonus')
    if raw is None:
        raw = request.data.get('include_bonus')
    include_bonus = str(raw).strip().lower() in ('true', '1', 'yes') if raw is not None else False

    if not include_bonus:
        return False, None

    bonus_type_id = request.data.get('bonusTypeId') or request.data.get('bonus_type_id')
    if bonus_type_id:
        bonus_type = BonusType.objects.filter(id=bonus_type_id, is_active=True).first()
        if not bonus_type:
            raise ValueError(f"Active bonus type with ID {bonus_type_id} not found.")
        return True, bonus_type

    # No type given: fall back only when the choice is unambiguous.
    active = list(BonusType.objects.filter(is_active=True)[:2])
    if not active:
        raise ValueError("Cannot include a bonus: no active bonus type is configured.")
    if len(active) > 1:
        raise ValueError("More than one active bonus type exists. Send bonusTypeId to choose one.")
    return True, active[0]


@extend_schema(tags=['HR - Attendance'])
class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all().select_related('user')
    serializer_class = AttendanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id', 'notes', 'check_in_location_name', 'check_out_location_name']
    filterset_fields = ['user', 'date', 'shift', 'status']
    ordering_fields = ['id', 'date', 'check_in_time', 'check_out_time']
    ordering = ['-date', '-check_in_time']
    
    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset.all().order_by('-date', '-check_in_time')
        return self.queryset.filter(user=self.request.user).order_by('-date', '-check_in_time')
        
    @extend_schema(
        tags=['HR - Attendance'],
        summary='Employee Check-in / Check-out',
        description='Records employee attendance with geo-fencing validation, dual-shift tracking, and biometric device support.',
        examples=[
            OpenApiExample(
                'Geo-fenced Check-in Example',
                value={
                    'latitude': 23.81033100,
                    'longitude': 90.41252100,
                    'shift': 1,
                    'check_in_method': 'GPS',
                    'notes': 'On-time arrival at head office'
                },
                request_only=True
            )
        ]
    )
    @action(detail=False, methods=['post'], url_path='check-in')
    def check_in(self, request):
        lat = request.data.get('latitude') or request.data.get('lat')
        lon = request.data.get('longitude') or request.data.get('lng') or request.data.get('long')
        shift = int(request.data.get('shift', 1))
        notes = request.data.get('notes', '')
        check_in_method = request.data.get('check_in_method') or request.data.get('checkInMethod')
        biometric_device_id = request.data.get('biometric_device_id') or request.data.get('biometricDeviceId')
        location_name = request.data.get('location_name') or request.data.get('locationName') or request.data.get('check_in_location_name') or request.data.get('checkInLocationName')

        try:
            attendance, msg = AttendanceService.process_check_in(
                user=request.user,
                latitude=lat,
                longitude=lon,
                shift=shift,
                notes=notes,
                check_in_method=check_in_method,
                biometric_device_id=biometric_device_id,
                location_name=location_name
            )
            return Response({
                'message': msg,
                'data': AttendanceSerializer(attendance).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['HR - Attendance'],
        summary="Get Logged-in User's Attendance Today",
        description="Returns today's attendance details (Check-in/Check-out times, shift, location, status) for the currently authenticated user."
    )
    @action(detail=False, methods=['get'], url_path='today')
    def today(self, request):
        today_date = timezone.now().date()
        today_records = Attendance.objects.filter(user=request.user, date=today_date).order_by('shift')
        return Response({
            'date': today_date,
            'hasCheckedIn': today_records.exists(),
            'records': AttendanceSerializer(today_records, many=True).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Attendance'],
        summary="Get Monthly Attendance Summary for Current User",
        description="Returns count of Present, Late, Half Day, Absent, and On Leave days for the specified month and year."
    )
    @action(detail=False, methods=['get'], url_path='my-summary')
    def my_summary(self, request):
        now = timezone.now()
        month = int(request.query_params.get('month', now.month))
        year = int(request.query_params.get('year', now.year))

        attendances = Attendance.objects.filter(
            user=request.user,
            date__year=year,
            date__month=month
        )

        counts = {
            'present': attendances.filter(status=Attendance.STATUS_CHOICES['PRESENT']).count(),
            'late': attendances.filter(status=Attendance.STATUS_CHOICES['LATE']).count(),
            'halfDay': attendances.filter(status=Attendance.STATUS_CHOICES['HALF_DAY']).count(),
            'absent': attendances.filter(status=Attendance.STATUS_CHOICES['ABSENT']).count(),
            'onLeave': attendances.filter(status=Attendance.STATUS_CHOICES['ON_LEAVE']).count(),
            'totalRecords': attendances.count()
        }

        return Response({
            'month': month,
            'year': year,
            'summary': counts
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Attendance'],
        summary="Get Date-Range Attendance Summary",
        description="Returns an aggregated attendance summary (Present, Late, Half Day, Absent, On Leave, Total Working Hours) and paginated attendance records for a user within a specified date range.",
        parameters=[
            OpenApiParameter(name='user_id', type=int, location=OpenApiParameter.QUERY, description='Target user ID', required=False),
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Start date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='End date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='status', type=str, location=OpenApiParameter.QUERY, description='Status filter', required=False),
            OpenApiParameter(name='page', type=int, location=OpenApiParameter.QUERY, description='Page number', required=False),
            OpenApiParameter(name='page_size', type=int, location=OpenApiParameter.QUERY, description='Page size', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        now = timezone.now()
        today = now.date()

        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')

        if start_date_str:
            start_date = parse_date(str(start_date_str).strip())
            if not start_date:
                return Response({'error': 'Invalid start_date format. Please use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            start_date = datetime.date(today.year, today.month, 1)

        if end_date_str:
            end_date = parse_date(str(end_date_str).strip())
            if not end_date:
                return Response({'error': 'Invalid end_date format. Please use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            end_date = today

        if start_date > end_date:
            return Response({'error': 'start_date must be on or before end_date.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id_param = request.query_params.get('user_id') or request.query_params.get('userId') or request.query_params.get('user')
        if user_id_param:
            try:
                user_id = int(user_id_param)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid user_id parameter.'}, status=status.HTTP_400_BAD_REQUEST)

            if request.user.id != user_id and not (request.user.is_superuser or request.user.is_staff):
                return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

            target_user = User.objects.filter(id=user_id).select_related('role').first()
            if not target_user:
                return Response({'error': f'User with ID {user_id} not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            target_user = request.user

        attendances_qs = Attendance.objects.filter(
            user=target_user,
            date__gte=start_date,
            date__lte=end_date
        ).select_related('user').order_by('-date', '-check_in_time')

        present_count = attendances_qs.filter(status=Attendance.STATUS_CHOICES['PRESENT']).count()
        late_count = attendances_qs.filter(status=Attendance.STATUS_CHOICES['LATE']).count()
        half_day_count = attendances_qs.filter(status=Attendance.STATUS_CHOICES['HALF_DAY']).count()
        absent_count = attendances_qs.filter(status=Attendance.STATUS_CHOICES['ABSENT']).count()
        on_leave_count = attendances_qs.filter(status=Attendance.STATUS_CHOICES['ON_LEAVE']).count()
        total_records = attendances_qs.count()

        total_seconds = 0
        for att in attendances_qs:
            if att.check_in_time and att.check_out_time:
                diff = (att.check_out_time - att.check_in_time).total_seconds()
                if diff > 0:
                    total_seconds += diff
        total_working_hours = round(total_seconds / 3600.0, 2)

        status_filter = request.query_params.get('status')
        records_to_paginate = attendances_qs
        if status_filter:
            records_to_paginate = records_to_paginate.filter(status__iexact=status_filter.strip())

        page = self.paginate_queryset(records_to_paginate)
        if page is not None:
            serialized_records = AttendanceSerializer(page, many=True).data
            paginator = self.paginator
            count = paginator.page.paginator.count
            total_pages = paginator.page.paginator.num_pages
            current_page = paginator.page.number
            page_size = paginator.get_page_size(self.request)
            next_link = paginator.get_next_link()
            previous_link = paginator.get_previous_link()
        else:
            serialized_records = AttendanceSerializer(records_to_paginate, many=True).data
            count = len(serialized_records)
            total_pages = 1
            current_page = 1
            page_size = count
            next_link = None
            previous_link = None

        return Response({
            'count': count,
            'total_pages': total_pages,
            'current_page': current_page,
            'page_size': page_size,
            'next': next_link,
            'previous': previous_link,
            'user': {
                'id': target_user.id,
                'username': target_user.username,
                'employee_id': target_user.employee_id,
                'email': target_user.email,
                'role': target_user.role.role_name if target_user.role else None
            },
            'date_range': {
                'start_date': start_date,
                'end_date': end_date,
                'total_days': (end_date - start_date).days + 1
            },
            'summary': {
                'present': present_count,
                'late': late_count,
                'half_day': half_day_count,
                'absent': absent_count,
                'on_leave': on_leave_count,
                'total_records': total_records,
                'total_working_hours': total_working_hours
            },
            'data': serialized_records
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['HR - Payroll'])
class PayrollViewSet(viewsets.ModelViewSet):
    queryset = Payroll.objects.all().select_related('user', 'generated_by', 'current_approver_role').order_by('-year', '-month')
    serializer_class = PayrollSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id']
    filterset_fields = ['user', 'month', 'year', 'status', 'generated_by']
    ordering_fields = ['id', 'year', 'month', 'amount', 'created_at']
    ordering = ['-year', '-month']

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset.all()
        return self.queryset.filter(user=self.request.user)

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Auto-Generate Monthly Payroll for Employee',
        description='Automatically calculates complete salary breakdown for an employee based on working days, absent deductions, loans, and tour allowances.',
        examples=[
            OpenApiExample(
                'Generate Single Payroll Example',
                value={'userId': 9, 'month': 8, 'year': 2026, 'approverRoleId': 1},
                request_only=True
            )
        ],
        responses={200: PayrollSerializer}
    )
    @action(detail=False, methods=['post'], url_path='generate')
    def generate_payroll(self, request):
        user_id = request.data.get('userId') or request.data.get('user_id')
        month = request.data.get('month')
        year = request.data.get('year')
        approver_role_id = request.data.get('approverRoleId') or request.data.get('currentApproverRole') or request.data.get('approver_role_id')

        if not all([user_id, month, year]):
            return Response({'error': 'userId, month, and year are required.'}, status=status.HTTP_400_BAD_REQUEST)

        approver_role = Role.objects.filter(id=approver_role_id).first() if approver_role_id else None

        try:
            include_bonus, bonus_type = _resolve_bonus_request(request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user = User.objects.get(id=user_id)
            payroll = PayrollService.calculate_user_payroll(
                user=target_user,
                month=int(month),
                year=int(year),
                generated_by=request.user,
                current_approver_role=approver_role,
                include_bonus=include_bonus,
                bonus_type=bonus_type
            )
            return Response({
                'message': f"Monthly payroll calculated successfully for {target_user.username}",
                'data': PayrollSerializer(payroll).data
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Auto-Generate Payroll for All Active Employees',
        description='Calculates monthly payroll for all active employees with active salary structures.',
        examples=[
            OpenApiExample(
                'Generate All Payroll Example',
                value={'month': 8, 'year': 2026, 'approverRoleId': 1},
                request_only=True
            )
        ]
    )
    @action(detail=False, methods=['post'], url_path='generate-all')
    def generate_all_payrolls(self, request):
        month = request.data.get('month')
        year = request.data.get('year')
        approver_role_id = request.data.get('approverRoleId') or request.data.get('currentApproverRole') or request.data.get('approver_role_id')

        if not all([month, year]):
            return Response({'error': 'month and year are required.'}, status=status.HTTP_400_BAD_REQUEST)

        month = int(month)
        year = int(year)
        approver_role = Role.objects.filter(id=approver_role_id).first() if approver_role_id else None

        try:
            include_bonus, bonus_type = _resolve_bonus_request(request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        employees = User.objects.filter(is_active=True, salary_structures__isnull=False).distinct()
        
        generated = []
        errors = []

        for emp in employees:
            try:
                p = PayrollService.calculate_user_payroll(
                    emp, month, year, generated_by=request.user,
                    current_approver_role=approver_role,
                    include_bonus=include_bonus, bonus_type=bonus_type
                )
                generated.append(PayrollSerializer(p).data)
            except Exception as e:
                errors.append({'userId': emp.id, 'username': emp.username, 'error': str(e)})

        return Response({
            'message': f"Generated payroll for {len(generated)} employee(s).",
            'totalGenerated': len(generated),
            'payrolls': generated,
            'errors': errors
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Disburse / Pay Payroll',
        description='Marks payroll as PAID and settles pending employee loans.',
        request=None,
        responses={200: PayrollSerializer}
    )
    @action(detail=True, methods=['post'], url_path='disburse')
    def disburse_payroll(self, request, pk=None):
        payroll = self.get_object()
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if payroll.user == request.user and not request.user.is_superuser:
            return Response({'error': 'Security restriction: You cannot disburse your own payroll.'}, status=status.HTTP_403_FORBIDDEN)

        payroll.status = Payroll.STATUS_CHOICES['PAID']
        payroll.save()

        if payroll.loan_deduction > 0:
            loan = Loan.objects.filter(user=payroll.user, remaining_amount__gt=0).first()
            if loan:
                loan.remaining_amount = max(0, loan.remaining_amount - payroll.loan_deduction)
                if loan.remaining_amount == 0:
                    loan.status = Loan.STATUS_CHOICES['CLOSED']
                loan.save()

        # Auto-post to Accounting General Ledger
        try:
            from accounting.services import AccountingIntegrationService
            AccountingIntegrationService.post_payroll_disbursement(payroll=payroll, user=request.user)
        except ValueError:
            logger.exception(
                "Failed to post payroll voucher for %s (%s/%s). "
                "The payroll was marked PAID but the General Ledger was not updated.",
                payroll.user.username, payroll.month, payroll.year
            )

        return Response({
            'message': f"Payroll for {payroll.user.username} marked as Paid.",
            'data': PayrollSerializer(payroll).data
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Payroll'], summary='Approve Monthly Payroll', request=None, responses={200: PayrollSerializer})
    @action(detail=True, methods=['post'], url_path='approve')
    def approve_payroll(self, request, pk=None):
        payroll = self.get_object()
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if payroll.user == request.user and not request.user.is_superuser:
            return Response({'error': 'Security restriction: You cannot approve your own payroll.'}, status=status.HTTP_403_FORBIDDEN)

        if payroll.status == Payroll.STATUS_CHOICES['PAID']:
            return Response({'error': 'Cannot approve a payroll that is already PAID.'}, status=status.HTTP_400_BAD_REQUEST)

        remarks = request.data.get('remarks') or 'Approved by manager'
        role_to_record = request.user.role or payroll.current_approver_role or Role.objects.filter(role_name__icontains='Admin').first() or Role.objects.first()

        payroll.status = Payroll.STATUS_CHOICES['APPROVED']
        payroll.save()

        if role_to_record:
            PayrollApproval.objects.create(
                payroll=payroll,
                approver=request.user,
                role=role_to_record,
                status=PayrollApproval.STATUS_CHOICES['APPROVED'],
                remarks=remarks
            )

        return Response({
            'message': f"Payroll for {payroll.user.username} approved successfully.",
            'data': PayrollSerializer(payroll).data
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Payroll'], summary='Reject Monthly Payroll')
    @action(detail=True, methods=['post'], url_path='reject')
    def reject_payroll(self, request, pk=None):
        payroll = self.get_object()
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if payroll.user == request.user and not request.user.is_superuser:
            return Response({'error': 'Security restriction: You cannot reject your own payroll.'}, status=status.HTTP_403_FORBIDDEN)

        remarks = request.data.get('remarks') or request.data.get('rejectionReason', 'Rejected by manager')
        role_to_record = request.user.role or payroll.current_approver_role or Role.objects.filter(role_name__icontains='Admin').first() or Role.objects.first()

        payroll.status = Payroll.STATUS_CHOICES['REJECTED']
        payroll.save()

        if role_to_record:
            PayrollApproval.objects.create(
                payroll=payroll,
                approver=request.user,
                role=role_to_record,
                status=PayrollApproval.STATUS_CHOICES['REJECTED'],
                remarks=remarks
            )

        return Response({
            'message': f"Payroll for {payroll.user.username} rejected.",
            'data': PayrollSerializer(payroll).data
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['HR - Loans'])
class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.all().select_related('user').order_by('-created_at')
    serializer_class = LoanSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id']
    filterset_fields = ['user', 'status', 'deduction_start_date']
    ordering_fields = ['id', 'amount', 'remaining_amount', 'deduction_start_date', 'created_at']
    ordering = ['-created_at']


@extend_schema(tags=['HR - Tour Allowance'])
class TourAllowanceViewSet(viewsets.ModelViewSet):
    queryset = TourAllowance.objects.all().select_related('user').order_by('-date', '-created_at')
    serializer_class = TourAllowanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id', 'from_location', 'to_location', 'mode_of_journey']
    filterset_fields = ['user', 'date', 'status', 'mode_of_journey']
    ordering_fields = ['id', 'date', 'total_amount', 'created_at']
    ordering = ['-date', '-created_at']


@extend_schema(tags=['HR - Holidays & Weekends'])
class HolidayViewSet(viewsets.ModelViewSet):
    queryset = Holiday.objects.all().order_by('date')
    serializer_class = HolidaySerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name']
    filterset_fields = ['date']
    ordering_fields = ['id', 'date', 'name']
    ordering = ['date']


@extend_schema(tags=['HR - Holidays & Weekends'])
class WeekendConfigViewSet(viewsets.ModelViewSet):
    queryset = WeekendConfig.objects.all().order_by('day_of_week')
    serializer_class = WeekendConfigSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['day_of_week', 'is_active']
    ordering_fields = ['day_of_week', 'is_active']
    ordering = ['day_of_week']


@extend_schema(tags=['HR - Attendance'])
class OfficeLocationViewSet(viewsets.ModelViewSet):
    queryset = OfficeLocation.objects.all().order_by('name')
    serializer_class = OfficeLocationSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'name', 'created_at']
    ordering = ['name']


@extend_schema(tags=['HR - Payroll'])
class SalaryStructureViewSet(viewsets.ModelViewSet):
    queryset = SalaryStructure.objects.all().select_related('user').order_by('-effective_from')
    serializer_class = SalaryStructureSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id']
    filterset_fields = ['user', 'effective_from']
    ordering_fields = ['id', 'effective_from', 'base_salary', 'created_at']
    ordering = ['-effective_from']


@extend_schema(tags=['HR - Payroll'])
class PayrollApprovalViewSet(viewsets.ModelViewSet):
    queryset = PayrollApproval.objects.all().select_related('payroll__user', 'approver', 'role').order_by('-created_at')
    serializer_class = PayrollApprovalSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['payroll__user__username', 'payroll__user__employee_id', 'approver__username', 'remarks']
    filterset_fields = ['payroll', 'approver', 'role', 'status']
    ordering_fields = ['id', 'created_at', 'status']
    ordering = ['-created_at']


@extend_schema(tags=['HR - Leave Management'])
class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all().select_related('user', 'approved_by').order_by('-applied_at')
    serializer_class = LeaveRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id', 'reason', 'leave_type', 'rejection_reason']
    filterset_fields = ['user', 'leave_type', 'status', 'start_date', 'end_date']
    ordering_fields = ['id', 'start_date', 'end_date', 'applied_at', 'status']
    ordering = ['-applied_at']

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset.all()
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        if (self.request.user.is_superuser or self.request.user.is_staff) and 'user' in serializer.validated_data:
            serializer.save()
        else:
            serializer.save(user=self.request.user)

    @extend_schema(tags=['HR - Leave Management'], summary='Get All Pending Leave Requests')
    @action(detail=False, methods=['get'], url_path='pending')
    def pending(self, request):
        queryset = self.get_queryset().filter(status=LeaveRequest.STATUS_CHOICES['PENDING'])
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(tags=['HR - Leave Management'], summary='Approve Leave Request', request=None, responses={200: LeaveRequestSerializer})
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        leave_request = self.get_object()
        is_manager = request.user.is_superuser or request.user.is_staff or 'hr.change_leaverequest' in request.user.get_effective_permissions()
        if not is_manager:
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if leave_request.user == request.user and not request.user.is_superuser:
            return Response({'error': 'Security restriction: You cannot approve your own leave request.'}, status=status.HTTP_403_FORBIDDEN)

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response({'error': f"Cannot approve leave request with status '{leave_request.status}'."}, status=status.HTTP_400_BAD_REQUEST)

        updated_leave = LeaveService.approve_leave(leave_request=leave_request, approved_by=request.user)
        return Response({
            'message': f"Leave request for {updated_leave.user.username} approved successfully.",
            'data': LeaveRequestSerializer(updated_leave).data
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Leave Management'], summary='Reject Leave Request')
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        leave_request = self.get_object()
        is_manager = request.user.is_superuser or request.user.is_staff or 'hr.change_leaverequest' in request.user.get_effective_permissions()
        if not is_manager:
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if leave_request.user == request.user and not request.user.is_superuser:
            return Response({'error': 'Security restriction: You cannot reject your own leave request.'}, status=status.HTTP_403_FORBIDDEN)

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response({'error': f"Cannot reject leave request with status '{leave_request.status}'."}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('rejection_reason') or request.data.get('rejectionReason') or request.data.get('reason', '')
        updated_leave = LeaveService.reject_leave(leave_request=leave_request, rejected_by=request.user, rejection_reason=reason)
        return Response({
            'message': f"Leave request for {updated_leave.user.username} rejected.",
            'data': LeaveRequestSerializer(updated_leave).data
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Leave Management'], summary='Cancel Leave Request', request=None, responses={200: LeaveRequestSerializer})
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        leave_request = self.get_object()
        if leave_request.user != request.user and not (request.user.is_superuser or request.user.is_staff):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response({'error': "Only pending leave requests can be cancelled."}, status=status.HTTP_400_BAD_REQUEST)

        leave_request.status = LeaveRequest.STATUS_CHOICES['CANCELLED']
        leave_request.save()
        return Response({
            'message': "Leave request cancelled successfully.",
            'data': LeaveRequestSerializer(leave_request).data
        }, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# Live GPS Tracking ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['HR - Live GPS Tracking'])
class TrackingViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Record Live Location Ping (Mobile Foreground Service)',
        description='Receives real-time GPS coordinate from the field marketing officer mobile device. Updates current location and appends to historical route logs.',
        request=UserLocationPingSerializer,
        responses={200: UserCurrentLocationSerializer}
    )
    @action(detail=False, methods=['post'], url_path='ping')
    def ping(self, request):
        serializer = UserLocationPingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        current_loc, log = TrackingService.record_ping(
            user=request.user,
            latitude=data['latitude'],
            longitude=data['longitude'],
            location_name=data.get('location_name'),
            accuracy=data.get('accuracy'),
            speed=data.get('speed'),
            battery_level=data.get('battery_level'),
            is_mock_location=data.get('is_mock_location', False),
            recorded_at=data.get('recorded_at')
        )

        return Response({
            'status': 'RECORDED',
            'isTrackingActive': current_loc.is_tracking_active,
            'location': UserCurrentLocationSerializer(current_loc).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Sync Offline Cached GPS Coordinates (Batch Sync)',
        description='Bulk inserts offline cached GPS points collected when the mobile device was out of network coverage.',
        request=UserLocationBatchSyncSerializer,
        responses={200: dict}
    )
    @action(detail=False, methods=['post'], url_path='batch-sync')
    def batch_sync(self, request):
        serializer = UserLocationBatchSyncSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        locations = serializer.validated_data.get('locations', [])
        synced_count = TrackingService.record_batch_sync(user=request.user, locations_data=locations)

        return Response({
            'status': 'SYNCED',
            'syncedPointsCount': synced_count,
            'message': f"{synced_count} offline location points synced successfully."
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Start / Stop Live Tracking Toggle',
        description='Toggles or explicitly sets tracking status (START or STOP) from the mobile action button.',
        parameters=[
            OpenApiParameter(name='action', type=str, location=OpenApiParameter.QUERY, description='Optional action: START or STOP', required=False)
        ]
    )
    @action(detail=False, methods=['post'], url_path='toggle')
    def toggle(self, request):
        action_param = request.data.get('action') or request.query_params.get('action')
        current_loc = TrackingService.toggle_tracking(user=request.user, action=action_param)

        return Response({
            'isTrackingActive': current_loc.is_tracking_active,
            'message': f"Tracking {'started' if current_loc.is_tracking_active else 'stopped'} successfully.",
            'location': UserCurrentLocationSerializer(current_loc).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Get Current User Live Tracking Status',
        description='Returns current tracking state, active coordinates, and last updated time for the authenticated MPO.'
    )
    @action(detail=False, methods=['get'], url_path='my-status')
    def my_status(self, request):
        current_loc = UserCurrentLocation.objects.filter(user=request.user).first()
        if not current_loc:
            return Response({
                'isTrackingActive': False,
                'location': None
            }, status=status.HTTP_200_OK)

        return Response({
            'isTrackingActive': current_loc.is_tracking_active,
            'location': UserCurrentLocationSerializer(current_loc).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Get Real-time Fleet Team Map Status (Admin / Manager)',
        description='Returns all field marketing officers with active tracking status, latest coordinates, and battery level for Web Map visualizers.'
    )
    @action(detail=False, methods=['get'], url_path='live-team')
    def live_team(self, request):
        if not (request.user.is_superuser or request.user.is_staff or getattr(request.user, 'role', None) and 'Manager' in str(request.user.role)):
            return Response({'error': 'Permission denied: Only managers can view team live map.'}, status=status.HTTP_403_FORBIDDEN)

        team_status = TrackingService.get_live_team_status()
        return Response(team_status, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Live GPS Tracking'],
        summary='Get MPO Route Breadcrumb History & Travel Distance (KM)',
        description='Returns chronological GPS breadcrumb points for a given MPO on a date, with calculated travel distance in KM for TA/DA allowance.',
        parameters=[
            OpenApiParameter(name='date', type=str, location=OpenApiParameter.QUERY, description='Optional date (YYYY-MM-DD)', required=False)
        ]
    )
    @action(detail=False, methods=['get'], url_path=r'route/(?P<user_id>\d+)')
    def route(self, request, user_id=None):
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': f"Employee with ID {user_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.user.id != target_user.id and not (request.user.is_superuser or request.user.is_staff):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        date_str = request.query_params.get('date')
        date_param = parse_date(date_str) if date_str else timezone.now().date()

        route_data = TrackingService.get_mpo_route(user=target_user, date_param=date_param)
        return Response(route_data, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# TA Configuration & Monthly TA/DA Bill
# -----------------------------------------------------------------------------

@extend_schema(tags=['HR - TA/DA Allowances'])
class TAComponentViewSet(viewsets.ModelViewSet):
    queryset = TAComponent.objects.all().order_by('display_order', 'code')
    serializer_class = TAComponentSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['code', 'name', 'description']
    filterset_fields = ['is_active']
    ordering_fields = ['display_order', 'code', 'name']
    ordering = ['display_order', 'code']


@extend_schema(tags=['HR - TA/DA Allowances'])
class EmployeeTARateViewSet(viewsets.ModelViewSet):
    queryset = EmployeeTARate.objects.all().select_related('user', 'component').order_by(
        'user', 'component', '-effective_from'
    )
    serializer_class = EmployeeTARateSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['user__username', 'user__employee_id', 'component__code', 'component__name']
    filterset_fields = ['user', 'component', 'is_active', 'effective_from']
    ordering_fields = ['effective_from', 'daily_amount', 'id']

    @extend_schema(
        summary='Effective TA Rates for an Employee',
        description='Returns the rate in force per component on a date, with the daily total.',
        parameters=[
            OpenApiParameter('user_id', int, required=False, description='Defaults to the logged-in user'),
            OpenApiParameter('on_date', str, required=False, description='YYYY-MM-DD, defaults to today'),
        ]
    )
    @action(detail=False, methods=['get'], url_path='effective')
    def effective(self, request):
        user_id = request.query_params.get('user_id') or request.query_params.get('userId')
        target_user = request.user
        if user_id:
            if str(request.user.id) != str(user_id) and not (request.user.is_superuser or request.user.is_staff):
                return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            target_user = User.objects.filter(id=user_id).first()
            if not target_user:
                return Response({'error': f'User {user_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        on_date_str = request.query_params.get('on_date') or request.query_params.get('onDate')
        on_date = parse_date(on_date_str) if on_date_str else timezone.now().date()

        rates = TAConfigService.get_effective_rates(target_user, on_date=on_date)
        return Response({
            'userId': target_user.id,
            'username': target_user.username,
            'onDate': str(on_date),
            'totalDailyRate': str(TAConfigService.get_total_daily_rate(target_user, on_date=on_date)),
            'rates': EmployeeTARateSerializer(rates, many=True).data
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['HR - TA/DA Allowances'])
class AllowanceBillViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Monthly TA/DA bills. Bills are generated from attendance and approved tours
    rather than posted directly, so there is no create endpoint - use generate.
    """
    queryset = AllowanceBill.objects.all().select_related(
        'user', 'generated_by', 'approved_by', 'accounting_voucher'
    ).prefetch_related('lines__component', 'lines__tour_allowance').order_by('-year', '-month', '-id')
    serializer_class = AllowanceBillSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['bill_number', 'user__username', 'user__employee_id', 'notes']
    filterset_fields = ['user', 'month', 'year', 'status']
    ordering_fields = ['year', 'month', 'total_amount', 'id']

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset
        return self.queryset.filter(user=self.request.user)

    def _is_manager(self, request):
        perms = request.user.get_effective_permissions()
        return (
            request.user.is_superuser
            or request.user.is_staff
            or 'change_allowancebill' in perms
            or 'all' in perms
        )

    @extend_schema(
        summary='Get the TA/DA Bills of the Logged-in Employee',
        responses={200: AllowanceBillSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='my-bills')
    def my_bills(self, request):
        qs = AllowanceBill.objects.filter(user=request.user).select_related(
            'user', 'approved_by', 'accounting_voucher'
        ).prefetch_related('lines__component').order_by('-year', '-month')
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(AllowanceBillSerializer(page, many=True).data)
        return Response(AllowanceBillSerializer(qs, many=True).data)

    @extend_schema(
        summary='Generate a TA/DA Bill for One Employee',
        description='Rebuilds the month from attendance, TA rates and approved tours. '
                    'Refuses to overwrite an APPROVED or PAID bill.',
        request=AllowanceBillGenerateSerializer,
        responses={200: AllowanceBillSerializer}
    )
    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        if not self._is_manager(request):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = AllowanceBillGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not data.get('user_id'):
            return Response({'error': 'userId is required.'}, status=status.HTTP_400_BAD_REQUEST)

        target_user = User.objects.filter(id=data['user_id']).first()
        if not target_user:
            return Response({'error': f"User {data['user_id']} not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            bill = AllowanceBillService.generate(
                user=target_user, month=data['month'], year=data['year'],
                generated_by=request.user
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': f"TA/DA bill generated for {target_user.username} ({data['month']}/{data['year']}).",
            'data': AllowanceBillSerializer(bill).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Generate TA/DA Bills for All Employees with Configured Rates',
        request=AllowanceBillGenerateSerializer,
    )
    @action(detail=False, methods=['post'], url_path='generate-all')
    def generate_all(self, request):
        if not self._is_manager(request):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = AllowanceBillGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data['month']
        year = serializer.validated_data['year']

        employees = User.objects.filter(is_active=True, ta_rates__isnull=False).distinct()

        generated, errors = [], []
        for emp in employees:
            try:
                bill = AllowanceBillService.generate(emp, month, year, generated_by=request.user)
                generated.append(AllowanceBillSerializer(bill).data)
            except ValueError as e:
                errors.append({'userId': emp.id, 'username': emp.username, 'error': str(e)})

        return Response({
            'message': f"Generated {len(generated)} TA/DA bill(s) for {month}/{year}.",
            'totalGenerated': len(generated),
            'bills': generated,
            'errors': errors
        }, status=status.HTTP_200_OK)

    @extend_schema(summary='Approve a TA/DA Bill', request=None, responses={200: AllowanceBillSerializer})
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        bill = self.get_object()
        if not self._is_manager(request):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if bill.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot approve your own TA/DA bill.'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            bill = AllowanceBillService.approve(
                bill, approved_by=request.user, notes=request.data.get('notes', '')
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': f"TA/DA bill {bill.bill_number} approved.",
            'data': AllowanceBillSerializer(bill).data
        }, status=status.HTTP_200_OK)

    @extend_schema(summary='Reject a TA/DA Bill', request=AllowanceBillRejectSerializer)
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        bill = self.get_object()
        if not self._is_manager(request):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if bill.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot reject your own TA/DA bill.'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = AllowanceBillRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bill = AllowanceBillService.reject(
                bill, rejected_by=request.user,
                reason=serializer.validated_data.get('reason', '')
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': f"TA/DA bill {bill.bill_number} rejected.",
            'data': AllowanceBillSerializer(bill).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Disburse a TA/DA Bill (posts Dr 6120 / Cr 1112)',
        request=None,
        responses={200: AllowanceBillSerializer}
    )
    @action(detail=True, methods=['post'], url_path='disburse')
    def disburse(self, request, pk=None):
        bill = self.get_object()
        if not self._is_manager(request):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if bill.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot disburse your own TA/DA bill.'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            bill = AllowanceBillService.disburse(bill, user=request.user)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': f"TA/DA bill {bill.bill_number} disbursed and posted to the General Ledger.",
            'data': AllowanceBillSerializer(bill).data
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['HR - Payroll'])
class BonusTypeViewSet(viewsets.ModelViewSet):
    """Festival bonus heads. The percentage is applied to basic salary."""
    queryset = BonusType.objects.all().order_by('display_order', 'code')
    serializer_class = BonusTypeSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['code', 'name', 'description']
    filterset_fields = ['is_active']
    ordering_fields = ['display_order', 'code', 'percentage_of_basic']
    ordering = ['display_order', 'code']
