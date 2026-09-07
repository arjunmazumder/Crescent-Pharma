import datetime
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import CompanyProfile
from accounting.models import AccountHead, AccountType, VoucherType
from accounting.services import VoucherPostingService, AccountingIntegrationService
from inventory.models import Category, Product, Warehouse
from inventory.services import InventoryService
from sales.models import Customer, CustomerOrder, OrderStatus
from sales.services import OrderService

User = get_user_model()


class CompanyProfileTestCase(TestCase):
    """The letterhead every printed document needs."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username='cp_admin', password='pass12345')
        self.client.force_authenticate(user=self.admin)

    def _payload(self, **over):
        data = {
            'name': 'Crescent Pharma Ltd.',
            'address': '12 Gulshan Avenue, Dhaka',
            'city': 'Dhaka',
            'business_identification_number': '004123456789',
            'tax_identification_number': '123456789012',
            'drug_license_number': 'DGDA-MFG-1180',
        }
        data.update(over)
        return data

    def test_active_returns_404_before_setup(self):
        resp = self.client.get('/api/core/company-profile/active/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('No company profile', str(resp.data))

    def test_create_and_fetch_active(self):
        create = self.client.post('/api/core/company-profile/', self._payload(), format='json')
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.data)

        resp = self.client.get('/api/core/company-profile/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Crescent Pharma Ltd.')
        self.assertEqual(resp.data['business_identification_number'], '004123456789')
        self.assertEqual(resp.data['default_currency'], 'BDT')

    def test_only_one_profile_stays_active(self):
        """A document must never be ambiguous about who issued it."""
        self.client.post('/api/core/company-profile/', self._payload(), format='json')
        self.client.post(
            '/api/core/company-profile/',
            self._payload(name='Crescent Skincare Ltd.'), format='json'
        )

        self.assertEqual(CompanyProfile.objects.count(), 2)
        self.assertEqual(CompanyProfile.objects.filter(is_active=True).count(), 1)
        self.assertEqual(CompanyProfile.get_active().name, 'Crescent Skincare Ltd.')

    def test_profile_requires_authentication(self):
        self.assertEqual(
            APIClient().get('/api/core/company-profile/active/').status_code,
            status.HTTP_401_UNAUTHORIZED
        )


class InvoicePayloadTestCase(TestCase):
    """What the frontend needs on screen to print a pharmaceutical invoice."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(username='inv_admin', password='pass12345')
        self.client.force_authenticate(user=self.user)

        self.customer = Customer.objects.create(
            name='Popular Pharmacy', phone='01711000000',
            drug_license_no='DGDA-RET-9911',
            drug_license_expiry_date=datetime.date(2027, 12, 31),
            address='Mirpur 10, Dhaka',
        )
        cat = Category.objects.create(name='Tablets', code='TAB-INV')
        self.product = Product.objects.create(
            name='Napa 500mg', generic_name='Paracetamol',
            category=cat, selling_price=Decimal('100.00'), vat_percentage=Decimal('5.00')
        )
        self.warehouse = Warehouse.objects.create(name='Dhaka Depot', code='WH-INV')
        InventoryService.record_stock_movement(
            product=self.product, warehouse=self.warehouse, batch_number='B-INV-1',
            movement_type='IN', quantity=100, user=self.user
        )

    def test_order_response_carries_the_buyer_drug_licence(self):
        order = OrderService.create_order(
            customer=self.customer, user=self.user,
            items_data=[{'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
                         'batch_number': 'B-INV-1', 'quantity': 5}],
        )
        resp = self.client.get(f'/api/customer-orders/{order.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        customer = resp.data['customer']
        self.assertEqual(customer['drug_license_no'], 'DGDA-RET-9911')
        self.assertEqual(str(customer['drug_license_expiry_date']), '2027-12-31')

        line = resp.data['items'][0]
        self.assertEqual(line['product']['name'], 'Napa 500mg')
        self.assertEqual(line['batch_number'], 'B-INV-1')
        self.assertEqual(line['quantity'], 5)


class BillDraftTestCase(TestCase):
    """Save an in-progress bill, come back to it, edit it, then finalise."""

    def setUp(self):
        self.client = APIClient()
        self.officer = User.objects.create_user(username='draft_mpo', password='pass12345')
        self.client.force_authenticate(user=self.officer)

        self.customer = Customer.objects.create(name='Alif Medicine Corner', phone='01811000000')
        cat = Category.objects.create(name='Syrup', code='SYR-DR')
        self.product = Product.objects.create(
            name='Ace Syrup', generic_name='Paracetamol',
            category=cat, selling_price=Decimal('120.00')
        )
        self.warehouse = Warehouse.objects.create(name='Field Van', code='WH-DR')
        InventoryService.record_stock_movement(
            product=self.product, warehouse=self.warehouse, batch_number='B-DR-1',
            movement_type='IN', quantity=100, user=self.officer
        )

    def _items(self, qty):
        return [{'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
                 'batch_number': 'B-DR-1', 'quantity': qty}]

    def _stock(self):
        from inventory.models import StockLevel
        return StockLevel.objects.get(
            product=self.product, warehouse=self.warehouse, batch_number='B-DR-1'
        )

    def test_draft_saves_without_reserving_stock(self):
        """A bill left open mid-negotiation must not hold someone else's stock."""
        resp = self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(10), 'as_draft': True},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data['status'], OrderStatus.DRAFT)
        self.assertEqual(self._stock().reserved_quantity, 0)

    def test_normal_order_still_reserves(self):
        self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(10)},
            format='json'
        )
        self.assertEqual(self._stock().reserved_quantity, 10)

    def test_my_drafts_lists_only_drafts(self):
        self.client.post('/api/customer-orders/',
                         {'customer_id': self.customer.id, 'items': self._items(3), 'as_draft': True},
                         format='json')
        self.client.post('/api/customer-orders/',
                         {'customer_id': self.customer.id, 'items': self._items(2)},
                         format='json')

        resp = self.client.get('/api/customer-orders/my-drafts/')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['data'][0]['status'], OrderStatus.DRAFT)

    def test_edit_draft_recomputes_totals(self):
        created = self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(2), 'as_draft': True},
            format='json'
        )
        draft_id = created.data['id']
        self.assertEqual(created.data['total_amount'], '240.00')

        resp = self.client.patch(
            f'/api/customer-orders/{draft_id}/update-draft/',
            {'items': self._items(5), 'discount_flat': '100.00'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # 5 x 120 = 600, less a flat 100
        self.assertEqual(resp.data['data']['total_amount'], '500.00')
        self.assertEqual(len(resp.data['data']['items']), 1)
        self.assertEqual(resp.data['data']['items'][0]['quantity'], 5)

    def test_editing_a_draft_leaves_no_orphan_lines(self):
        created = self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(2), 'as_draft': True},
            format='json'
        )
        draft = CustomerOrder.objects.get(id=created.data['id'])
        self.client.patch(f'/api/customer-orders/{draft.id}/update-draft/',
                          {'items': self._items(7)}, format='json')
        self.assertEqual(draft.items.count(), 1)

    def test_confirming_a_draft_finally_reserves_the_stock(self):
        """The gap that would ship goods the order never held."""
        created = self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(8), 'as_draft': True},
            format='json'
        )
        self.assertEqual(self._stock().reserved_quantity, 0)

        confirm = self.client.post(f"/api/customer-orders/{created.data['id']}/confirm/")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
        self.assertEqual(confirm.data['data']['status'], OrderStatus.CONFIRMED)
        self.assertEqual(self._stock().reserved_quantity, 8)

    def test_confirmed_order_cannot_be_edited_as_a_draft(self):
        created = self.client.post(
            '/api/customer-orders/',
            {'customer_id': self.customer.id, 'items': self._items(2)},
            format='json'
        )
        resp = self.client.patch(
            f"/api/customer-orders/{created.data['id']}/update-draft/",
            {'items': self._items(9)}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Only DRAFT orders can be edited', str(resp.data))


class DashboardTestCase(TestCase):
    """The landing screen, built from data other modules have already posted."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command('seed_chart_of_accounts')

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username='dash_admin', password='pass12345')
        self.client.force_authenticate(user=self.admin)

        self.today = datetime.date.today()
        self.customer = Customer.objects.create(name='City Pharmacy', phone='01911000000')
        cat = Category.objects.create(name='Capsule', code='CAP-DSH')
        self.product = Product.objects.create(
            name='Seclo 20mg', generic_name='Omeprazole',
            category=cat, selling_price=Decimal('200.00'),
            purchase_price=Decimal('120.00')
        )
        self.warehouse = Warehouse.objects.create(name='Central', code='WH-DSH')
        InventoryService.record_stock_movement(
            product=self.product, warehouse=self.warehouse, batch_number='B-DSH-1',
            movement_type='IN', quantity=100, user=self.admin
        )

    def _order(self, qty):
        return OrderService.create_order(
            customer=self.customer, user=self.admin, order_date=self.today,
            items_data=[{'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
                         'batch_number': 'B-DSH-1', 'quantity': qty}],
        )

    def test_summary_is_empty_on_a_quiet_day(self):
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['today']['ordersCount'], 0)
        self.assertEqual(resp.data['today']['salesValue'], '0.00')
        self.assertEqual(resp.data['today']['incomeCollected'], '0.00')
        self.assertEqual(resp.data['today']['expense'], '0.00')

    def test_summary_counts_todays_sales_and_customers(self):
        self._order(3)
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.data['today']['ordersCount'], 1)
        self.assertEqual(resp.data['today']['customersOrdered'], 1)
        self.assertEqual(resp.data['today']['newCustomers'], 1)
        self.assertEqual(resp.data['today']['salesValue'], '600.00')

    def test_cancelled_orders_do_not_count_as_sales(self):
        order = self._order(3)
        OrderService.cancel_order(order, reason='Customer changed mind', user=self.admin)
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.data['today']['ordersCount'], 0)
        self.assertEqual(resp.data['today']['salesValue'], '0.00')

    def test_income_is_money_collected_not_invoiced(self):
        """Sales on credit must not show up as income until the cash arrives."""
        order = self._order(5)
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.data['today']['salesValue'], '1000.00')
        self.assertEqual(resp.data['today']['incomeCollected'], '0.00')

        AccountingIntegrationService.post_customer_payment(
            order=order, amount=Decimal('400.00'), payment_method='CASH',
            deposit_account=AccountHead.objects.get(code='1111'), user=self.admin
        )
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.data['today']['incomeCollected'], '400.00')
        self.assertEqual(resp.data['month']['outstanding'], '600.00')

    def test_expense_comes_from_the_ledger(self):
        VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.JOURNAL,
            voucher_date=self.today,
            narration='Office rent',
            entries_data=[
                {'account_id': AccountHead.objects.get(code='6210').id,
                 'debit_amount': Decimal('5000.00'), 'credit_amount': Decimal('0.00')},
                {'account_id': AccountHead.objects.get(code='1111').id,
                 'debit_amount': Decimal('0.00'), 'credit_amount': Decimal('5000.00')},
            ],
            user=self.admin,
        )
        resp = self.client.get('/api/core/dashboard/summary/')
        self.assertEqual(resp.data['today']['expense'], '5000.00')
        self.assertEqual(resp.data['today']['netCashFlow'], '-5000.00')

    def test_sales_vs_expense_series_shape(self):
        self._order(2)
        resp = self.client.get('/api/core/dashboard/sales-vs-expense/?months=3')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['series']), 3)

        # Oldest first, current month last.
        last = resp.data['series'][-1]
        self.assertEqual(last['year'], self.today.year)
        self.assertEqual(last['month'], self.today.month)
        self.assertEqual(last['salesValue'], '400.00')

    def test_series_rejects_a_silly_month_count(self):
        resp = self.client.get('/api/core/dashboard/sales-vs-expense/?months=abc')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        clamped = self.client.get('/api/core/dashboard/sales-vs-expense/?months=999')
        self.assertEqual(len(clamped.data['series']), 36)

    def test_dashboard_requires_authentication(self):
        self.assertEqual(
            APIClient().get('/api/core/dashboard/summary/').status_code,
            status.HTTP_401_UNAUTHORIZED
        )
