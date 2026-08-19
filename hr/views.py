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
    LeaveRequest
)
from hr.services import AttendanceService, PayrollService, LeaveService
from hr.serializers import (
    HolidaySerializer, WeekendConfigSerializer,
    OfficeLocationSerializer, SalaryStructureSerializer, PayrollApprovalSerializer,
    AttendanceSerializer, PayrollSerializer, LoanSerializer, TourAllowanceSerializer,
    LeaveRequestSerializer
)

User = get_user_model()


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
        description='Automatically calculates complete salary breakdown for an employee based on working days, absent deductions, loans, and tour allowances.'
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
            target_user = User.objects.get(id=user_id)
            payroll = PayrollService.calculate_user_payroll(
                user=target_user,
                month=int(month),
                year=int(year),
                generated_by=request.user,
                current_approver_role=approver_role
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
        summary='Auto-Generate Payroll for All Active Employees'
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
        employees = User.objects.filter(is_active=True, salary_structures__isnull=False).distinct()
        
        generated = []
        errors = []

        for emp in employees:
            try:
                p = PayrollService.calculate_user_payroll(emp, month, year, generated_by=request.user, current_approver_role=approver_role)
                generated.append(PayrollSerializer(p).data)
            except Exception as e:
                errors.append({'userId': emp.id, 'username': emp.username, 'error': str(e)})

        return Response({
            'message': f"Generated payroll for {len(generated)} employee(s).",
            'totalGenerated': len(generated),
            'payrolls': generated,
            'errors': errors
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Payroll'], summary='Disburse / Pay Payroll')
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

        return Response({
            'message': f"Payroll for {payroll.user.username} marked as Paid.",
            'data': PayrollSerializer(payroll).data
        }, status=status.HTTP_200_OK)

    @extend_schema(tags=['HR - Payroll'], summary='Approve Monthly Payroll')
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

    @extend_schema(tags=['HR - Leave Management'], summary='Approve Leave Request')
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

    @extend_schema(tags=['HR - Leave Management'], summary='Cancel Leave Request')
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
