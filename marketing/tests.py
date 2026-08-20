from decimal import Decimal
import datetime
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Role, Lookup
from inventory.models import Category, Product, Warehouse
from inventory.services import InventoryService
from sales.models import Customer, CustomerOrder, CustomerOrderItem, OrderStatus, PaymentMethod, CustomerType
from sales.services import OrderService
from hr.models import Attendance
from hr.services import AttendanceService
from marketing.models import SalesTarget, ProductTargetItem, PeriodType, TargetType, TargetStatus
from marketing.services import TargetService

User = get_user_model()


class MarketingManagementModuleTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # 1. Setup Roles & Users
        self.mpo_role = Role.objects.create(role_name='Medical Representative (MPO)')
        self.manager_role = Role.objects.create(role_name='Area Sales Manager')

        self.mpo_user = User.objects.create_user(
            username='mpo_tanvir',
            email='tanvir@crescent.com',
            password='Password@123',
            employee_id='EMP-0101',
            role=self.mpo_role,
            location_bounded_attendance=False # Remote field check-in enabled
        )

        self.mpo_user_2 = User.objects.create_user(
            username='mpo_sabbir',
            email='sabbir@crescent.com',
            password='Password@123',
            employee_id='EMP-0102',
            role=self.mpo_role,
            location_bounded_attendance=False
        )

        self.manager_user = User.objects.create_user(
            username='manager_hasan',
            email='hasan@crescent.com',
            password='Password@123',
            employee_id='EMP-0010',
            is_staff=True,
            role=self.manager_role
        )

        # 2. Setup Products & Inventory
        self.category = Category.objects.create(name='Antibiotics', code='CAT-ANTI')
        self.product_a = Product.objects.create(
            name='Ciprocin 500',
            generic_name='Ciprofloxacin 500mg',
            category=self.category,
            unit='Box',
            purchase_price=Decimal('180.00'),
            selling_price=Decimal('250.00'),
            vat_percentage=Decimal('5.00'),
            min_stock_level=20
        )
        self.product_b = Product.objects.create(
            name='Azicin 500',
            generic_name='Azithromycin 500mg',
            category=self.category,
            unit='Box',
            purchase_price=Decimal('300.00'),
            selling_price=Decimal('400.00'),
            vat_percentage=Decimal('5.00'),
            min_stock_level=10
        )

        self.warehouse = Warehouse.objects.create(name='Central Dhaka Depot', code='WH-DHK-01')
        InventoryService.record_stock_movement(
            product=self.product_a,
            warehouse=self.warehouse,
            batch_number='BATCH-2026-A1',
            movement_type='IN',
            quantity=1000,
            user=self.manager_user
        )
        InventoryService.record_stock_movement(
            product=self.product_b,
            warehouse=self.warehouse,
            batch_number='BATCH-2026-B1',
            movement_type='IN',
            quantity=1000,
            user=self.manager_user
        )

        # 3. Setup Customer
        self.customer = Customer.objects.create(
            name='Lazz Pharma Dhanmondi',
            proprietor_name='Lutfur Rahman',
            phone='+8801711223344',
            drug_license_no='DGDA-998811',
            drug_license_expiry_date=datetime.date(2027, 12, 31),
            customer_type=CustomerType.RETAIL,
            address='Dhanmondi, Dhaka',
            city='Dhaka'
        )

        # Target Period: August 2026
        self.start_date = datetime.date(2026, 8, 1)
        self.end_date = datetime.date(2026, 8, 31)

    def test_smart_target_creation_and_auto_pricing(self):
        """Tests that SalesTarget auto-generates code and ProductTargetItem auto-fetches price & amount."""
        target = SalesTarget.objects.create(
            title='August 2026 Monthly Drive',
            assigned_to=self.mpo_user,
            assigned_by=self.manager_user,
            period_type=PeriodType.MONTHLY,
            start_date=self.start_date,
            end_date=self.end_date,
            target_type=TargetType.HYBRID,
            territory_name='Dhanmondi & Mirpur Zone'
        )

        self.assertTrue(target.target_code.startswith(f"TGT-{datetime.date.today().year}-"))

        # Create target item without providing unit_price
        item_a = ProductTargetItem.objects.create(
            sales_target=target,
            product=self.product_a,
            target_quantity=200 # 200 boxes of Ciprocin 500 @ 250 = 50,000
        )
        self.assertEqual(item_a.unit_price, Decimal('250.00'))
        self.assertEqual(item_a.target_amount, Decimal('50000.00'))

        item_b = ProductTargetItem.objects.create(
            sales_target=target,
            product=self.product_b,
            target_quantity=100 # 100 boxes of Azicin 500 @ 400 = 40,000
        )
        self.assertEqual(item_b.unit_price, Decimal('400.00'))
        self.assertEqual(item_b.target_amount, Decimal('40000.00'))

    def test_target_achievement_calculation_engine(self):
        """Tests live calculation of amount achievement, product breakdown, and shift compliance."""
        # 1. Create Target
        target = SalesTarget.objects.create(
            title='August 2026 Monthly Drive',
            assigned_to=self.mpo_user,
            assigned_by=self.manager_user,
            period_type=PeriodType.MONTHLY,
            start_date=self.start_date,
            end_date=self.end_date,
            target_type=TargetType.HYBRID,
            total_target_amount=Decimal('100000.00'), # Target 100,000 BDT
            territory_name='Dhanmondi'
        )
        ProductTargetItem.objects.create(
            sales_target=target,
            product=self.product_a,
            target_quantity=200 # Target 200 boxes
        )

        # 2. Book Order 1 (CONFIRMED) within date range
        order1 = OrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    'product_id': self.product_a.id,
                    'warehouse_id': self.warehouse.id,
                    'batch_number': 'BATCH-2026-A1',
                    'quantity': 150,
                    'unit_price': '250.00',
                    'vat_percentage': '0.00',
                    'discount_percentage': '0.00'
                }
            ],
            user=self.mpo_user,
            order_date=datetime.date(2026, 8, 10)
        )
        OrderService.confirm_order(order1, user=self.manager_user)
        # Order 1 total: 150 * 250 = 37,500

        # 3. Book Order 2 (DELIVERED) within date range
        order2 = OrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    'product_id': self.product_a.id,
                    'warehouse_id': self.warehouse.id,
                    'batch_number': 'BATCH-2026-A1',
                    'quantity': 100,
                    'unit_price': '250.00',
                    'vat_percentage': '0.00',
                    'discount_percentage': '0.00'
                }
            ],
            user=self.mpo_user,
            order_date=datetime.date(2026, 8, 15)
        )
        OrderService.confirm_order(order2, user=self.manager_user)
        OrderService.deliver_order(order2, user=self.manager_user)
        # Order 2 total: 100 * 250 = 25,000

        # 4. Book Order 3 (Outside date range - should be EXCLUDED)
        order3 = OrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    'product_id': self.product_a.id,
                    'warehouse_id': self.warehouse.id,
                    'batch_number': 'BATCH-2026-A1',
                    'quantity': 50,
                    'unit_price': '250.00',
                    'vat_percentage': '0.00',
                    'discount_percentage': '0.00'
                }
            ],
            user=self.mpo_user,
            order_date=datetime.date(2026, 9, 5)
        )
        OrderService.confirm_order(order3, user=self.manager_user)

        # 5. Book Order 4 (CANCELLED - should be EXCLUDED)
        order4 = OrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    'product_id': self.product_a.id,
                    'warehouse_id': self.warehouse.id,
                    'batch_number': 'BATCH-2026-A1',
                    'quantity': 50,
                    'unit_price': '250.00',
                    'vat_percentage': '0.00',
                    'discount_percentage': '0.00'
                }
            ],
            user=self.mpo_user,
            order_date=datetime.date(2026, 8, 20)
        )
        OrderService.cancel_order(order4, reason="Client cancelled", user=self.mpo_user)

        # 6. Record Dual-Shift Attendances for MPO
        Attendance.objects.create(
            user=self.mpo_user,
            date=datetime.date(2026, 8, 10),
            shift=1, # Morning
            status=Attendance.STATUS_CHOICES['PRESENT'],
            check_in_method='GPS',
            check_in_location_name='Dhanmondi Area'
        )
        Attendance.objects.create(
            user=self.mpo_user,
            date=datetime.date(2026, 8, 10),
            shift=2, # Evening
            status=Attendance.STATUS_CHOICES['PRESENT'],
            check_in_method='BIOMETRIC_FINGERPRINT',
            biometric_device_id='FP-DEVICE-01'
        )

        # 7. Evaluate Real-Time Achievement
        res = TargetService.calculate_target_achievement(target)

        # Expected Achieved Amount: 37,500 + 25,000 = 62,500.00 BDT
        self.assertEqual(res['totalAchievedAmount'], '62500.00')
        self.assertEqual(res['totalTargetAmount'], '100000.00')
        self.assertEqual(res['amountAchievementPercentage'], 62.50)
        self.assertEqual(res['amountVariance'], '-37500.00')
        self.assertEqual(res['totalOrdersCount'], 2)

        # Product breakdown: Total 250 units sold vs 200 target -> 125% achieved
        prod_res = res['productBreakdown'][0]
        self.assertEqual(prod_res['targetQuantity'], 200)
        self.assertEqual(prod_res['achievedQuantity'], 250)
        self.assertEqual(prod_res['quantityAchievementPercentage'], 125.0)
        self.assertTrue(prod_res['isAchieved'])

        # Shift Attendance
        self.assertEqual(res['shiftPerformance']['shift1MorningCount'], 1)
        self.assertEqual(res['shiftPerformance']['shift2EveningCount'], 1)

    def test_target_rest_api_endpoints(self):
        """Tests REST API endpoints for target management, live achievement, and scorecards."""
        self.client.force_authenticate(user=self.manager_user)

        # 1. POST /api/marketing/targets/
        payload = {
            'title': 'Q3 High Value Campaign',
            'assigned_to_id': self.mpo_user.id,
            'period_type': 'QUARTERLY',
            'start_date': '2026-07-01',
            'end_date': '2026-09-30',
            'target_type': 'HYBRID',
            'territory_name': 'Dhaka North',
            'notes': 'Focus on hospital doctors',
            'items': [
                {
                    'product_id': self.product_a.id,
                    'target_quantity': 400
                },
                {
                    'product_id': self.product_b.id,
                    'target_quantity': 250
                }
            ]
        }
        res = self.client.post('/api/marketing/targets/', data=payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        target_id = res.data['id']
        assigned_user = (res.data.get('assigned_to') or res.data.get('assignedTo') or {}).get('username') or res.data.get('assigned_to_username') or res.data.get('assignedToUsername')
        self.assertEqual(assigned_user, 'mpo_tanvir')
        items = res.data.get('product_items') or res.data.get('productItems')
        self.assertEqual(len(items), 2)

        # 2. GET /api/marketing/targets/{id}/achievement/
        res_ach = self.client.get(f'/api/marketing/targets/{target_id}/achievement/')
        self.assertEqual(res_ach.status_code, status.HTTP_200_OK)
        target_id_returned = res_ach.data.get('targetId') or res_ach.data.get('target_id')
        self.assertEqual(target_id_returned, target_id)
        self.assertIn('assignedTo', res_ach.data)
        self.assertEqual(res_ach.data['assignedTo']['username'], 'mpo_tanvir')

        # Test filtering by product_id
        res_ach_filter = self.client.get(f'/api/marketing/targets/{target_id}/achievement/?product_id={self.product_a.id}')
        self.assertEqual(res_ach_filter.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_ach_filter.data['productBreakdown']), 1)
        self.assertEqual(res_ach_filter.data['productBreakdown'][0]['productId'], self.product_a.id)

        # Test filtering by date range and order status
        res_ach_dates = self.client.get(f'/api/marketing/targets/{target_id}/achievement/?start_date=2026-08-01&end_date=2026-08-15&order_status=DELIVERED')
        self.assertEqual(res_ach_dates.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ach_dates.data['startDate'], '2026-08-01')
        self.assertEqual(res_ach_dates.data['endDate'], '2026-08-15')

        # 3. GET /api/marketing/reports/mpo/{user_id}/
        res_scorecard = self.client.get(f'/api/marketing/reports/mpo/{self.mpo_user.id}/')
        self.assertEqual(res_scorecard.status_code, status.HTTP_200_OK)
        self.assertEqual(res_scorecard.data['username'], 'mpo_tanvir')
        total_targets = res_scorecard.data.get('totalTargetsAssigned') or res_scorecard.data.get('total_targets_assigned')
        self.assertEqual(total_targets, 1)

        # 4. GET /api/marketing/reports/consolidated/
        res_team = self.client.get('/api/marketing/reports/consolidated/')
        self.assertEqual(res_team.status_code, status.HTTP_200_OK)
        self.assertIn('leaderboard', res_team.data)
        self.assertGreaterEqual(len(res_team.data['leaderboard']), 1)

    def test_biometric_and_gps_dual_check_in_api(self):
        """Tests dual check-in with GPS and Biometric Fingerprint device integration."""
        self.client.force_authenticate(user=self.mpo_user)

        # 1. Shift 1 Check-In via GPS
        res1 = self.client.post('/api/attendance/check-in/', data={
            'latitude': 23.81033100,
            'longitude': 90.41252100,
            'shift': 1,
            'check_in_method': 'GPS',
            'notes': 'Field morning arrival'
        }, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        method1 = res1.data['data'].get('check_in_method') or res1.data['data'].get('checkInMethod')
        self.assertEqual(method1, 'GPS')

        # 2. Shift 2 Check-In via Biometric
        res2 = self.client.post('/api/attendance/check-in/', data={
            'shift': 2,
            'check_in_method': 'BIOMETRIC_FINGERPRINT',
            'biometric_device_id': 'SCANNER-DHAKA-04',
            'notes': 'Evening office debrief'
        }, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        method2 = res2.data['data'].get('check_in_method') or res2.data['data'].get('checkInMethod')
        self.assertIn(method2, ['BIOMETRIC_FINGERPRINT', 'Biometric Fingerprint'])
        device_id = res2.data['data'].get('biometric_device_id') or res2.data['data'].get('biometricDeviceId')
        self.assertEqual(device_id, 'SCANNER-DHAKA-04')

    def test_dynamic_incentive_tier_configuration_from_lookup(self):
        """Tests that incentive tiers and commission rates adapt dynamically to Lookup table records."""
        # 1. Custom Lookup configuration: Super Tier at 150% with 8% commission
        Lookup.objects.create(name='INCENTIVE_TIER_SUPER_THRESHOLD', value='150.00', is_active=True)
        Lookup.objects.create(name='INCENTIVE_TIER_SUPER_RATE', value='8.00', is_active=True)
        Lookup.objects.create(name='INCENTIVE_TIER_TARGET_THRESHOLD', value='110.00', is_active=True)
        Lookup.objects.create(name='INCENTIVE_TIER_TARGET_RATE', value='4.00', is_active=True)

        target = SalesTarget.objects.create(
            title='Special Campaign',
            assigned_to=self.mpo_user,
            assigned_by=self.manager_user,
            period_type=PeriodType.MONTHLY,
            start_date=datetime.date(2026, 8, 1),
            end_date=datetime.date(2026, 8, 31),
            target_type=TargetType.AMOUNT_WISE,
            total_target_amount=Decimal('100000.00')
        )

        # Book 160,000 BDT sales (160% achievement)
        order = OrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    'product_id': self.product_a.id,
                    'warehouse_id': self.warehouse.id,
                    'batch_number': 'BATCH-2026-A1',
                    'quantity': 640, # 640 * 250 = 160,000
                    'unit_price': '250.00',
                    'vat_percentage': '0.00',
                    'discount_percentage': '0.00'
                }
            ],
            user=self.mpo_user,
            order_date=datetime.date(2026, 8, 15)
        )
        OrderService.deliver_order(order, user=self.manager_user)

        res = TargetService.calculate_target_achievement(target)
        self.assertEqual(res['amountAchievementPercentage'], 160.0)
        self.assertTrue(res['incentiveEvaluation']['isAchieved'])
        self.assertEqual(res['incentiveEvaluation']['incentiveTier'], 'Super Achiever (150%+)')
        self.assertEqual(res['incentiveEvaluation']['commissionRatePercentage'], 8.0)
        # 160,000 * 8% = 12,800 BDT
        self.assertEqual(res['incentiveEvaluation']['potentialCommissionAmount'], '12800.00')
