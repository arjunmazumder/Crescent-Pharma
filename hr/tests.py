import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from hr.models import Attendance, UserLocationLog, UserCurrentLocation
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


