from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal
from django.contrib.auth import get_user_model
from inventory.models import Product, Warehouse, Category, StockLevel, StockMovement
from inventory.services import InventoryService

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
