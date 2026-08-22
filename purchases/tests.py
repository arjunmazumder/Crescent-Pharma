import datetime
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from purchases.models import (
    Supplier, SupplierType, SupplyCategory, AuditStatus,
    PurchaseOrder, PurchaseOrderItem, OrderStatus,
    LetterOfCredit, LetterOfCreditType, LetterOfCreditStatus,
    GoodsReceivedNote, GoodsReceivedNoteStatus
)
from purchases.services import (
    PurchaseOrderService, LCManagementService, LandedCostService, GoodsReceiptService
)
from inventory.models import Category, Product, Warehouse, StockLevel, StockMovement
from accounting.models import AccountHead, AccountType, FiscalYear, AccountingPeriod

User = get_user_model()


class PurchasesModuleTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='procurement_officer', password='password123')
        self.client.force_authenticate(user=self.user)

        # 1. Setup Accounting Chart of Accounts
        self.asset_head = AccountHead.objects.create(
            code='1000', name='Assets', account_type=AccountType.ASSET, is_group=True
        )
        self.current_assets = AccountHead.objects.create(
            code='1100', name='Current Assets', account_type=AccountType.ASSET, parent=self.asset_head, is_group=True
        )
        self.bank_head = AccountHead.objects.create(
            code='1112', name='Sonali Bank Corporate CD A/C', account_type=AccountType.ASSET, parent=self.current_assets, is_reconciliation=True
        )
        self.lc_margin_head = AccountHead.objects.create(
            code='1160', name='LC Margin & Advance Asset', account_type=AccountType.ASSET, parent=self.current_assets, is_reconciliation=True
        )
        self.inv_head = AccountHead.objects.create(
            code='1141', name='Raw & Packaging Material Inventory', account_type=AccountType.ASSET, parent=self.current_assets
        )
        self.liab_head = AccountHead.objects.create(
            code='2000', name='Liabilities', account_type=AccountType.LIABILITY, is_group=True
        )
        self.current_liab = AccountHead.objects.create(
            code='2100', name='Current Liabilities', account_type=AccountType.LIABILITY, parent=self.liab_head, is_group=True
        )
        self.ap_head = AccountHead.objects.create(
            code='2110', name='Accounts Payable', account_type=AccountType.LIABILITY, parent=self.current_liab
        )

        # 2. Setup Inventory Products and Warehouses
        self.category = Category.objects.create(name='Active Pharmaceutical Ingredients', code='CAT-API')
        self.product_paracetamol = Product.objects.create(
            name='Paracetamol BP Micronized',
            generic_name='Paracetamol',
            category=self.category,
            unit='KG',
            purchase_price=Decimal('18.00'),
            selling_price=Decimal('25.00')
        )
        self.product_binder = Product.objects.create(
            name='Microcrystalline Cellulose (MCC PH-102)',
            generic_name='Cellulose',
            category=self.category,
            unit='KG',
            purchase_price=Decimal('4.50'),
            selling_price=Decimal('7.00')
        )
        self.warehouse = Warehouse.objects.create(
            name='Savar Central Raw Material Warehouse',
            code='WH-SAVAR-RM',
            address='Savar Plant, Dhaka'
        )

        # 3. Setup Suppliers
        today = timezone.now().date()
        self.supplier_local = Supplier.objects.create(
            company_name='Bengal Packaging & Cartons Ltd',
            supplier_type=SupplierType.LOCAL,
            supply_category=SupplyCategory.PACKAGING_SECONDARY,
            country='Bangladesh',
            currency='BDT',
            phone_number='+8801711000001',
            office_address='Tejgaon I/A, Dhaka',
            drug_license_number='DL-DH-98231',
            drug_license_expiry_date=today + datetime.timedelta(days=365)
        )
        self.supplier_overseas = Supplier.objects.create(
            company_name='Sinochem International Raw Materials',
            supplier_type=SupplierType.OVERSEAS,
            supply_category=SupplyCategory.API,
            country='China',
            currency='USD',
            phone_number='+862168880000',
            office_address='Pudong New Area, Shanghai, China',
            drug_license_number='IMP-DGDA-2026-091',
            drug_license_expiry_date=today + datetime.timedelta(days=500)
        )

    def test_supplier_auto_code_generation(self):
        self.assertTrue(self.supplier_local.supplier_code.startswith('SUP-'))
        self.assertTrue(self.supplier_overseas.supplier_code.startswith('SUP-'))
        self.assertNotEqual(self.supplier_local.supplier_code, self.supplier_overseas.supplier_code)

    def test_purchase_order_creation_and_approval(self):
        items_data = [
            {
                'product_id': self.product_paracetamol.id,
                'ordered_quantity': Decimal('1000.000'),
                'unit_price_in_order_currency': Decimal('18.50'),
                'technical_specifications': 'USP Grade, Assay > 99.5%'
            },
            {
                'product_id': self.product_binder.id,
                'ordered_quantity': Decimal('500.000'),
                'unit_price_in_order_currency': Decimal('4.00'),
                'technical_specifications': 'PH-102 Grade'
            }
        ]

        po = PurchaseOrderService.create_order(
            supplier=self.supplier_overseas,
            items_data=items_data,
            user=self.user,
            currency='USD',
            exchange_rate=Decimal('120.0000'),
            delivery_warehouse=self.warehouse
        )

        self.assertTrue(po.purchase_order_number.startswith('PO-'))
        self.assertEqual(po.status, OrderStatus.DRAFT)
        # Expected foreign total: (1000 * 18.50) + (500 * 4.00) = 18500 + 2000 = 20500 USD
        self.assertEqual(po.total_amount_in_foreign_currency, Decimal('20500.00'))
        # Expected BDT total: 20500 * 120 = 2,460,000 BDT
        self.assertEqual(po.total_amount_in_bdt, Decimal('2460000.00'))
        self.assertEqual(po.items.count(), 2)

        # Approve PO
        approved_po = PurchaseOrderService.approve_order(po, user=self.user)
        self.assertEqual(approved_po.status, OrderStatus.APPROVED)
        self.assertEqual(approved_po.approved_by, self.user)
        self.assertIsNotNone(approved_po.approved_at)

    def test_letter_of_credit_creation_and_landed_cost_allocation(self):
        # 1. Create PO
        items_data = [
            {'product_id': self.product_paracetamol.id, 'ordered_quantity': Decimal('1000.000'), 'unit_price_in_order_currency': Decimal('10.00')}, # 10,000 USD (50%)
            {'product_id': self.product_binder.id, 'ordered_quantity': Decimal('2000.000'), 'unit_price_in_order_currency': Decimal('5.00')},   # 10,000 USD (50%)
        ]
        po = PurchaseOrderService.create_order(
            supplier=self.supplier_overseas,
            items_data=items_data,
            currency='USD',
            exchange_rate=Decimal('100.0000')
        )
        # Base BDT: (10,000 + 10,000) * 100 = 2,000,000 BDT

        today = timezone.now().date()
        lc = LCManagementService.create_letter_of_credit(
            supplier=self.supplier_overseas,
            purchase_order=po,
            issuing_bank_account=self.bank_head,
            issuing_branch_name='Principal Branch, Dhaka',
            lc_opening_date=today,
            lc_expiry_date=today + datetime.timedelta(days=90),
            total_amount_in_foreign_currency=Decimal('20000.00'),
            exchange_rate_to_bdt=Decimal('100.0000'),
            bank_margin_percentage=Decimal('10.00'),
            post_margin_voucher=False,
            user=self.user
        )

        self.assertTrue(lc.letter_of_credit_number.startswith('LC-'))
        self.assertEqual(lc.total_amount_in_bdt, Decimal('2000000.00'))
        self.assertEqual(lc.bank_margin_amount_in_bdt, Decimal('200000.00'))
        self.assertEqual(lc.status, LetterOfCreditStatus.OPENED)

        # 2. Landed Cost calculation: add 200,000 BDT duties & freight
        LandedCostService.calculate_and_save_landed_cost(
            letter_of_credit=lc,
            cost_data={
                'customs_duty': Decimal('100000.00'),
                'regulatory_duty': Decimal('20000.00'),
                'value_added_tax': Decimal('50000.00'),
                'freight_charges': Decimal('30000.00'),
            },
            finalize=True
        )

        allocations = LandedCostService.get_allocated_landed_costs(lc)
        # Each item had equal base value (1,000,000 BDT each).
        # Total duties: 200,000 BDT -> 100,000 BDT added to each item.
        # Paracetamol total landed: 1,000,000 + 100,000 = 1,100,000 BDT / 1000 KG = 1,100 BDT/KG
        # Binder total landed: 1,000,000 + 100,000 = 1,100,000 BDT / 2000 KG = 550 BDT/KG
        item_para = po.items.filter(product=self.product_paracetamol).first()
        item_binder = po.items.filter(product=self.product_binder).first()

        self.assertEqual(allocations[item_para.id]['unit_landed_cost'], Decimal('1100.0000'))
        self.assertEqual(allocations[item_binder.id]['unit_landed_cost'], Decimal('550.0000'))

    def test_goods_receipt_updates_inventory_and_product_price(self):
        items_data = [
            {'product_id': self.product_paracetamol.id, 'ordered_quantity': Decimal('500.000'), 'unit_price_in_order_currency': Decimal('1500.00')}
        ]
        po = PurchaseOrderService.create_order(
            supplier=self.supplier_local,
            items_data=items_data,
            currency='BDT',
            exchange_rate=Decimal('1.0000')
        )
        po_item = po.items.first()

        today = timezone.now().date()
        grn_items = [
            {
                'product_id': self.product_paracetamol.id,
                'purchase_order_item_id': po_item.id,
                'batch_number': 'BATCH-PARA-2026-01',
                'manufacturing_date': today - datetime.timedelta(days=10),
                'expiry_date': today + datetime.timedelta(days=700),
                'challan_quantity': Decimal('500.000'),
                'received_quantity': Decimal('500.000'),
                'accepted_quantity': Decimal('500.000'),
                'unit_landed_cost': Decimal('1500.00')
            }
        ]

        grn = GoodsReceiptService.create_grn(
            receiving_warehouse=self.warehouse,
            items_data=grn_items,
            purchase_order=po,
            challan_number='CHAL-9921',
            user=self.user
        )
        self.assertEqual(grn.status, GoodsReceivedNoteStatus.DRAFT)

        # Approve GRN
        approved_grn = GoodsReceiptService.approve_and_receive_grn(grn, user=self.user)
        self.assertEqual(approved_grn.status, GoodsReceivedNoteStatus.APPROVED)

        # Verify physical inventory stock in StockLevel
        stock = StockLevel.objects.get(
            product=self.product_paracetamol,
            warehouse=self.warehouse,
            batch_number='BATCH-PARA-2026-01'
        )
        self.assertEqual(stock.quantity, 500)
        self.assertEqual(stock.mfg_date, today - datetime.timedelta(days=10))

        # Verify StockMovement IN
        movement = StockMovement.objects.filter(
            product=self.product_paracetamol,
            batch_number='BATCH-PARA-2026-01',
            movement_type=StockMovement.MOVEMENT_TYPE_CHOICES['IN']
        ).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 500)

        # Verify PO completion
        po.refresh_from_db()
        self.assertEqual(po.status, OrderStatus.COMPLETED)

        # Verify Product purchase_price updated
        self.product_paracetamol.refresh_from_db()
        self.assertEqual(self.product_paracetamol.purchase_price, Decimal('1500.00'))

    def test_api_endpoints(self):
        # 1. Test Supplier API
        res = self.client.get('/api/purchases/suppliers/')
        self.assertEqual(res.status_code, 200)
        supplier_count = len(res.data['results']) if 'results' in res.data else len(res.data)
        self.assertGreaterEqual(supplier_count, 2)

        # 2. Test Reports Dashboard API
        res_rep = self.client.get('/api/purchases/reports/dashboard/')
        self.assertEqual(res_rep.status_code, 200)
        self.assertIn('supplier_metrics', res_rep.data)
        self.assertIn('po_metrics', res_rep.data)
