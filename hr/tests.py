import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from django.db import IntegrityError, transaction

from hr.models import (
    Attendance, UserLocationLog, UserCurrentLocation, Loan,
    TAComponent, EmployeeTARate, Holiday, WeekendConfig, TourAllowance,
    AllowanceBill, AllowanceBillLine, SalaryStructure, BonusType
)
from hr.services import (
    TAConfigService, AllowanceEligibilityService, AllowanceBillService,
    PayrollService
)
from accounting.services import AccountingIntegrationService
from core.models import Role

User = get_user_model()


class AttendanceSummaryAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.role_emp = Role.objects.create(role_name='Medical Representative')
        self.role_admin = Role.objects.create(role_name='HR Manager')

        self.employee1 = User.objects.create_user(
            username='emp_rahim',
            email='rahim@crescent.com',
            password='Password@123',
            employee_id='EMP-0010',
            role=self.role_emp
        )

        self.employee2 = User.objects.create_user(
            username='emp_karim',
            email='karim@crescent.com',
            password='Password@123',
            employee_id='EMP-0020',
            role=self.role_emp
        )

        self.admin_user = User.objects.create_user(
            username='admin_hr',
            email='hr@crescent.com',
            password='Password@123',
            is_staff=True,
            role=self.role_admin
        )

        # Seed attendance records for employee1 across August 2026
        # Day 1: Present (8 hours)
        Attendance.objects.create(
            user=self.employee1,
            date=datetime.date(2026, 8, 1),
            shift=1,
            status=Attendance.STATUS_CHOICES['PRESENT'],
            check_in_time=timezone.make_aware(datetime.datetime(2026, 8, 1, 9, 0, 0)),
            check_out_time=timezone.make_aware(datetime.datetime(2026, 8, 1, 17, 0, 0)),
            check_in_location_name='Head Office'
        )

        # Day 2: Late (7.5 hours)
        Attendance.objects.create(
            user=self.employee1,
            date=datetime.date(2026, 8, 2),
            shift=1,
            status=Attendance.STATUS_CHOICES['LATE'],
            check_in_time=timezone.make_aware(datetime.datetime(2026, 8, 2, 9, 30, 0)),
            check_out_time=timezone.make_aware(datetime.datetime(2026, 8, 2, 17, 0, 0)),
            check_in_location_name='Head Office'
        )

        # Day 3: Absent
        Attendance.objects.create(
            user=self.employee1,
            date=datetime.date(2026, 8, 3),
            shift=1,
            status=Attendance.STATUS_CHOICES['ABSENT']
        )

        # Day 4: On Leave
        Attendance.objects.create(
            user=self.employee1,
            date=datetime.date(2026, 8, 4),
            shift=1,
            status=Attendance.STATUS_CHOICES['ON_LEAVE'],
            notes='Casual Leave'
        )

        # Day 5: Half Day (4 hours)
        Attendance.objects.create(
            user=self.employee1,
            date=datetime.date(2026, 8, 5),
            shift=1,
            status=Attendance.STATUS_CHOICES['HALF_DAY'],
            check_in_time=timezone.make_aware(datetime.datetime(2026, 8, 5, 9, 0, 0)),
            check_out_time=timezone.make_aware(datetime.datetime(2026, 8, 5, 13, 0, 0)),
            check_in_location_name='Head Office'
        )

    def test_employee_can_get_own_attendance_summary(self):
        """Tests that an employee gets accurate summary counts, working hours, pagination, and data array."""
        self.client.force_authenticate(user=self.employee1)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': '2026-08-01',
                'endDate': '2026-08-05'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data

        # Check pagination root fields
        self.assertEqual(data.get('count'), 5)
        self.assertEqual(data.get('totalPages') or data.get('total_pages'), 1)
        self.assertEqual(data.get('currentPage') or data.get('current_page'), 1)
        self.assertEqual(data.get('pageSize') or data.get('page_size'), 10)

        # Check user info
        user_info = data.get('user', {})
        self.assertEqual(user_info.get('id'), self.employee1.id)
        self.assertEqual(user_info.get('username'), 'emp_rahim')
        self.assertEqual(user_info.get('employeeId') or user_info.get('employee_id'), 'EMP-0010')

        # Check date range
        date_range = data.get('dateRange') or data.get('date_range')
        self.assertEqual(date_range.get('totalDays') or date_range.get('total_days'), 5)

        # Check summary metrics
        summary = data.get('summary', {})
        self.assertEqual(summary.get('present'), 1)
        self.assertEqual(summary.get('late'), 1)
        self.assertEqual(summary.get('absent'), 1)
        self.assertEqual(summary.get('onLeave') if summary.get('onLeave') is not None else summary.get('on_leave'), 1)
        self.assertEqual(summary.get('halfDay') if summary.get('halfDay') is not None else summary.get('half_day'), 1)
        self.assertEqual(summary.get('totalRecords') or summary.get('total_records'), 5)
        # Total working hours = 8 + 7.5 + 4 = 19.5
        total_hours = summary.get('totalWorkingHours') or summary.get('total_working_hours')
        self.assertEqual(float(total_hours), 19.5)

        # Check data array
        self.assertEqual(len(data.get('data')), 5)

    def test_admin_can_query_other_user_summary(self):
        """Tests that staff/admin can query any user's attendance summary via userId."""
        self.client.force_authenticate(user=self.admin_user)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'userId': self.employee1.id,
                'startDate': '2026-08-01',
                'endDate': '2026-08-05'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['user']['id'], self.employee1.id)
        self.assertEqual(resp.data['count'], 5)
        self.assertEqual(len(resp.data['data']), 5)

    def test_employee_cannot_query_other_user_summary(self):
        """Tests that regular employee is forbidden (403) from querying another employee's summary."""
        self.client.force_authenticate(user=self.employee2)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'userId': self.employee1.id,
                'startDate': '2026-08-01',
                'endDate': '2026-08-05'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Permission denied', str(resp.data.get('error')))

    def test_invalid_date_range_validation(self):
        """Tests that startDate > endDate returns 400 Bad Request."""
        self.client.force_authenticate(user=self.employee1)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': '2026-08-10',
                'endDate': '2026-08-01'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must be on or before', str(resp.data.get('error')))

    def test_invalid_date_format(self):
        """Tests that invalid date string format returns 400 Bad Request."""
        self.client.force_authenticate(user=self.employee1)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': 'not-a-date',
                'endDate': '2026-08-05'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pagination_in_attendance_summary(self):
        """Tests pagination when records exceed page size."""
        # Create 10 additional records for employee1
        for day in range(6, 16):
            Attendance.objects.create(
                user=self.employee1,
                date=datetime.date(2026, 8, day),
                shift=1,
                status=Attendance.STATUS_CHOICES['PRESENT'],
                check_in_time=timezone.make_aware(datetime.datetime(2026, 8, day, 9, 0, 0)),
                check_out_time=timezone.make_aware(datetime.datetime(2026, 8, day, 17, 0, 0))
            )

        self.client.force_authenticate(user=self.employee1)

        # Page 1 (pageSize=10)
        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': '2026-08-01',
                'endDate': '2026-08-15',
                'page': 1,
                'pageSize': 10
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data.get('count'), 15)
        self.assertEqual(data.get('totalPages') or data.get('total_pages'), 2)
        self.assertEqual(data.get('currentPage') or data.get('current_page'), 1)
        self.assertEqual(len(data.get('data')), 10)
        self.assertIsNotNone(data.get('next'))

        # Page 2
        resp2 = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': '2026-08-01',
                'endDate': '2026-08-15',
                'page': 2,
                'pageSize': 10
            }
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp2.data.get('data')), 5)
        self.assertEqual(resp2.data.get('currentPage') or resp2.data.get('current_page'), 2)

    def test_status_filter_on_records(self):
        """Tests that passing status filter only filters the record list while retaining overall summary."""
        self.client.force_authenticate(user=self.employee1)

        resp = self.client.get(
            '/api/attendance/summary/',
            {
                'startDate': '2026-08-01',
                'endDate': '2026-08-05',
                'status': 'Late'
            }
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(len(data.get('data')), 1)
        self.assertEqual(data['data'][0]['status'], 'Late')

        summary = data.get('summary', {})
        self.assertEqual(summary.get('present'), 1)
        self.assertEqual(summary.get('late'), 1)
        self.assertEqual(summary.get('absent'), 1)

    def test_remote_employee_check_in_with_custom_location(self):
        """Tests that remote employee can provide explicit location_name or fallback gracefully."""
        self.employee1.location_bounded_attendance = False
        self.employee1.save()
        self.client.force_authenticate(user=self.employee1)

        # Shift 1: with explicit location_name
        resp = self.client.post('/api/attendance/check-in/', {
            'shift': 1,
            'latitude': 23.7465,
            'longitude': 90.3760,
            'location_name': 'Lazz Pharma Dhanmondi Branch',
            'notes': 'Field clinic visit'
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        loc_name = resp.data['data'].get('check_in_location_name') or resp.data['data'].get('checkInLocationName')
        self.assertEqual(loc_name, 'Lazz Pharma Dhanmondi Branch')

    def test_remote_employee_check_in_with_gps_geocoding(self):
        """Tests that remote employee check-in with GPS resolves real location name instead of Remote / Unbounded."""
        self.employee1.location_bounded_attendance = False
        self.employee1.save()
        self.client.force_authenticate(user=self.employee1)

        # Shift 2: with GPS coords (Banani / Dhaka coordinates)
        resp = self.client.post('/api/attendance/check-in/', {
            'shift': 2,
            'latitude': 23.792308,
            'longitude': 90.405696,
            'notes': 'Field visit evening'
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        loc_name = resp.data['data'].get('check_in_location_name') or resp.data['data'].get('checkInLocationName')
        self.assertIsNotNone(loc_name)
        self.assertNotEqual(loc_name, 'Remote / Unbounded')


class LiveGPSTrackingAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.role_mpo = Role.objects.create(role_name='Medical Representative')
        self.role_manager = Role.objects.create(role_name='Regional Sales Manager')

        self.mpo_user = User.objects.create_user(
            username='mpo_rakib',
            email='rakib@crescent.com',
            password='Password@123',
            employee_id='EMP-0050',
            role=self.role_mpo
        )

        self.manager_user = User.objects.create_user(
            username='rsm_tanvir',
            email='tanvir@crescent.com',
            password='Password@123',
            employee_id='EMP-0005',
            role=self.role_manager,
            is_staff=True
        )

    def test_single_location_ping(self):
        """Tests that /api/tracking/ping/ creates a log and updates current location."""
        self.client.force_authenticate(user=self.mpo_user)

        payload = {
            'latitude': 23.8103310,
            'longitude': 90.4125210,
            'accuracy': 5.4,
            'speed': 1.8,
            'batteryLevel': 85,
            'isMockLocation': False,
            'recordedAt': '2026-08-25T11:45:00Z'
        }

        resp = self.client.post('/api/tracking/ping/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Check DB
        current = UserCurrentLocation.objects.get(user=self.mpo_user)
        self.assertTrue(current.is_tracking_active)
        self.assertEqual(float(current.latitude), 23.810331)
        self.assertEqual(current.battery_level, 85)

        self.assertEqual(UserLocationLog.objects.filter(user=self.mpo_user).count(), 1)

    def test_batch_sync_offline_locations(self):
        """Tests that /api/tracking/batch-sync/ stores all offline points in bulk."""
        self.client.force_authenticate(user=self.mpo_user)

        payload = {
            'locations': [
                {
                    'latitude': 23.8101000,
                    'longitude': 90.4121000,
                    'accuracy': 6.0,
                    'speed': 2.1,
                    'batteryLevel': 90,
                    'isMockLocation': False,
                    'recordedAt': '2026-08-25T09:00:00Z'
                },
                {
                    'latitude': 23.8125000,
                    'longitude': 90.4150000,
                    'accuracy': 4.8,
                    'speed': 12.5,
                    'batteryLevel': 88,
                    'isMockLocation': False,
                    'recordedAt': '2026-08-25T09:15:00Z'
                }
            ]
        }

        resp = self.client.post('/api/tracking/batch-sync/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get('syncedPointsCount') or resp.data.get('synced_points_count'), 2)
        self.assertEqual(UserLocationLog.objects.filter(user=self.mpo_user).count(), 2)

    def test_toggle_tracking_state(self):
        """Tests that /api/tracking/toggle/ flips the is_tracking_active boolean."""
        self.client.force_authenticate(user=self.mpo_user)

        # 1. Start tracking
        resp = self.client.post('/api/tracking/toggle/', {'action': 'START'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get('isTrackingActive') or resp.data.get('is_tracking_active'))

        # 2. Stop tracking
        resp = self.client.post('/api/tracking/toggle/', {'action': 'STOP'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data.get('isTrackingActive') or resp.data.get('is_tracking_active'))

    def test_my_status_endpoint(self):
        """Tests that /api/tracking/my-status/ returns the current user's tracking state."""
        UserCurrentLocation.objects.create(
            user=self.mpo_user,
            latitude=Decimal('23.8103310'),
            longitude=Decimal('90.4125210'),
            is_tracking_active=True,
            battery_level=75
        )

        self.client.force_authenticate(user=self.mpo_user)
        resp = self.client.get('/api/tracking/my-status/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get('isTrackingActive') or resp.data.get('is_tracking_active'))

    def test_live_team_status_for_managers(self):
        """Tests that /api/tracking/live-team/ returns full team status for authorized manager."""
        UserCurrentLocation.objects.create(
            user=self.mpo_user,
            latitude=Decimal('23.8103310'),
            longitude=Decimal('90.4125210'),
            is_tracking_active=True,
            battery_level=90
        )

        self.client.force_authenticate(user=self.manager_user)
        resp = self.client.get('/api/tracking/live-team/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(resp.data.get('totalStaffCount') or resp.data.get('total_staff_count'), 1)

    def test_route_history_and_distance_calculation(self):
        """Tests that /api/tracking/route/{user_id}/ calculates Haversine route distance in KM."""
        now = timezone.now()
        # Seed 2 points 1 km apart
        UserLocationLog.objects.create(
            user=self.mpo_user,
            latitude=Decimal('23.8103000'),
            longitude=Decimal('90.4125000'),
            recorded_at=now - datetime.timedelta(minutes=30)
        )
        UserLocationLog.objects.create(
            user=self.mpo_user,
            latitude=Decimal('23.8193000'),
            longitude=Decimal('90.4125000'),
            recorded_at=now
        )

        self.client.force_authenticate(user=self.mpo_user)
        resp = self.client.get(f'/api/tracking/route/{self.mpo_user.id}/?date={now.date().isoformat()}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get('totalPoints') or resp.data.get('total_points'), 2)
        total_dist = resp.data.get('totalDistanceKm') or resp.data.get('total_distance_km')
        self.assertGreater(total_dist, 0.0)




class LoanRulesTestCase(TestCase):
    """
    Phase 1: an employee may hold only one open loan at a time, the monthly
    deduction is validated, and a free-text note is available on the record.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username='loan_admin', password='pass12345', email='loanadmin@crescent.test'
        )
        self.employee = User.objects.create_user(
            username='loan_emp', password='pass12345', email='loanemp@crescent.test'
        )
        self.client.force_authenticate(user=self.admin)

    def _payload(self, **overrides):
        data = {
            'user': self.employee.id,
            'amount': '12000.00',
            'emi_amount': '2000.00',
            'total_months': 6,
            'remaining_amount': '12000.00',
            'deduction_start_date': '2026-01-01',
            'note': 'Medical emergency advance, approved verbally by MD.',
        }
        data.update(overrides)
        return data

    def test_note_is_stored_and_returned(self):
        resp = self.client.post('/api/loans/', self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        loan = Loan.objects.get(id=resp.data['id'])
        self.assertEqual(loan.note, 'Medical emergency advance, approved verbally by MD.')

    def test_second_loan_rejected_while_first_is_open(self):
        first = self.client.post('/api/loans/', self._payload(), format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)

        second = self.client.post(
            '/api/loans/',
            self._payload(amount='5000.00', remaining_amount='5000.00', note='Second loan'),
            format='json'
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already has an open loan', str(second.data))
        self.assertEqual(Loan.objects.filter(user=self.employee).count(), 1)

    def test_new_loan_allowed_once_previous_is_repaid(self):
        first = self.client.post('/api/loans/', self._payload(), format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)

        loan = Loan.objects.get(id=first.data['id'])
        loan.remaining_amount = Decimal('0.00')
        loan.status = Loan.STATUS_CHOICES['CLOSED']
        loan.save()

        second = self.client.post(
            '/api/loans/',
            self._payload(amount='5000.00', remaining_amount='5000.00', note='Fresh loan after repayment'),
            format='json'
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(Loan.objects.filter(user=self.employee).count(), 2)
        self.assertEqual(Loan.objects.filter(user=self.employee, remaining_amount__gt=0).count(), 1)

    def test_two_employees_may_each_hold_a_loan(self):
        other = User.objects.create_user(username='loan_emp2', password='pass12345')
        first = self.client.post('/api/loans/', self._payload(), format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)

        second = self.client.post('/api/loans/', self._payload(user=other.id), format='json')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)

    def test_monthly_deduction_must_be_positive(self):
        resp = self.client.post('/api/loans/', self._payload(emi_amount='0.00'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('greater than zero', str(resp.data))

    def test_monthly_deduction_cannot_exceed_loan_amount(self):
        resp = self.client.post(
            '/api/loans/',
            self._payload(amount='5000.00', emi_amount='9000.00', remaining_amount='5000.00'),
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cannot be greater than the loan amount', str(resp.data))

    def test_editing_the_open_loan_itself_is_allowed(self):
        """Updating a loan must not trip the one-open-loan rule against itself."""
        created = self.client.post('/api/loans/', self._payload(), format='json')
        loan_id = created.data['id']

        resp = self.client.patch(
            f'/api/loans/{loan_id}/',
            {'emi_amount': '3000.00', 'note': 'Deduction raised at employee request.'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        loan = Loan.objects.get(id=loan_id)
        self.assertEqual(loan.emi_amount, Decimal('3000.00'))


class TAConfigurationTestCase(TestCase):
    """
    Phase 2: TA is configured per employee, per component, and is effective-dated
    so raising a rate does not rewrite what past months were worth.
    """

    def setUp(self):
        self.employee = User.objects.create_user(username='ta_emp', password='pass12345')
        # Migration 0015 seeds the standard catalogue, so use those rows rather
        # than creating duplicates. This also asserts the seed actually ran.
        self.transport = TAComponent.objects.get(code='TRANSPORT')
        self.meal = TAComponent.objects.get(code='MEAL')
        self.hotel = TAComponent.objects.get(code='HOTEL')

    def test_rates_are_per_employee(self):
        other = User.objects.create_user(username='ta_emp2', password='pass12345')
        EmployeeTARate.objects.create(
            user=self.employee, component=self.transport,
            daily_amount=Decimal('150.00'), effective_from=datetime.date(2026, 1, 1)
        )
        EmployeeTARate.objects.create(
            user=other, component=self.transport,
            daily_amount=Decimal('300.00'), effective_from=datetime.date(2026, 1, 1)
        )

        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 6, 1)),
            Decimal('150.00')
        )
        self.assertEqual(
            TAConfigService.get_total_daily_rate(other, datetime.date(2026, 6, 1)),
            Decimal('300.00')
        )

    def test_components_sum_into_the_daily_rate(self):
        for component, amount in [
            (self.transport, '150.00'), (self.meal, '250.00'), (self.hotel, '600.00')
        ]:
            EmployeeTARate.objects.create(
                user=self.employee, component=component,
                daily_amount=Decimal(amount), effective_from=datetime.date(2026, 1, 1)
            )

        rates = TAConfigService.get_effective_rates(self.employee, datetime.date(2026, 6, 1))
        self.assertEqual([r.component.code for r in rates], ['TRANSPORT', 'MEAL', 'HOTEL'])
        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 6, 1)),
            Decimal('1000.00')
        )

    def test_latest_rate_on_or_before_the_date_wins(self):
        EmployeeTARate.objects.create(
            user=self.employee, component=self.transport,
            daily_amount=Decimal('150.00'), effective_from=datetime.date(2026, 1, 1)
        )
        EmployeeTARate.objects.create(
            user=self.employee, component=self.transport,
            daily_amount=Decimal('220.00'), effective_from=datetime.date(2026, 7, 1)
        )

        # Before the raise, the old rate still applies.
        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 6, 30)),
            Decimal('150.00')
        )
        # On and after the raise, the new one does.
        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 7, 1)),
            Decimal('220.00')
        )

    def test_rate_starting_in_the_future_is_ignored(self):
        EmployeeTARate.objects.create(
            user=self.employee, component=self.meal,
            daily_amount=Decimal('250.00'), effective_from=datetime.date(2027, 1, 1)
        )
        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 6, 1)),
            Decimal('0.00')
        )

    def test_inactive_rate_and_inactive_component_are_excluded(self):
        EmployeeTARate.objects.create(
            user=self.employee, component=self.transport,
            daily_amount=Decimal('150.00'), effective_from=datetime.date(2026, 1, 1),
            is_active=False
        )
        EmployeeTARate.objects.create(
            user=self.employee, component=self.hotel,
            daily_amount=Decimal('600.00'), effective_from=datetime.date(2026, 1, 1)
        )
        self.hotel.is_active = False
        self.hotel.save()

        self.assertEqual(
            TAConfigService.get_total_daily_rate(self.employee, datetime.date(2026, 6, 1)),
            Decimal('0.00')
        )

    def test_employee_without_any_rate_earns_nothing(self):
        self.assertEqual(TAConfigService.get_effective_rates(self.employee), [])
        self.assertEqual(TAConfigService.get_total_daily_rate(self.employee), Decimal('0.00'))

    def test_component_code_is_normalised(self):
        component = TAComponent.objects.create(code='  daily food  ', name='Daily Food')
        self.assertEqual(component.code, 'DAILY_FOOD')

    def test_one_rate_per_component_per_start_date(self):
        EmployeeTARate.objects.create(
            user=self.employee, component=self.meal,
            daily_amount=Decimal('250.00'), effective_from=datetime.date(2026, 1, 1)
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmployeeTARate.objects.create(
                    user=self.employee, component=self.meal,
                    daily_amount=Decimal('300.00'), effective_from=datetime.date(2026, 1, 1)
                )


class AllowanceEligibilityTestCase(TestCase):
    """
    Phase 3: allowances are earned only on days actually worked. Holidays,
    weekly off-days, approved leave and absence all earn nothing.
    """

    def setUp(self):
        self.employee = User.objects.create_user(username='elig_emp', password='pass12345')

        # August 2026: 1st is Sat, so Fridays are 7/14/21/28, Saturdays 1/8/15/22/29.
        WeekendConfig.objects.update_or_create(day_of_week=4, defaults={'is_active': True})
        WeekendConfig.objects.update_or_create(day_of_week=5, defaults={'is_active': True})

        self.holiday = Holiday.objects.create(
            date=datetime.date(2026, 8, 17), name='Independence Day'
        )

    def _attend(self, day, status=None, shift=1):
        return Attendance.objects.create(
            user=self.employee,
            date=datetime.date(2026, 8, day),
            shift=shift,
            status=status or Attendance.STATUS_CHOICES['PRESENT'],
        )

    def test_holiday_attendance_earns_nothing(self):
        self._attend(17)  # the public holiday
        self._attend(18)  # ordinary Tuesday
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 18)])

    def test_weekly_off_day_earns_nothing(self):
        self._attend(7)   # Friday
        self._attend(8)   # Saturday
        self._attend(10)  # Monday
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 10)])

    def test_approved_leave_earns_nothing(self):
        """The gap the old derived-day calculation left open."""
        self._attend(18)
        self._attend(19, status=Attendance.STATUS_CHOICES['ON_LEAVE'])
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 18)])

    def test_absent_and_half_day_earn_nothing(self):
        self._attend(18)
        self._attend(19, status=Attendance.STATUS_CHOICES['ABSENT'])
        self._attend(20, status=Attendance.STATUS_CHOICES['HALF_DAY'])
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 18)])

    def test_late_still_earns(self):
        self._attend(18, status=Attendance.STATUS_CHOICES['LATE'])
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 18)])

    def test_two_shifts_on_one_day_count_once(self):
        self._attend(18, shift=1)
        self._attend(18, shift=2)
        eligible = AllowanceEligibilityService.get_eligible_days(self.employee, 8, 2026)
        self.assertEqual(eligible, [datetime.date(2026, 8, 18)])

    def _tour(self, day, status=None):
        return TourAllowance.objects.create(
            user=self.employee,
            date=datetime.date(2026, 8, day),
            from_location='Dhaka',
            to_location='Gazipur',
            mode_of_journey='Bus',
            da_amount=Decimal('400.00'),
            other_amount=Decimal('100.00'),
            total_amount=Decimal('500.00'),
            status=status or TourAllowance.STATUS_CHOICES['APPROVED'],
        )

    def test_tour_on_holiday_is_not_payable(self):
        self._tour(17)              # public holiday
        payable = self._tour(18)    # ordinary Tuesday
        result = AllowanceEligibilityService.filter_payable_tours(self.employee, 8, 2026)
        self.assertEqual([t.id for t in result], [payable.id])

    def test_tour_on_weekly_off_day_is_not_payable(self):
        self._tour(7)               # Friday
        payable = self._tour(18)
        result = AllowanceEligibilityService.filter_payable_tours(self.employee, 8, 2026)
        self.assertEqual([t.id for t in result], [payable.id])

    def test_unapproved_tour_is_not_payable(self):
        self._tour(18, status=TourAllowance.STATUS_CHOICES['PENDING'])
        self._tour(19, status=TourAllowance.STATUS_CHOICES['REJECTED'])
        result = AllowanceEligibilityService.filter_payable_tours(self.employee, 8, 2026)
        self.assertEqual(result, [])

    def test_non_payable_reason_names_the_cause(self):
        holidays, weekend_days = AllowanceEligibilityService.get_calendar()

        holiday_reason = AllowanceEligibilityService.get_non_payable_reason(
            datetime.date(2026, 8, 17), holidays, weekend_days
        )
        self.assertIn('public holiday', holiday_reason)

        weekend_reason = AllowanceEligibilityService.get_non_payable_reason(
            datetime.date(2026, 8, 7), holidays, weekend_days
        )
        self.assertIn('weekly off-day', weekend_reason)

        self.assertIsNone(
            AllowanceEligibilityService.get_non_payable_reason(
                datetime.date(2026, 8, 18), holidays, weekend_days
            )
        )

    def test_api_flags_a_holiday_tour_before_approval(self):
        client = APIClient()
        admin = User.objects.create_superuser(username='elig_admin', password='pass12345')
        client.force_authenticate(user=admin)

        self._tour(17)  # holiday
        self._tour(18)  # normal day

        resp = client.get('/api/tour-allowance/?user={}'.format(self.employee.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # resp.data is pre-render, so keys are snake_case here. The camelCase
        # renderer converts them (is_payable -> isPayable) on the way out.
        rows = {str(r['date']): r for r in resp.data['data']}
        self.assertFalse(rows['2026-08-17']['is_payable'])
        self.assertIn('public holiday', rows['2026-08-17']['non_payable_reason'])
        self.assertTrue(rows['2026-08-18']['is_payable'])
        self.assertIsNone(rows['2026-08-18']['non_payable_reason'])


class AllowanceBillTestCase(TestCase):
    """
    Phase 4: the monthly TA/DA bill — built from worked days and approved tours,
    approved and disbursed on its own, posted to its own ledger voucher.
    """

    def setUp(self):
        self.employee = User.objects.create_user(username='bill_emp', password='pass12345')
        self.admin = User.objects.create_superuser(username='bill_admin', password='pass12345')

        WeekendConfig.objects.update_or_create(day_of_week=4, defaults={'is_active': True})
        WeekendConfig.objects.update_or_create(day_of_week=5, defaults={'is_active': True})
        Holiday.objects.create(date=datetime.date(2026, 8, 17), name='Independence Day')

        self.transport = TAComponent.objects.get(code='TRANSPORT')
        self.meal = TAComponent.objects.get(code='MEAL')
        for component, amount in [(self.transport, '150.00'), (self.meal, '250.00')]:
            EmployeeTARate.objects.create(
                user=self.employee, component=component,
                daily_amount=Decimal(amount), effective_from=datetime.date(2026, 1, 1)
            )

        # Worked: 18, 19, 20 (Tue-Thu) plus the holiday 17 and Friday 21.
        for day in (17, 18, 19, 20, 21):
            Attendance.objects.create(
                user=self.employee, date=datetime.date(2026, 8, day), shift=1,
                status=Attendance.STATUS_CHOICES['PRESENT']
            )

    def _tour(self, day, total='500.00', status=None):
        return TourAllowance.objects.create(
            user=self.employee, date=datetime.date(2026, 8, day),
            from_location='Dhaka', to_location='Gazipur', mode_of_journey='Bus',
            da_amount=Decimal('400.00'), other_amount=Decimal('100.00'),
            total_amount=Decimal(total),
            status=status or TourAllowance.STATUS_CHOICES['APPROVED'],
        )

    def test_bill_totals_only_worked_days(self):
        bill = AllowanceBillService.generate(self.employee, 8, 2026, generated_by=self.admin)

        # 17 is a holiday and 21 a Friday, so only 18/19/20 count.
        self.assertEqual(bill.eligible_days, 3)
        # (150 + 250) x 3 days
        self.assertEqual(bill.total_daily_ta, Decimal('1200.00'))
        self.assertEqual(bill.total_tour_da, Decimal('0.00'))
        self.assertEqual(bill.total_amount, Decimal('1200.00'))
        self.assertTrue(bill.bill_number.startswith('TADA-2026-'))

    def test_bill_has_a_line_per_component(self):
        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        lines = bill.lines.filter(source=AllowanceBillLine.SOURCE_CHOICES['DAILY_RATE'])
        self.assertEqual(lines.count(), 2)
        by_code = {line.component.code: line for line in lines}
        self.assertEqual(by_code['TRANSPORT'].amount, Decimal('450.00'))
        self.assertEqual(by_code['MEAL'].amount, Decimal('750.00'))
        self.assertEqual(by_code['MEAL'].days, 3)

    def test_only_payable_tours_reach_the_bill(self):
        self._tour(18)                                                    # payable
        self._tour(17)                                                    # holiday
        self._tour(21)                                                    # Friday
        self._tour(19, status=TourAllowance.STATUS_CHOICES['PENDING'])    # unapproved

        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        tour_lines = bill.lines.filter(source=AllowanceBillLine.SOURCE_CHOICES['TOUR'])
        self.assertEqual(tour_lines.count(), 1)
        self.assertEqual(bill.total_tour_da, Decimal('500.00'))
        self.assertEqual(bill.total_amount, Decimal('1700.00'))

    def test_regeneration_rebuilds_lines_without_orphans(self):
        self._tour(18)
        first = AllowanceBillService.generate(self.employee, 8, 2026)
        self.assertEqual(first.lines.count(), 3)

        TourAllowance.objects.all().delete()
        second = AllowanceBillService.generate(self.employee, 8, 2026)

        self.assertEqual(second.id, first.id)
        self.assertEqual(second.lines.count(), 2)
        self.assertEqual(second.total_tour_da, Decimal('0.00'))

    def test_settled_bill_cannot_be_regenerated(self):
        """The mistake payroll makes today: regenerating over a paid month."""
        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        AllowanceBillService.approve(bill, approved_by=self.admin)

        with self.assertRaises(ValueError) as ctx:
            AllowanceBillService.generate(self.employee, 8, 2026)
        self.assertIn('cannot be regenerated', str(ctx.exception))

    def test_disburse_requires_approval_first(self):
        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        with self.assertRaises(ValueError) as ctx:
            AllowanceBillService.disburse(bill, user=self.admin)
        self.assertIn('must be APPROVED', str(ctx.exception))

    def test_disbursement_posts_a_balanced_voucher(self):
        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        AllowanceBillService.approve(bill, approved_by=self.admin)
        bill = AllowanceBillService.disburse(bill, user=self.admin)

        self.assertEqual(bill.status, AllowanceBill.STATUS_CHOICES['PAID'])
        self.assertIsNotNone(bill.accounting_voucher, "TA/DA bill was not posted to the ledger.")

        voucher = bill.accounting_voucher
        self.assertEqual(voucher.source_module, 'HR_ALLOWANCE_BILL')
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(voucher.total_debit, bill.total_amount)

        # Debit TA expense (6120), credit bank (1112).
        self.assertEqual(voucher.entries.get(account__code='6120').debit_amount, bill.total_amount)
        self.assertEqual(voucher.entries.get(account__code='1112').credit_amount, bill.total_amount)

    def test_employee_with_no_worked_days_gets_an_empty_bill(self):
        Attendance.objects.filter(user=self.employee).delete()
        bill = AllowanceBillService.generate(self.employee, 8, 2026)
        self.assertEqual(bill.eligible_days, 0)
        self.assertEqual(bill.total_amount, Decimal('0.00'))
        self.assertEqual(bill.lines.count(), 0)

        AllowanceBillService.approve(bill, approved_by=self.admin)
        with self.assertRaises(ValueError):
            AllowanceBillService.disburse(bill, user=self.admin)


class AllowanceBillAPITestCase(TestCase):
    """
    Phase 6: the TA/DA bill is fully operable over HTTP before payroll stops
    paying TA, so there is never a window where the allowance has nowhere to go.
    """

    def setUp(self):
        self.client = APIClient()
        self.employee = User.objects.create_user(username='api_emp', password='pass12345')
        self.admin = User.objects.create_superuser(username='api_admin', password='pass12345')

        WeekendConfig.objects.update_or_create(day_of_week=4, defaults={'is_active': True})
        WeekendConfig.objects.update_or_create(day_of_week=5, defaults={'is_active': True})
        Holiday.objects.create(date=datetime.date(2026, 8, 17), name='Independence Day')

        self.transport = TAComponent.objects.get(code='TRANSPORT')
        EmployeeTARate.objects.create(
            user=self.employee, component=self.transport,
            daily_amount=Decimal('200.00'), effective_from=datetime.date(2026, 1, 1)
        )
        for day in (17, 18, 19, 20):  # 17 is the holiday
            Attendance.objects.create(
                user=self.employee, date=datetime.date(2026, 8, day), shift=1,
                status=Attendance.STATUS_CHOICES['PRESENT']
            )

    def test_effective_rates_endpoint(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(
            f'/api/employee-ta-rates/effective/?user_id={self.employee.id}&on_date=2026-08-31'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['totalDailyRate'], '200.00')
        self.assertEqual(len(resp.data['rates']), 1)

    def test_employee_cannot_read_another_employees_rates(self):
        other = User.objects.create_user(username='api_emp2', password='pass12345')
        self.client.force_authenticate(user=other)
        resp = self.client.get(f'/api/employee-ta-rates/effective/?user_id={self.employee.id}')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_full_generate_approve_disburse_flow(self):
        self.client.force_authenticate(user=self.admin)

        gen = self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026},
            format='json'
        )
        self.assertEqual(gen.status_code, status.HTTP_200_OK, gen.data)
        bill = gen.data['data']
        # 17 is a holiday, so only 18/19/20 count: 200 x 3
        self.assertEqual(bill['eligible_days'], 3)
        self.assertEqual(bill['total_amount'], '600.00')
        self.assertEqual(bill['status'], 'Draft')
        bill_id = bill['id']

        approve = self.client.post(f'/api/allowance-bills/{bill_id}/approve/')
        self.assertEqual(approve.status_code, status.HTTP_200_OK, approve.data)
        self.assertEqual(approve.data['data']['status'], 'Approved')

        disburse = self.client.post(f'/api/allowance-bills/{bill_id}/disburse/')
        self.assertEqual(disburse.status_code, status.HTTP_200_OK, disburse.data)
        self.assertEqual(disburse.data['data']['status'], 'Paid')
        self.assertIsNotNone(disburse.data['data']['voucher_number'])

    def test_disburse_before_approval_is_rejected(self):
        self.client.force_authenticate(user=self.admin)
        gen = self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026}, format='json'
        )
        bill_id = gen.data['data']['id']
        resp = self.client.post(f'/api/allowance-bills/{bill_id}/disburse/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must be APPROVED', str(resp.data))

    def test_regenerating_a_settled_bill_is_rejected(self):
        self.client.force_authenticate(user=self.admin)
        gen = self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026}, format='json'
        )
        self.client.post(f"/api/allowance-bills/{gen.data['data']['id']}/approve/")

        again = self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026}, format='json'
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cannot be regenerated', str(again.data))

    def test_generate_all_covers_employees_with_rates(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/allowance-bills/generate-all/', {'month': 8, 'year': 2026}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['totalGenerated'], 1)

    def test_employee_sees_only_their_own_bills(self):
        other = User.objects.create_user(username='api_emp3', password='pass12345')
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026}, format='json'
        )

        self.client.force_authenticate(user=other)
        resp = self.client.get('/api/allowance-bills/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)

        self.client.force_authenticate(user=self.employee)
        mine = self.client.get('/api/allowance-bills/my-bills/')
        self.assertEqual(mine.data['count'], 1)

    def test_employee_cannot_approve_own_bill(self):
        self.client.force_authenticate(user=self.admin)
        gen = self.client.post(
            '/api/allowance-bills/generate/',
            {'user_id': self.employee.id, 'month': 8, 'year': 2026}, format='json'
        )
        bill_id = gen.data['data']['id']

        self.client.force_authenticate(user=self.employee)
        resp = self.client.post(f'/api/allowance-bills/{bill_id}/approve/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_bills_endpoint_requires_authentication(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/allowance-bills/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(anon.get('/api/ta-components/').status_code, status.HTTP_401_UNAUTHORIZED)


class PayrollExcludesAllowancesTestCase(TestCase):
    """
    Phase 5: the switch. TA and DA leave the payslip and are settled on the
    TA/DA bill instead. The payroll voucher must still balance afterwards.
    """

    def setUp(self):
        self.employee = User.objects.create_user(username='pay_emp', password='pass12345')
        self.admin = User.objects.create_superuser(username='pay_admin', password='pass12345')

        WeekendConfig.objects.update_or_create(day_of_week=4, defaults={'is_active': True})
        WeekendConfig.objects.update_or_create(day_of_week=5, defaults={'is_active': True})

        SalaryStructure.objects.create(
            user=self.employee,
            base_salary=Decimal('30000.00'),
            housing_allowance=Decimal('5000.00'),
            transport_allowance=Decimal('2000.00'),
            medical_benefits=Decimal('1000.00'),
            utility_allowance=Decimal('500.00'),
            daily_ta_allowance=Decimal('300.00'),   # deprecated, must be ignored
            effective_from=datetime.date(2026, 1, 1),
        )

        # A configured TA rate and an approved tour: neither may reach the payslip.
        EmployeeTARate.objects.create(
            user=self.employee, component=TAComponent.objects.get(code='TRANSPORT'),
            daily_amount=Decimal('200.00'), effective_from=datetime.date(2026, 1, 1)
        )
        Attendance.objects.create(
            user=self.employee, date=datetime.date(2026, 8, 18), shift=1,
            status=Attendance.STATUS_CHOICES['PRESENT']
        )
        TourAllowance.objects.create(
            user=self.employee, date=datetime.date(2026, 8, 19),
            from_location='Dhaka', to_location='Gazipur', mode_of_journey='Bus',
            da_amount=Decimal('400.00'), other_amount=Decimal('100.00'),
            total_amount=Decimal('500.00'),
            status=TourAllowance.STATUS_CHOICES['APPROVED'],
        )

    def test_payslip_excludes_ta_and_tour(self):
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, generated_by=self.admin
        )
        # 30000 + 5000 + 2000 + 1000 + 500, no TA and no tour DA.
        self.assertEqual(payroll.amount, Decimal('38500.00'))
        self.assertEqual(payroll.total_ta_allowance, Decimal('0.00'))
        self.assertEqual(payroll.total_tour_allowance, Decimal('0.00'))

    def test_deprecated_daily_ta_allowance_is_ignored(self):
        """The old SalaryStructure field must not leak back into the payslip."""
        payroll = PayrollService.calculate_user_payroll(self.employee, 8, 2026)
        self.assertEqual(payroll.total_ta_allowance, Decimal('0.00'))
        self.assertNotIn(Decimal('300.00'), [payroll.total_ta_allowance])

    def test_payroll_voucher_still_balances(self):
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, generated_by=self.admin
        )
        voucher = AccountingIntegrationService.post_payroll_disbursement(
            payroll=payroll, user=self.admin
        )
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertGreater(voucher.total_debit, Decimal('0.00'))
        # No TA/DA expense line on a post-split payroll.
        self.assertFalse(voucher.entries.filter(account__code='6120').exists())

    def test_voucher_balances_with_a_loan_deduction(self):
        Loan.objects.create(
            user=self.employee, amount=Decimal('12000.00'), emi_amount=Decimal('2000.00'),
            total_months=6, remaining_amount=Decimal('12000.00'),
            deduction_start_date=datetime.date(2026, 1, 1),
        )
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, generated_by=self.admin
        )
        self.assertEqual(payroll.loan_deduction, Decimal('2000.00'))
        self.assertEqual(payroll.amount, Decimal('36500.00'))

        voucher = AccountingIntegrationService.post_payroll_disbursement(
            payroll=payroll, user=self.admin
        )
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(
            voucher.entries.get(account__code='1130').credit_amount, Decimal('2000.00')
        )

    def test_the_same_month_pays_ta_on_its_own_bill(self):
        """What left the payslip must be collectable somewhere else."""
        payroll = PayrollService.calculate_user_payroll(self.employee, 8, 2026)
        bill = AllowanceBillService.generate(self.employee, 8, 2026, generated_by=self.admin)

        self.assertEqual(payroll.total_ta_allowance, Decimal('0.00'))
        # 200/day x 1 worked day, plus the 500 approved tour.
        self.assertEqual(bill.total_daily_ta, Decimal('200.00'))
        self.assertEqual(bill.total_tour_da, Decimal('500.00'))
        self.assertEqual(bill.total_amount, Decimal('700.00'))


class FestivalBonusTestCase(TestCase):
    """
    Festival bonus: a percentage of basic salary, paid on the payslip, chosen by
    the admin at generation time because Eid moves with the lunar calendar.
    """

    def setUp(self):
        self.client = APIClient()
        self.employee = User.objects.create_user(username='bonus_emp', password='pass12345')
        self.admin = User.objects.create_superuser(username='bonus_admin', password='pass12345')

        SalaryStructure.objects.create(
            user=self.employee,
            base_salary=Decimal('30000.00'),
            housing_allowance=Decimal('5000.00'),
            transport_allowance=Decimal('2000.00'),
            medical_benefits=Decimal('1000.00'),
            utility_allowance=Decimal('500.00'),
            effective_from=datetime.date(2026, 1, 1),
        )
        self.fitr = BonusType.objects.get(code='EID_UL_FITR')
        self.adha = BonusType.objects.get(code='EID_UL_ADHA')

    def test_payroll_without_bonus_is_unchanged(self):
        payroll = PayrollService.calculate_user_payroll(self.employee, 8, 2026)
        self.assertEqual(payroll.total_bonus, Decimal('0.00'))
        self.assertIsNone(payroll.bonus_type)
        self.assertEqual(payroll.amount, Decimal('38500.00'))

    def test_bonus_is_a_percentage_of_basic_only(self):
        """100% of basic (30000), not of gross."""
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, include_bonus=True, bonus_type=self.fitr
        )
        self.assertEqual(payroll.total_bonus, Decimal('30000.00'))
        self.assertEqual(payroll.bonus_percentage, Decimal('100.00'))
        self.assertEqual(payroll.bonus_type, self.fitr)
        self.assertEqual(payroll.amount, Decimal('68500.00'))

    def test_half_rate_bonus(self):
        self.fitr.percentage_of_basic = Decimal('50.00')
        self.fitr.save()
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, include_bonus=True, bonus_type=self.fitr
        )
        self.assertEqual(payroll.total_bonus, Decimal('15000.00'))
        self.assertEqual(payroll.amount, Decimal('53500.00'))

    def test_rate_change_does_not_rewrite_a_past_payslip(self):
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, include_bonus=True, bonus_type=self.fitr
        )
        self.assertEqual(payroll.bonus_percentage, Decimal('100.00'))

        self.fitr.percentage_of_basic = Decimal('60.00')
        self.fitr.save()

        payroll.refresh_from_db()
        self.assertEqual(payroll.bonus_percentage, Decimal('100.00'))
        self.assertEqual(payroll.total_bonus, Decimal('30000.00'))

    def test_ambiguous_bonus_choice_is_refused(self):
        """Two active festivals exist, so the system must not guess."""
        with self.assertRaises(ValueError) as ctx:
            PayrollService.calculate_user_payroll(self.employee, 8, 2026, include_bonus=True)
        self.assertIn('More than one active', str(ctx.exception))

    def test_single_active_type_is_inferred(self):
        self.adha.is_active = False
        self.adha.save()
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, include_bonus=True
        )
        self.assertEqual(payroll.bonus_type, self.fitr)
        self.assertEqual(payroll.total_bonus, Decimal('30000.00'))

    def test_voucher_balances_with_bonus(self):
        payroll = PayrollService.calculate_user_payroll(
            self.employee, 8, 2026, include_bonus=True, bonus_type=self.adha
        )
        voucher = AccountingIntegrationService.post_payroll_disbursement(
            payroll=payroll, user=self.admin
        )
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(
            voucher.entries.get(account__code='6130').debit_amount, Decimal('30000.00')
        )

    def test_api_generate_with_bonus(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/payroll/generate/',
            {'userId': self.employee.id, 'month': 8, 'year': 2026,
             'includeBonus': True, 'bonusTypeId': self.fitr.id},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['data']['total_bonus'], '30000.00')
        self.assertEqual(resp.data['data']['amount'], '68500.00')

    def test_api_generate_without_bonus_by_default(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/payroll/generate/',
            {'userId': self.employee.id, 'month': 8, 'year': 2026},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['data']['total_bonus'], '0.00')
        self.assertEqual(resp.data['data']['amount'], '38500.00')

    def test_api_rejects_unknown_bonus_type(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/payroll/generate/',
            {'userId': self.employee.id, 'month': 8, 'year': 2026,
             'includeBonus': True, 'bonusTypeId': 99999},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not found', str(resp.data))

    def test_everyone_gets_the_bonus_regardless_of_attendance(self):
        """No length-of-service or attendance condition, by design."""
        newcomer = User.objects.create_user(username='bonus_new', password='pass12345')
        SalaryStructure.objects.create(
            user=newcomer, base_salary=Decimal('20000.00'),
            effective_from=datetime.date(2026, 8, 25),
        )
        Attendance.objects.create(
            user=self.employee, date=datetime.date(2026, 8, 18), shift=1,
            status=Attendance.STATUS_CHOICES['ABSENT']
        )

        for person, expected in [(self.employee, Decimal('30000.00')),
                                 (newcomer, Decimal('20000.00'))]:
            payroll = PayrollService.calculate_user_payroll(
                person, 8, 2026, include_bonus=True, bonus_type=self.adha
            )
            self.assertEqual(payroll.total_bonus, expected)
