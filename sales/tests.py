from decimal import Decimal
import datetime
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from sales.models import Customer, CustomerOrder, CustomerOrderItem, CustomerType, OrderStatus, PaymentStatus, PaymentMethod
from sales.services import OrderService
from inventory.models import Category, Product, Warehouse, StockLevel, StockMovement
from inventory.services import InventoryService

User = get_user_model()


class SalesModuleTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='sales_rep',
            email='rep@crescent.com',
            password='Password@123',
            is_staff=True
        )
        self.client.force_authenticate(user=self.user)

        self.category = Category.objects.create(name='Tablets', code='CAT-TAB')
        self.product = Product.objects.create(
            name='Napa Extra',
            generic_name='Paracetamol + Caffeine',
            category=self.category,
            selling_price=Decimal('250.00'),
            purchase_price=Decimal('200.00'),
            vat_percentage=Decimal('5.00')
        )
        self.warehouse = Warehouse.objects.create(
            name='Central Dhaka Warehouse',
            code='WH-DHK-01'
        )

        # Receive 100 boxes into inventory
        self.stock_level, _ = InventoryService.record_stock_movement(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-2026-A1',
            movement_type='IN',
            quantity=100,
            user=self.user
        )

        # Create valid active customer
        self.customer = Customer.objects.create(
            name='Lazz Pharma',
            proprietor_name='Lutfur Rahman',
            phone='+8801711223344',
            drug_license_no='DGDA-998811',
            drug_license_expiry_date=timezone.now().date() + datetime.timedelta(days=365),
            customer_type=CustomerType.RETAIL,
            address='Kalabagan, Mirpur Road, Dhaka',
            city='Dhaka'
        )

    def test_customer_auto_code_generation(self):
        """Tests that customer code is automatically generated sequentially."""
        self.assertEqual(self.customer.customer_code, 'CUST-0001')
        second_customer = Customer.objects.create(
            name='Square Pharmacy',
            phone='+8801811223344'
        )
        self.assertEqual(second_customer.customer_code, 'CUST-0002')

    def test_create_order_with_automatic_calculations(self):
        """Tests creating an order with item-level pricing, discounts, and VAT calculation."""
        items_data = [
            {
                'product_id': self.product.id,
                'warehouse_id': self.warehouse.id,
                'batch_number': 'BATCH-2026-A1',
                'quantity': 10,
                'unit_price': '250.00',
                'vat_percentage': '5.00',
                'discount_percentage': '0.00'
            }
        ]

        order = OrderService.create_order(
            customer=self.customer,
            items_data=items_data,
            user=self.user,
            discount_percentage=Decimal('2.00'), # 2% overall order discount
            discount_flat=Decimal('50.00'),       # 50 BDT flat cash discount
            payment_method=PaymentMethod.CASH
        )

        self.assertTrue(order.order_number.startswith(f"ORD-{timezone.now().year}-"))
        self.assertEqual(order.items.count(), 1)
        
        # Subtotal: 10 * 250 = 2500.00
        self.assertEqual(order.subtotal, Decimal('2500.00'))
        # VAT: 5% of 2500 = 125.00
        self.assertEqual(order.tax_amount, Decimal('125.00'))
        # Discount: 2% of 2500 (50.00) + 50.00 flat = 100.00
        # Net: 2500 - 100 + 125 = 2525.00
        self.assertEqual(order.total_amount, Decimal('2525.00'))
        self.assertEqual(order.status, OrderStatus.PENDING)

    def test_drug_license_expired_prevents_order_creation(self):
        """Tests that attempting to create an order for an expired drug license customer raises a ValueError."""
        expired_customer = Customer.objects.create(
            name='Expired Meds Store',
            phone='+8801999887766',
            drug_license_no='DGDA-EXPIRED',
            drug_license_expiry_date=timezone.now().date() - datetime.timedelta(days=10)
        )

        items_data = [{'product_id': self.product.id, 'quantity': 5}]
        with self.assertRaises(ValueError) as ctx:
            OrderService.create_order(customer=expired_customer, items_data=items_data, user=self.user)
        self.assertIn("Drug License expired", str(ctx.exception))

    def test_deliver_order_deducts_inventory_stock(self):
        """Tests that delivering an order automatically deducts stock and logs OUT movement."""
        items_data = [
            {
                'product_id': self.product.id,
                'warehouse_id': self.warehouse.id,
                'batch_number': 'BATCH-2026-A1',
                'quantity': 20
            }
        ]
        order = OrderService.create_order(customer=self.customer, items_data=items_data, user=self.user)
        OrderService.deliver_order(order=order, user=self.user)

        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.quantity, 80) # 100 - 20 = 80

        # Check stock movement record
        movement = StockMovement.objects.filter(reference_no=order.order_number, movement_type='OUT').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 20)
        self.assertEqual(movement.new_stock, 80)

    def test_cancel_order_with_rollback(self):
        """Tests that cancelling a delivered order restores stock and requires a reason."""
        items_data = [
            {
                'product_id': self.product.id,
                'warehouse_id': self.warehouse.id,
                'batch_number': 'BATCH-2026-A1',
                'quantity': 30
            }
        ]
        order = OrderService.create_order(customer=self.customer, items_data=items_data, user=self.user)
        OrderService.deliver_order(order=order, user=self.user)
        
        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.quantity, 70) # 100 - 30

        # Now cancel the delivered order
        OrderService.cancel_order(order=order, reason="Pharmacy returned full shipment due to wrong batch", user=self.user)
        self.assertEqual(order.status, OrderStatus.CANCELLED)

        # Check stock rolled back to 100
        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.quantity, 100)

    def test_customer_order_history_and_summary_api(self):
        """Tests REST API endpoints for customer list, create order, order history, and summary."""
        # 1. Test Customer List API
        resp = self.client.get('/api/customers/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

        # 2. Test Customer Create Order API
        order_payload = {
            'customerId': self.customer.id,
            'paymentMethod': 'CASH',
            'discountPercentage': 0,
            'discountFlat': 0,
            'items': [
                {
                    'productId': self.product.id,
                    'warehouseId': self.warehouse.id,
                    'batchNumber': 'BATCH-2026-A1',
                    'quantity': 5,
                    'unitPrice': 250.00
                }
            ]
        }
        create_resp = self.client.post('/api/customer-orders/', data=order_payload, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        order_id = create_resp.data['id']

        # 3. Test Customer Order History endpoint
        history_resp = self.client.get(f'/api/customers/{self.customer.id}/orders/')
        self.assertEqual(history_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history_resp.data['data']), 1)

        # 4. Deliver the order via action endpoint
        deliver_resp = self.client.post(f'/api/customer-orders/{order_id}/deliver/')
        self.assertEqual(deliver_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(deliver_resp.data['data']['status'], 'DELIVERED')

        # 5. Test Customer Summary endpoint
        summary_resp = self.client.get(f'/api/customers/{self.customer.id}/summary/')
        self.assertEqual(summary_resp.status_code, status.HTTP_200_OK)
        total_orders = summary_resp.data.get('total_orders') or summary_resp.data.get('totalOrders')
        delivered_orders = summary_resp.data.get('delivered_orders') or summary_resp.data.get('deliveredOrders')
        self.assertEqual(total_orders, 1)
        self.assertEqual(delivered_orders, 1)

    def test_stock_reservation_lifecycle(self):
        """Tests that stock is reserved on order creation, and released on cancel/delivery."""
        # Initial state: 100 boxes in stock, 0 reserved, 100 available
        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.quantity, 100)
        self.assertEqual(self.stock_level.reserved_quantity, 0)
        self.assertEqual(self.stock_level.available_quantity, 100)

        # Step 1: Create a pending order with 25 boxes
        items_data = [
            {
                'product_id': self.product.id,
                'warehouse_id': self.warehouse.id,
                'batch_number': 'BATCH-2026-A1',
                'quantity': 25
            }
        ]
        order = OrderService.create_order(customer=self.customer, items_data=items_data, user=self.user)
        self.stock_level.refresh_from_db()
        # Physical quantity is still 100, but 25 is reserved, so available is 75!
        self.assertEqual(self.stock_level.quantity, 100)
        self.assertEqual(self.stock_level.reserved_quantity, 25)
        self.assertEqual(self.stock_level.available_quantity, 75)

        # Step 2: Cancel pending order -> Reserved stock should be released back!
        OrderService.cancel_order(order=order, reason="Customer cancelled pending booking", user=self.user)
        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.quantity, 100)
        self.assertEqual(self.stock_level.reserved_quantity, 0)
        self.assertEqual(self.stock_level.available_quantity, 100)

        # Step 3: Re-order 25 boxes and Deliver
        order2 = OrderService.create_order(customer=self.customer, items_data=items_data, user=self.user)
        self.stock_level.refresh_from_db()
        self.assertEqual(self.stock_level.reserved_quantity, 25)
        self.assertEqual(self.stock_level.available_quantity, 75)

        OrderService.deliver_order(order=order2, user=self.user)
        self.stock_level.refresh_from_db()
        # Physical stock decreases to 75, reserved resets to 0, available becomes 75!
        self.assertEqual(self.stock_level.quantity, 75)
        self.assertEqual(self.stock_level.reserved_quantity, 0)
        self.assertEqual(self.stock_level.available_quantity, 75)

