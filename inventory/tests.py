from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal
from django.contrib.auth import get_user_model
from inventory.models import Product, Warehouse, Category, StockLevel, StockMovement
from inventory.services import InventoryService
from accounting.models import Voucher, JournalEntry, VoucherStatus

User = get_user_model()


class InventoryDamageAndLossTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='inventory_officer',
            password='TestPassword123',
            is_staff=True
        )
        self.client.force_authenticate(user=self.user)

        self.category = Category.objects.create(name='Antibiotics', code='ANTIBIOTIC')
        self.product = Product.objects.create(
            name='Ciprocin 500',
            generic_name='Ciprofloxacin',
            category=self.category,
            purchase_price=Decimal('100.00'),
            selling_price=Decimal('150.00'),
            min_stock_level=50,
            unit='Box'
        )
        self.warehouse = Warehouse.objects.create(
            name='Dhaka Main Depot',
            code='DHK-01',
            address='Tejgaon, Dhaka'
        )

        # Inward 200 boxes first
        InventoryService.record_stock_movement(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            movement_type='IN',
            quantity=200,
            user=self.user
        )

    def test_damage_and_loss_api(self):
        # 1. Record 10 boxes direct physical damage
        InventoryService.record_stock_movement(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            movement_type='DAMAGE',
            quantity=10,
            notes='Water leakage damage',
            user=self.user
        )

        # Current stock is now 190 boxes.
        # 2. Perform Audit Adjustment: Auditor counts only 185 boxes (5 boxes missing/shrinkage)
        adjust_url = reverse('stockmovements-adjust-stock')
        adjust_payload = {
            'productId': self.product.id,
            'warehouseId': self.warehouse.id,
            'batchNumber': 'BATCH-DAM-01',
            'newQuantity': 185,
            'referenceNo': 'AUDIT-2026-Q1',
            'notes': 'Quarterly physical inventory count audit'
        }
        adjust_res = self.client.post(adjust_url, adjust_payload, format='json')
        self.assertEqual(adjust_res.status_code, status.HTTP_200_OK)
        self.assertEqual(adjust_res.data['variance'], -5)
        self.assertEqual(adjust_res.data['varianceStatus'], 'SHRINKAGE_LOSS')
        self.assertEqual(adjust_res.data['estimatedFinancialLoss'], '500.00')

        # 3. Query GET /api/stock-movements/damages/ (should include both 10 damaged + 5 shrinkage = 15 total lost)
        url = reverse('stockmovements-damages')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data['totalDamageAndLossIncidents'], 2)
        self.assertEqual(data['totalDamagedQuantity'], 10)
        self.assertEqual(data['totalShrinkageQuantity'], 5)
        self.assertEqual(data['totalLostQuantity'], 15)
        self.assertEqual(data['totalDamageLossValue'], '1000.00')
        self.assertEqual(data['totalShrinkageLossValue'], '500.00')
        self.assertEqual(data['totalEstimatedFinancialLoss'], '1500.00')
        self.assertEqual(len(data['warehouseBreakdown']), 1)
        self.assertEqual(data['warehouseBreakdown'][0]['warehouseName'], 'Dhaka Main Depot')
        self.assertEqual(data['warehouseBreakdown'][0]['totalLostQuantity'], 15)
        self.assertEqual(data['warehouseBreakdown'][0]['totalLossValue'], '1500.00')

    def test_damage_and_shrinkage_reach_the_ledger(self):
        """
        The damage report always valued these losses, but nothing posted them,
        so inventory on the balance sheet stayed overstated.
        """
        InventoryService.record_stock_movement(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            movement_type='DAMAGE',
            quantity=10,
            notes='Water leakage damage',
            user=self.user
        )

        vouchers = Voucher.objects.filter(source_module='INVENTORY_DAMAGE')
        self.assertEqual(vouchers.count(), 1, "Damage write-off was not booked to the ledger.")

        voucher = vouchers.first()
        self.assertEqual(voucher.status, VoucherStatus.POSTED)
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        # 10 boxes at a 100.00 purchase price.
        self.assertEqual(voucher.total_debit, Decimal('1000.00'))
        # Dr 5300 damaged stock loss, Cr 1140 inventory.
        self.assertEqual(voucher.entries.get(account__code='5300').debit_amount, Decimal('1000.00'))
        self.assertEqual(voucher.entries.get(account__code='1140').credit_amount, Decimal('1000.00'))

        # An audit finding 5 boxes short is the same kind of loss.
        InventoryService.adjust_stock(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            new_quantity=185,
            reference_no='AUDIT-2026-Q1',
            user=self.user
        )
        self.assertEqual(Voucher.objects.filter(source_module='INVENTORY_DAMAGE').count(), 2)
        shrinkage = Voucher.objects.filter(source_module='INVENTORY_DAMAGE').order_by('-id').first()
        self.assertEqual(shrinkage.total_debit, Decimal('500.00'))

    def test_normal_inflow_does_not_touch_the_ledger(self):
        """Only losses post. A routine receipt must not book an expense."""
        InventoryService.record_stock_movement(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            movement_type='IN',
            quantity=50,
            user=self.user
        )
        self.assertEqual(Voucher.objects.filter(source_module='INVENTORY_DAMAGE').count(), 0)

    def test_audit_surplus_does_not_book_a_loss(self):
        """Counting more than the system says is not a loss."""
        InventoryService.adjust_stock(
            product=self.product,
            warehouse=self.warehouse,
            batch_number='BATCH-DAM-01',
            new_quantity=250,
            user=self.user
        )
        self.assertEqual(Voucher.objects.filter(source_module='INVENTORY_DAMAGE').count(), 0)
