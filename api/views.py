import datetime
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from core.models import Lookup, Role
from hr.models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest
)
from hr.services import AttendanceService, PayrollService, LeaveService
from inventory.models import (
    Category, Attribute, AttributeValue, Product,
    ProductAttributeValue, Warehouse, StockLevel, StockMovement
)
from inventory.services import InventoryService
from sales.models import (
    Customer, CustomerOrder, CustomerOrderItem,
    CustomerType, OrderStatus, PaymentStatus, PaymentMethod
)
from sales.services import OrderService
from marketing.models import (
    SalesTarget, ProductTargetItem, PeriodType, TargetType, TargetStatus
)
from marketing.services import TargetService
from .serializers import (
    UserSerializer, LookupSerializer, PermissionSerializer, RoleSerializer,
    CustomTokenObtainPairSerializer,
    HolidaySerializer, WeekendConfigSerializer,
    OfficeLocationSerializer, SalaryStructureSerializer, PayrollApprovalSerializer,
    AttendanceSerializer, PayrollSerializer, LoanSerializer, TourAllowanceSerializer,
    LeaveRequestSerializer,
    CategorySerializer, AttributeSerializer, AttributeValueSerializer,
    ProductSerializer, ProductAttributeValueSerializer,
    WarehouseSerializer, StockLevelSerializer, StockMovementSerializer,
    StockMovementCreateSerializer, StockAdjustmentSerializer,
    CustomerSerializer, CustomerOrderItemSerializer, CustomerOrderSerializer,
    CustomerOrderCreateSerializer, OrderCancelSerializer,
    ProductTargetItemSerializer, ProductTargetItemCreateSerializer,
    SalesTargetSerializer, SalesTargetCreateSerializer
)

User = get_user_model()


@extend_schema(
    tags=['Authentication'],
    summary='User Login (Obtain JWT Access Token & User Details)',
    description='Takes username and password credentials and returns an access token and complete user profile details.',
    examples=[
        OpenApiExample(
            'Admin Login Credentials',
            summary='Admin Login',
            description='Default admin credentials for quick testing',
            value={
                'username': 'admin',
                'password': '012345678'
            },
            request_only=True
        )
    ]
)
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


@extend_schema(
    tags=['Authentication'],
    summary='Refresh JWT Token',
    description='Takes a valid refresh token and returns a new access token.'
)
class CustomTokenRefreshView(TokenRefreshView):
    pass


@extend_schema(tags=['Users / Employees'])
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().select_related('role').order_by('-id')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['username', 'email', 'employee_id', 'contact', 'nid_number']
    filterset_fields = ['role', 'is_active', 'is_staff', 'is_superuser', 'location_bounded_attendance']
    ordering_fields = ['id', 'username', 'employee_id', 'joining_date', 'date_of_birth']
    ordering = ['-id']

    @extend_schema(
        tags=['Users / Employees'],
        summary='Get Current User Profile',
        description='Returns profile details of the currently authenticated user.'
    )
    @action(detail=False, methods=['get'])
    def profile(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


@extend_schema(tags=['Core / Lookups'])
class LookupViewSet(viewsets.ModelViewSet):
    queryset = Lookup.objects.all().order_by('name', 'value')
    serializer_class = LookupSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'value']
    filterset_fields = ['name', 'is_active']
    ordering_fields = ['id', 'name', 'value', 'created_at']
    ordering = ['name', 'value']


@extend_schema(tags=['Core / Roles & Permissions'])
class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().prefetch_related('permissions').order_by('role_name')
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['role_name']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'role_name', 'created_at']
    ordering = ['role_name']


@extend_schema(tags=['Core / Roles & Permissions'])
class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all().select_related('content_type').order_by('content_type__app_label', 'codename')
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'codename', 'content_type__app_label', 'content_type__model']
    filterset_fields = ['content_type__app_label', 'content_type__model']
    ordering_fields = ['id', 'name', 'codename', 'content_type__app_label']
    ordering = ['content_type__app_label', 'codename']


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
        description='Records employee attendance with geo-fencing validation and shift tracking.',
        examples=[
            OpenApiExample(
                'Geo-fenced Check-in Example',
                value={
                    'latitude': 23.81033100,
                    'longitude': 90.41252100,
                    'shift': 1,
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
        summary="Get Date-Range Attendance Summary (Filtered by User, Start Date & End Date with Pagination)",
        description="Returns an aggregated attendance summary (Present, Late, Half Day, Absent, On Leave, Total Working Hours) and paginated attendance records for a user within a specified date range.",
        parameters=[
            OpenApiParameter(name='user_id', type=int, location=OpenApiParameter.QUERY, description='Target user ID (admin/staff can query any employee; defaults to logged-in user)', required=False),
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Start date in YYYY-MM-DD format (defaults to 1st of current month)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='End date in YYYY-MM-DD format (defaults to today)', required=False),
            OpenApiParameter(name='status', type=str, location=OpenApiParameter.QUERY, description='Optional status filter (e.g. Present, Late, Absent, Half Day, On Leave)', required=False),
            OpenApiParameter(name='page', type=int, location=OpenApiParameter.QUERY, description='Page number for paginated records list (defaults to 1)', required=False),
            OpenApiParameter(name='page_size', type=int, location=OpenApiParameter.QUERY, description='Number of records per page (defaults to 10)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        now = timezone.now()
        today = now.date()

        # 1. Parse & validate start_date & end_date
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

        # 2. Determine target user & enforce authorization
        user_id_param = request.query_params.get('user_id') or request.query_params.get('userId') or request.query_params.get('user')

        if user_id_param:
            try:
                user_id = int(user_id_param)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid user_id parameter. Must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)

            if request.user.id != user_id and not (request.user.is_superuser or request.user.is_staff):
                return Response(
                    {'error': 'Permission denied: You can only view your own attendance summary.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            target_user = User.objects.filter(id=user_id).select_related('role').first()
            if not target_user:
                return Response({'error': f'User with ID {user_id} not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            target_user = request.user

        # 3. Query all attendance records in date range
        attendances_qs = Attendance.objects.filter(
            user=target_user,
            date__gte=start_date,
            date__lte=end_date
        ).select_related('user').order_by('-date', '-check_in_time')

        # 4. Calculate aggregated metrics across the entire date range
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

        # 5. Optional status filtering on records list
        status_filter = request.query_params.get('status')
        records_to_paginate = attendances_qs
        if status_filter:
            records_to_paginate = records_to_paginate.filter(status__iexact=status_filter.strip())

        # 6. Apply pagination
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

        pagination_data = {
            'count': count,
            'total_pages': total_pages,
            'current_page': current_page,
            'page_size': page_size,
            'next': next_link,
            'previous': previous_link
        }

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
                'Generate Payroll Example',
                value={
                    'userId': 3,
                    'month': 8,
                    'year': 2026,
                    'approverRoleId': 1
                },
                request_only=True
            )
        ]
    )
    @action(detail=False, methods=['post'], url_path='generate')
    def generate_payroll(self, request):
        from core.models import Role
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
        summary='Auto-Generate Payroll for All Active Employees',
        description='Generates monthly payroll drafts for all active employees who have a configured salary structure.',
        examples=[
            OpenApiExample(
                'Generate All Payroll Example',
                value={
                    'month': 8,
                    'year': 2026,
                    'approverRoleId': 2
                },
                request_only=True
            )
        ]
    )
    @action(detail=False, methods=['post'], url_path='generate-all')
    def generate_all_payrolls(self, request):
        from core.models import Role
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

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Disburse / Pay Payroll (Deducts Loan EMI & Records Approval)',
        description='Marks the payroll as Paid, automatically deducts the loan EMI from active employee loans, and records approval logs.'
    )
    @action(detail=True, methods=['post'], url_path='disburse')
    def disburse_payroll(self, request, pk=None):
        payroll = self.get_object()

        # Permission check: Only Admin / Staff / HR Manager with change_payroll permission can disburse
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response(
                {'error': 'Permission denied: Only authorized HR or Accounts administrators can disburse payroll.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Self-disbursement prevention check
        if payroll.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot disburse your own payroll.'},
                status=status.HTTP_403_FORBIDDEN
            )

        payroll.status = Payroll.STATUS_CHOICES['PAID']
        payroll.save()

        # Deduct loan remaining amount if loan_deduction > 0
        if payroll.loan_deduction > 0:
            loan = Loan.objects.filter(user=payroll.user, remaining_amount__gt=0).first()
            if loan:
                loan.remaining_amount = max(0, loan.remaining_amount - payroll.loan_deduction)
                if loan.remaining_amount == 0:
                    loan.status = Loan.STATUS_CHOICES['CLOSED']
                loan.save()

        return Response({
            'message': f"Payroll for {payroll.user.username} marked as Paid. Loan deductions updated.",
            'data': PayrollSerializer(payroll).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Approve Monthly Payroll',
        description='Marks the payroll draft as APPROVED, ready for final disbursement. Requires HR/Finance Manager permissions.',
        examples=[
            OpenApiExample(
                'Approve Payroll Example',
                value={'remarks': 'Verified attendance, tour bills, and loan deductions. Approved.'},
                request_only=True
            )
        ]
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve_payroll(self, request, pk=None):
        payroll = self.get_object()

        # Permission check: Only Admin / Staff / HR Manager with change_payroll permission can approve
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response(
                {'error': 'Permission denied: Only managers or HR administrators with change_payroll permission can approve payroll.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Self-approval prevention check
        if payroll.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot approve your own payroll. It must be approved by an authorized manager.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if payroll.status == Payroll.STATUS_CHOICES['PAID']:
            return Response({'error': 'Cannot approve a payroll that is already PAID.'}, status=status.HTTP_400_BAD_REQUEST)

        remarks = request.data.get('remarks') or 'Approved by manager'
        role_to_record = request.user.role or payroll.current_approver_role or Role.objects.filter(role_name__icontains='Admin').first() or Role.objects.first()

        payroll.status = Payroll.STATUS_CHOICES['APPROVED']
        payroll.save()

        # Automatically log the approval audit entry
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

    @extend_schema(
        tags=['HR - Payroll'],
        summary='Reject Monthly Payroll',
        description='Marks the payroll as REJECTED with remarks.',
        examples=[
            OpenApiExample(
                'Reject Payroll Example',
                value={'remarks': 'Discrepancy found in absent days calculation.'},
                request_only=True
            )
        ]
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject_payroll(self, request, pk=None):
        payroll = self.get_object()

        # Permission check
        user_perms = request.user.get_effective_permissions()
        is_authorized = request.user.is_superuser or request.user.is_staff or 'change_payroll' in user_perms or 'all' in user_perms
        if not is_authorized:
            return Response(
                {'error': 'Permission denied: Only managers or HR administrators can reject payroll.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if payroll.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot reject your own payroll.'},
                status=status.HTTP_403_FORBIDDEN
            )

        remarks = request.data.get('remarks') or request.data.get('rejectionReason', 'Rejected by manager')
        role_to_record = request.user.role or payroll.current_approver_role or Role.objects.filter(role_name__icontains='Admin').first() or Role.objects.first()

        payroll.status = Payroll.STATUS_CHOICES['REJECTED']
        payroll.save()

        # Automatically log the rejection audit entry
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
            'remarks': remarks,
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

    @extend_schema(
        tags=['HR - Leave Management'],
        summary='Get All Pending Leave Requests',
        description='Returns all pending leave requests waiting for approval. Regular employees see their own pending requests; Admins/Managers see all employees pending requests. Supports pagination, search, and ordering.',
        responses={200: LeaveRequestSerializer(many=True)}
    )
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

    @extend_schema(
        tags=['HR - Leave Management'],
        summary='Approve Leave Request (Creates Attendance records as On Leave)',
        description='Manager or HR approves the leave request. Requires Manager/HR permissions. Self-approval is strictly forbidden.',
        request=None,
        responses={200: LeaveRequestSerializer}
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        leave_request = self.get_object()

        # 1. Permission check: Only Admin / Staff / Manager with proper permission can approve
        is_manager = request.user.is_superuser or request.user.is_staff or 'hr.change_leaverequest' in request.user.get_effective_permissions()
        if not is_manager:
            return Response(
                {'error': 'Permission denied: Only managers or HR administrators can approve leave requests.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Self-approval prevention check
        if leave_request.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot approve your own leave request. It must be approved by a manager or HR administrator.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response(
                {'error': f"Cannot approve leave request with current status '{leave_request.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        updated_leave = LeaveService.approve_leave(leave_request=leave_request, approved_by=request.user)
        return Response({
            'message': f"Leave request for {updated_leave.user.username} approved successfully.",
            'data': LeaveRequestSerializer(updated_leave).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Leave Management'],
        summary='Reject Leave Request',
        description='Rejects the leave request with an optional rejection reason. Requires Manager/HR permissions. Self-rejection is not allowed.',
        examples=[
            OpenApiExample(
                'Reject Leave Example',
                value={'rejectionReason': 'Staff shortage on requested dates'},
                request_only=True
            )
        ],
        responses={200: LeaveRequestSerializer}
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        leave_request = self.get_object()

        # 1. Permission check: Only Admin / Staff / Manager with proper permission can reject
        is_manager = request.user.is_superuser or request.user.is_staff or 'hr.change_leaverequest' in request.user.get_effective_permissions()
        if not is_manager:
            return Response(
                {'error': 'Permission denied: Only managers or HR administrators can reject leave requests.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Self-rejection prevention check
        if leave_request.user == request.user and not request.user.is_superuser:
            return Response(
                {'error': 'Security restriction: You cannot reject your own leave request.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response(
                {'error': f"Cannot reject leave request with current status '{leave_request.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        reason = request.data.get('rejection_reason') or request.data.get('rejectionReason') or request.data.get('reason', '')
        updated_leave = LeaveService.reject_leave(leave_request=leave_request, rejected_by=request.user, rejection_reason=reason)
        return Response({
            'message': f"Leave request for {updated_leave.user.username} rejected.",
            'data': LeaveRequestSerializer(updated_leave).data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['HR - Leave Management'],
        summary='Cancel Leave Request (By Employee)',
        description='Allows the employee to cancel their pending leave request. Only the ID in the URL is required (no body needed).',
        request=None,
        responses={200: LeaveRequestSerializer}
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        leave_request = self.get_object()

        # Ownership check: Only the employee who applied or an admin can cancel
        if leave_request.user != request.user and not (request.user.is_superuser or request.user.is_staff):
            return Response(
                {'error': 'Permission denied: You can only cancel your own leave requests.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if leave_request.status != LeaveRequest.STATUS_CHOICES['PENDING']:
            return Response(
                {'error': "Only pending leave requests can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST
            )

        leave_request.status = LeaveRequest.STATUS_CHOICES['CANCELLED']
        leave_request.save()
        return Response({
            'message': "Leave request cancelled successfully.",
            'data': LeaveRequestSerializer(leave_request).data
        }, status=status.HTTP_200_OK)


# =======================================================
# PRODUCTS & CATEGORIES VIEWSETS
# =======================================================

@extend_schema(tags=['Products & Categories'])
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().select_related('parent').prefetch_related('subcategories', 'products').order_by('display_order', 'name')
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['parent', 'is_active']
    ordering_fields = ['id', 'display_order', 'name', 'created_at']
    ordering = ['display_order', 'name']

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Root Categories with Nested Subcategories Tree (Paginated, Searchable, Filterable)',
        description='Returns top-level root categories with all nested children in tree hierarchy. Supports pagination, search, filtering, and ordering.'
    )
    @action(detail=False, methods=['get'], url_path='tree')
    def tree(self, request):
        roots = self.get_queryset().filter(parent__isnull=True)
        queryset = self.filter_queryset(roots)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema(tags=['Products & Categories'])
class AttributeViewSet(viewsets.ModelViewSet):
    queryset = Attribute.objects.all().prefetch_related('values').order_by('name')
    serializer_class = AttributeSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'name', 'created_at']
    ordering = ['name']


@extend_schema(tags=['Products & Categories'])
class AttributeValueViewSet(viewsets.ModelViewSet):
    queryset = AttributeValue.objects.all().select_related('attribute').order_by('attribute__name', 'value')
    serializer_class = AttributeValueSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['value', 'code', 'attribute__name']
    filterset_fields = ['attribute']
    ordering_fields = ['id', 'value', 'created_at']
    ordering = ['attribute__name', 'value']


@extend_schema(tags=['Products & Categories'])
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().select_related('category').prefetch_related(
        'product_attributes__attribute_value__attribute',
        'stock_levels'
    ).order_by('-id')
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'generic_name', 'unique_id', 'barcode', 'drug_registration_number', 'description']
    filterset_fields = ['category', 'unit', 'is_active', 'requires_prescription']
    ordering_fields = ['id', 'name', 'selling_price', 'purchase_price', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Low Stock Products (Reorder Threshold Alerts)',
        description='Returns all active products whose total stock in warehouses is at or below the minimum stock level.'
    )
    @action(detail=False, methods=['get'], url_path='low-stock')
    def low_stock(self, request):
        low_stock_items = InventoryService.get_low_stock_products()
        results = []
        for item in low_stock_items:
            data = ProductSerializer(item['product']).data
            data['totalStock'] = item['total_stock']
            data['minStockLevel'] = item['min_stock_level']
            data['deficit'] = item['deficit']
            results.append(data)
        return Response({
            'count': len(results),
            'results': results
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Expiring Products / Batches',
        description='Returns all product batches expiring within the specified days (default 90 days).'
    )
    @action(detail=False, methods=['get'], url_path='expiring')
    def expiring(self, request):
        days = int(request.query_params.get('days', 90))
        expiring_levels = InventoryService.get_expiring_batches(days=days)
        return Response({
            'daysThreshold': days,
            'count': expiring_levels.count(),
            'results': StockLevelSerializer(expiring_levels, many=True).data
        }, status=status.HTTP_200_OK)


# =======================================================
# INVENTORY & STOCK MANAGEMENT VIEWSETS
# =======================================================

@extend_schema(tags=['Inventory & Stock Management'])
class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all().prefetch_related('stock_levels').order_by('name')
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'address', 'contact_number']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'name', 'code', 'created_at']
    ordering = ['name']


@extend_schema(tags=['Inventory & Stock Management'])
class StockLevelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockLevel.objects.all().select_related('product', 'warehouse').order_by('expiry_date', 'batch_number')
    serializer_class = StockLevelSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['product__name', 'product__generic_name', 'product__unique_id', 'batch_number', 'warehouse__name']
    filterset_fields = ['product', 'warehouse', 'batch_number']
    ordering_fields = ['id', 'expiry_date', 'quantity', 'updated_at']
    ordering = ['expiry_date', 'batch_number']


@extend_schema(tags=['Inventory & Stock Management'])
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.all().select_related('product', 'warehouse', 'created_by').order_by('-created_at')
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['product__name', 'product__unique_id', 'batch_number', 'reference_no', 'notes']
    filterset_fields = ['product', 'warehouse', 'movement_type', 'batch_number']
    ordering_fields = ['id', 'created_at', 'quantity']
    ordering = ['-created_at']

    @extend_schema(
        tags=['Inventory & Stock Management'],
        summary='Record Stock Movement (Inflow, Outflow, Return, Damage)',
        description='Atomically records stock movement and updates the physical stock level in the warehouse.',
        request=StockMovementCreateSerializer,
        responses={200: StockMovementSerializer}
    )
    @action(detail=False, methods=['post'], url_path='record-movement')
    def record_movement(self, request):
        serializer = StockMovementCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            stock_level, movement = InventoryService.record_stock_movement(
                product=product,
                warehouse=warehouse,
                batch_number=data['batch_number'],
                movement_type=data['movement_type'],
                quantity=data['quantity'],
                mfg_date=data.get('mfg_date'),
                expiry_date=data.get('expiry_date'),
                rack_location=data.get('rack_location'),
                reference_no=data.get('reference_no', ''),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response({
                'message': f"Stock movement recorded successfully for {product.name}.",
                'movement': StockMovementSerializer(movement).data,
                'currentStock': StockLevelSerializer(stock_level).data
            }, status=status.HTTP_200_OK)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Warehouse not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Inventory & Stock Management'],
        summary='Adjust Stock Count (Physical Inventory Audit Reconciliation)',
        description='Sets the new physical stock quantity for a batch in a warehouse and logs an adjustment movement.',
        request=StockAdjustmentSerializer,
        responses={200: StockMovementSerializer}
    )
    @action(detail=False, methods=['post'], url_path='adjust')
    def adjust_stock(self, request):
        serializer = StockAdjustmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            stock_level, movement = InventoryService.adjust_stock(
                product=product,
                warehouse=warehouse,
                batch_number=data['batch_number'],
                new_quantity=data['new_quantity'],
                reference_no=data.get('reference_no', ''),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response({
                'message': f"Stock adjusted successfully for {product.name} to {data['new_quantity']}.",
                'movement': StockMovementSerializer(movement).data,
                'currentStock': StockLevelSerializer(stock_level).data
            }, status=status.HTTP_200_OK)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Warehouse not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# =======================================================
# CUSTOMERS & SALES ORDERS VIEWSETS
# =======================================================

@extend_schema(tags=['Customers & Sales Orders'])
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().prefetch_related('orders').order_by('-id')
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'customer_code', 'proprietor_name', 'phone', 'drug_license_no', 'trade_license_no', 'city']
    filterset_fields = ['customer_type', 'is_active', 'city']
    ordering_fields = ['id', 'name', 'customer_code', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Get Order History for a Specific Customer',
        description='Returns paginated list of all past sales orders placed by this customer with itemized details and status.'
    )
    @action(detail=True, methods=['get'], url_path='orders')
    def orders(self, request, pk=None):
        customer = self.get_object()
        orders_qs = customer.orders.all().select_related('customer', 'created_by').prefetch_related('items__product', 'items__warehouse').order_by('-order_date', '-id')
        page = self.paginate_queryset(orders_qs)
        if page is not None:
            serializer = CustomerOrderSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CustomerOrderSerializer(orders_qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Get Customer Orders Summary & Lifetime Metrics',
        description='Returns total orders count, delivered orders, pending orders, and lifetime total spent for this customer.'
    )
    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        customer = self.get_object()
        summary_data = OrderService.get_customer_summary(customer)
        return Response(summary_data, status=status.HTTP_200_OK)


@extend_schema(tags=['Customers & Sales Orders'])
class CustomerOrderViewSet(viewsets.ModelViewSet):
    queryset = CustomerOrder.objects.all().select_related('customer', 'created_by').prefetch_related('items__product', 'items__warehouse').order_by('-id')
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['order_number', 'customer__name', 'customer__customer_code', 'notes', 'shipping_address']
    filterset_fields = ['customer', 'status', 'payment_status', 'payment_method', 'order_date']
    ordering_fields = ['id', 'order_number', 'order_date', 'total_amount', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Create Customer Order (with multi-item products & automated billing)',
        description='Creates a customer sales order with multi-item products, automatic VAT & discount math, and compliance checks.',
        request=CustomerOrderCreateSerializer,
        responses={201: CustomerOrderSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = CustomerOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            customer = Customer.objects.get(id=data['customer_id'])
            order = OrderService.create_order(
                customer=customer,
                items_data=data['items'],
                user=request.user,
                order_date=data.get('order_date'),
                delivery_date=data.get('delivery_date'),
                discount_percentage=data.get('discount_percentage', 0),
                discount_flat=data.get('discount_flat', 0),
                payment_method=data.get('payment_method', PaymentMethod.CASH),
                shipping_address=data.get('shipping_address', ''),
                notes=data.get('notes', '')
            )
            return Response(CustomerOrderSerializer(order).data, status=status.HTTP_201_CREATED)
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Confirm Customer Order (Stock Availability Validation)',
        description='Validates inventory stock availability and marks order as CONFIRMED.'
    )
    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            updated_order = OrderService.confirm_order(order=order, user=request.user)
            return Response({
                'message': f"Order {order.order_number} confirmed successfully.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Deliver Customer Order (Atomically Deducts Inventory Stock)',
        description='Marks order as DELIVERED and atomically logs OUT stock movements and updates physical warehouse stock levels.'
    )
    @action(detail=True, methods=['post'], url_path='deliver')
    def deliver(self, request, pk=None):
        order = self.get_object()
        try:
            updated_order = OrderService.deliver_order(order=order, user=request.user)
            return Response({
                'message': f"Order {order.order_number} marked as DELIVERED. Inventory stock deducted.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Cancel Customer Order (with Stock Rollback if previously delivered)',
        description='Cancels the order with a mandatory cancellation reason. If the order was previously delivered, automatically restores the inventory stock.',
        request=OrderCancelSerializer,
        responses={200: CustomerOrderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        order = self.get_object()
        serializer = OrderCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reason = serializer.validated_data['cancellation_reason']
        try:
            updated_order = OrderService.cancel_order(order=order, reason=reason, user=request.user)
            return Response({
                'message': f"Order {order.order_number} cancelled successfully.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# =======================================================
# MARKETING & SALES TARGET VIEWSETS
# =======================================================

@extend_schema(tags=['Marketing & Sales Targets'])
class SalesTargetViewSet(viewsets.ModelViewSet):
    queryset = SalesTarget.objects.all().select_related('assigned_to', 'assigned_by').prefetch_related('product_items__product').order_by('-start_date', '-created_at')
    serializer_class = SalesTargetSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['title', 'target_code', 'assigned_to__username', 'assigned_to__employee_id', 'territory_name', 'notes']
    filterset_fields = ['assigned_to', 'period_type', 'target_type', 'status', 'start_date', 'end_date']
    ordering_fields = ['id', 'start_date', 'end_date', 'total_target_amount', 'created_at']
    ordering = ['-start_date', '-created_at']

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset.all()
        return self.queryset.filter(assigned_to=self.request.user)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Create Smart Sales Target with Auto-Priced Product Items',
        description='Creates a smart sales target for an MPO across a date range. Product unit prices and line-item amounts are automatically snapshot from product catalog if not provided.',
        request=SalesTargetCreateSerializer,
        responses={201: SalesTargetSerializer}
    )
    def create(self, request, *args, **kwargs):
        from django.db import transaction
        from inventory.models import Product
        serializer = SalesTargetCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        assigned_to_id = data['assigned_to_id']

        try:
            assigned_user = User.objects.get(id=assigned_to_id)
        except User.DoesNotExist:
            return Response({'error': f'Assigned employee with ID {assigned_to_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        items_data = data.get('items', [])
        total_target_amt = data.get('total_target_amount', 0)

        with transaction.atomic():
            target = SalesTarget.objects.create(
                title=data['title'],
                assigned_to=assigned_user,
                assigned_by=request.user,
                period_type=data.get('period_type', PeriodType.MONTHLY),
                start_date=data['start_date'],
                end_date=data['end_date'],
                target_type=data.get('target_type', TargetType.HYBRID),
                total_target_amount=total_target_amt,
                status=data.get('status', TargetStatus.ACTIVE),
                territory_name=data.get('territory_name', ''),
                notes=data.get('notes', '')
            )

            computed_items_total = 0
            for item in items_data:
                product_id = item['product_id']
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    raise ValueError(f"Product with ID {product_id} not found.")

                target_item = ProductTargetItem.objects.create(
                    sales_target=target,
                    product=product,
                    target_quantity=item['target_quantity'],
                    unit_price=item.get('unit_price')
                )
                computed_items_total += target_item.target_amount

            # If total_target_amount was 0 or not provided and items were given, auto-set header amount
            if (not total_target_amt or total_target_amt == 0) and computed_items_total > 0:
                target.total_target_amount = computed_items_total
                target.save(update_fields=['total_target_amount'])

        return Response(SalesTargetSerializer(target).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Live Real-time Target Achievement Breakdown with Filters',
        description='Computes real-time target achievement, product-wise actual sales vs targets, shift attendance compliance, and incentive tier qualification. Supports filtering by date range, product ID, and order status.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional evaluation start date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional evaluation end date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='product_id', type=int, location=OpenApiParameter.QUERY, description='Filter breakdown for a specific product ID', required=False),
            OpenApiParameter(name='order_status', type=str, location=OpenApiParameter.QUERY, description='Filter order status (e.g. DELIVERED, CONFIRMED)', required=False),
        ]
    )
    @action(detail=True, methods=['get'], url_path='achievement')
    def achievement(self, request, pk=None):
        target = get_object_or_404(self.get_queryset(), pk=pk)
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        product_id_param = request.query_params.get('product_id') or request.query_params.get('productId')
        order_status = request.query_params.get('order_status') or request.query_params.get('orderStatus')

        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None
        product_id = int(product_id_param) if product_id_param and str(product_id_param).isdigit() else None

        achievement_data = TargetService.calculate_target_achievement(
            target=target,
            start_date=start_date,
            end_date=end_date,
            product_id=product_id,
            order_status=order_status
        )
        return Response(achievement_data, status=status.HTTP_200_OK)


@extend_schema(tags=['Marketing & Sales Targets'])
class MarketingReportViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Logged-in MPO Live Achievement Scorecard',
        description='Returns the authenticated MPO performance scorecard across assigned targets with product breakdowns and shift compliance.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='my-achievement')
    def my_achievement(self, request):
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        scorecard = TargetService.get_mpo_scorecard(user=request.user, start_date=start_date, end_date=end_date)
        return Response(scorecard, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Specific MPO Performance Scorecard (Admin / Manager)',
        description='Returns comprehensive performance metrics, target achievement, and dual-shift attendance records for a specific MPO.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path=r'mpo/(?P<user_id>\d+)')
    def mpo_scorecard(self, request, user_id=None):
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': f'Employee with ID {user_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.id != target_user.id and not (request.user.is_superuser or request.user.is_staff):
            return Response(
                {'error': 'Permission denied: Only managers or administrators can view other employees scorecards.'},
                status=status.HTTP_403_FORBIDDEN
            )

        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        scorecard = TargetService.get_mpo_scorecard(user=target_user, start_date=start_date, end_date=end_date)
        return Response(scorecard, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Consolidated Marketing Team Report & Leaderboard',
        description='Returns company-wide consolidated sales target report ranking all MPOs by achievement percentage, team revenue totals, and territory metrics.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='period_type', type=str, location=OpenApiParameter.QUERY, description='Optional period filter (MONTHLY, QUARTERLY, CAMPAIGN, etc.)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='consolidated')
    def consolidated(self, request):
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        period_type = request.query_params.get('period_type') or request.query_params.get('periodType')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        report = TargetService.get_consolidated_team_report(start_date=start_date, end_date=end_date, period_type=period_type)
        return Response(report, status=status.HTTP_200_OK)





