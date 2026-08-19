import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from hr.models import Attendance
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

