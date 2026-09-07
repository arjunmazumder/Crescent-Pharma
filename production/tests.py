from decimal import Decimal
import datetime
from unittest import mock
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from inventory.models import Category, Product, Warehouse, StockLevel
from inventory.services import InventoryService
from accounting.models import (
    AccountHead, AccountType, FiscalYear, AccountingPeriod,
    VoucherType, VoucherStatus
)
from production.models import (
    BOMHeader, BOMItem, ProductionLine, ProductionPlan,
    ProductionBatch, MaterialIssueSlip, MaterialIssueItem,
    ProductionStageLog, FinishedGoodsTransfer
)
from production.services import BOMService, ProductionBatchService, ProductionReportService

User = get_user_model()


class ProductionModuleTestCase(TestCase):
    def setUp(self):
        # 1. Create Users
        self.supervisor = User.objects.create_user(
            username='supervisor_pharma',
            email='supervisor@crescentpharma.com',
            password='password123',
            first_name='Dr. Rafiq',
            last_name='Ahmed'
        )
        self.operator = User.objects.create_user(
            username='operator_one',
            email='operator@crescentpharma.com',
            password='password123',
            first_name='Kamal',
            last_name='Hossain'
        )

        # 2. Create Warehouses
        self.raw_warehouse = Warehouse.objects.create(
            name="Central Raw Material Chemical Store",
            code="WH-RAW-01",
            address="Tejgaon I/A, Dhaka"
        )
        self.fg_warehouse = Warehouse.objects.create(
            name="Central Finished Goods Commercial Depot",
            code="WH-FG-01",
            address="Tejgaon I/A, Dhaka"
        )

        # 3. Create Products
        self.cat_solid = Category.objects.create(name="Solid Dosage")
        self.cat_api = Category.objects.create(name="Active Ingredients")
        self.cat_pack = Category.objects.create(name="Packaging Components")

        # Finished Product
        self.finished_med = Product.objects.create(
            name="Crescent Paracetamol 500mg Tablet",
            generic_name="Paracetamol BP",
            unique_id="PRD-MED-0001",
            category=self.cat_solid,
            unit="Tablets",
            purchase_price=Decimal('1.20'),
            selling_price=Decimal('2.50'),
            min_stock_level=10000,
            max_stock_level=500000
        )

        # Raw Material API
        self.raw_api = Product.objects.create(
            name="Paracetamol Powder BP (Active API)",
            generic_name="Paracetamol",
            unique_id="RAW-API-0001",
            category=self.cat_api,
            unit="kg",
            purchase_price=Decimal('450.00'),
            selling_price=Decimal('500.00'),
            min_stock_level=100,
            max_stock_level=5000
        )

        # Packaging Material
        self.foil_pack = Product.objects.create(
            name="Alu-PVC Blister Foil 250mm",
            generic_name="Blister Foil",
            unique_id="PKG-FOIL-0001",
            category=self.cat_pack,
            unit="pcs",
            purchase_price=Decimal('0.80'),
            selling_price=Decimal('1.00'),
            min_stock_level=5000,
            max_stock_level=200000
        )

        # 4. Stock Inflow in Raw Material Store
        InventoryService.record_stock_movement(
            product=self.raw_api,
            warehouse=self.raw_warehouse,
            batch_number="RAW-BATCH-A01",
            movement_type='IN',
            quantity=Decimal('200.0000'),
            mfg_date=timezone.now().date() - datetime.timedelta(days=30),
            expiry_date=timezone.now().date() + datetime.timedelta(days=700),
            reference_no="GRN-RAW-001",
            notes="Initial Raw API stock"
        )
        InventoryService.record_stock_movement(
            product=self.foil_pack,
            warehouse=self.raw_warehouse,
            batch_number="PKG-BATCH-F01",
            movement_type='IN',
            quantity=Decimal('50000.0000'),
            mfg_date=timezone.now().date() - datetime.timedelta(days=30),
            expiry_date=timezone.now().date() + datetime.timedelta(days=700),
            reference_no="GRN-PKG-001",
            notes="Initial Blister Foil stock"
        )

        # 5. Create Production Line
        self.line = ProductionLine.objects.create(
            line_name="High-Speed Rotary Tablet Press Line 1",
            daily_capacity=Decimal('500000.000'),
            cleanroom_classification="Grade D",
            is_active=True
        )

        # 6. Create Accounting Fiscal Year & Period & Heads
        self.today = timezone.now().date()
        self.fiscal_year = FiscalYear.objects.create(
            name="FY 2026",
            code="FY2026",
            start_date=self.today.replace(month=1, day=1),
            end_date=self.today.replace(month=12, day=31),
            is_current=True,
            is_locked=False,
            is_closed=False
        )
        self.period = AccountingPeriod.objects.filter(
            fiscal_year=self.fiscal_year,
            start_date__lte=self.today,
            end_date__gte=self.today
        ).first()
        if not self.period:
            self.period = AccountingPeriod.objects.create(
                fiscal_year=self.fiscal_year,
                name=f"Period {self.today.strftime('%B %Y')}",
                period_number=self.today.month,
                start_date=self.today.replace(day=1),
                end_date=self.today.replace(day=28),
                is_current=True,
                is_locked=False,
                is_closed=False
            )

        AccountHead.objects.get_or_create(
            code='1140',
            defaults={
                'name': 'Finished Goods Inventory Stock',
                'account_type': AccountType.ASSET,
                'is_group': False,
                'is_active': True,
                'currency': 'BDT'
            }
        )
        AccountHead.objects.get_or_create(
            code='1141',
            defaults={
                'name': 'Raw & Packing Materials Inventory',
                'account_type': AccountType.ASSET,
                'is_group': False,
                'is_active': True,
                'currency': 'BDT'
            }
        )

    def test_production_line_auto_generation(self):
        """Tests that ProductionLine.line_code auto-generates LINE-0001 format or supports custom overrides."""
        self.assertTrue(self.line.line_code.startswith("LINE-"))

        custom_line = ProductionLine.objects.create(
            line_code="LINE-SYRUP-CUSTOM-01",
            line_name="Liquid Syrup Line",
            daily_capacity=Decimal('10000.000')
        )
        self.assertEqual(custom_line.line_code, "LINE-SYRUP-CUSTOM-01")

    def test_bom_creation_estimation_and_approval(self):
        """Tests Master Recipe (BOM) creation with mfr_number, scaling estimation, and approval workflow."""
        bom = BOMHeader.objects.create(
            mfr_number="MFR-TAB-PAR-001",
            finished_product=self.finished_med,
            version="v1.0",
            standard_batch_size=Decimal('100000.000'),
            batch_unit="Tablets",
            is_approved=False
        )
        BOMItem.objects.create(
            bom=bom,
            material=self.raw_api,
            material_type=BOMItem.MaterialType.RAW_MATERIAL,
            standard_quantity=Decimal('50.0000'),
            unit="kg",
            wastage_percentage=Decimal('1.00')  # 1% wastage -> 50.5 kg for 100k tabs
        )
        BOMItem.objects.create(
            bom=bom,
            material=self.foil_pack,
            material_type=BOMItem.MaterialType.PACKING_MATERIAL,
            standard_quantity=Decimal('10000.0000'),
            unit="pcs",
            wastage_percentage=Decimal('2.00')  # 2% wastage -> 10200 pcs for 100k tabs
        )

        self.assertTrue(bom.bom_code.startswith("BOM-"))
        self.assertEqual(bom.mfr_number, "MFR-TAB-PAR-001")

        # Estimate for 200,000 tablets (Double batch size)
        estimation = BOMService.estimate_materials(bom=bom, batch_target_quantity=Decimal('200000.000'), source_warehouse=self.raw_warehouse)
        self.assertEqual(estimation['batch_target_quantity'], Decimal('200000.000'))
        self.assertEqual(len(estimation['items']), 2)

        # Item 1: API (50 * 2 * 1.01 = 101.0000 kg)
        api_estimate = next(item for item in estimation['items'] if item['material_id'] == self.raw_api.id)
        self.assertEqual(api_estimate['required_quantity'], Decimal('101.0000'))
        self.assertTrue(api_estimate['is_sufficient'])

        # Approve BOM
        approved_bom = BOMService.approve_bom(bom=bom, user=self.supervisor, remarks="DGDA approved formula")
        self.assertTrue(approved_bom.is_approved)
        self.assertEqual(approved_bom.approved_by, self.supervisor)

    def test_full_manufacturing_lifecycle_flow(self):
        """
        Tests the end-to-end pharmaceutical manufacturing lifecycle:
        1. Schedule Batch with BOM
        2. Issue Raw Materials & verify warehouse stock decreases
        3. Advance through WIP stages (MIXING -> PROCESSING -> FILLING -> PACKAGING -> QC_PENDING)
        4. Log In-Process QC parameters & room conditions
        5. Complete batch & transfer to Finished Goods Warehouse
        6. Verify Finished Goods Stock Inflow & General Ledger Journal Voucher posting
        7. Verify 360° Batch Traceability Audit
        """
        # 1. Setup Approved BOM
        bom = BOMHeader.objects.create(
            mfr_number="MFR-TAB-PAR-001",
            finished_product=self.finished_med,
            version="v1.0",
            standard_batch_size=Decimal('100000.000'),
            batch_unit="Tablets",
            is_approved=True,
            approved_by=self.supervisor
        )
        BOMItem.objects.create(
            bom=bom,
            material=self.raw_api,
            material_type=BOMItem.MaterialType.RAW_MATERIAL,
            standard_quantity=Decimal('50.0000'),
            unit="kg",
            wastage_percentage=Decimal('1.00')
        )
        BOMItem.objects.create(
            bom=bom,
            material=self.foil_pack,
            material_type=BOMItem.MaterialType.PACKING_MATERIAL,
            standard_quantity=Decimal('10000.0000'),
            unit="pcs",
            wastage_percentage=Decimal('2.00')
        )

        # 2. Schedule Production Batch
        mfg_date = timezone.now().date()
        exp_date = mfg_date + datetime.timedelta(days=1095)  # 3 years
        batch = ProductionBatchService.schedule_batch(
            bom=bom,
            planned_quantity=Decimal('100000.000'),
            production_line=self.line,
            source_warehouse=self.raw_warehouse,
            destination_warehouse=self.fg_warehouse,
            manufacturing_date=mfg_date,
            expiry_date=exp_date,
            assigned_supervisor=self.supervisor,
            user=self.supervisor
        )

        self.assertTrue(batch.batch_number.startswith("BATCH-"))
        self.assertEqual(batch.status, ProductionBatch.BatchStatus.SCHEDULED)
        self.assertEqual(batch.current_stage, ProductionBatch.StageChoice.PLANNED)

        # 3. Issue Materials from Store
        raw_api_stock_before = StockLevel.objects.get(product=self.raw_api, warehouse=self.raw_warehouse, batch_number="RAW-BATCH-A01").quantity
        items_to_issue = [
            {
                'material_id': self.raw_api.id,
                'issued_quantity': Decimal('50.0000'),
                'batch_number': 'RAW-BATCH-A01',
                'standard_bom_quantity': Decimal('50.0000')
            },
            {
                'material_id': self.foil_pack.id,
                'issued_quantity': Decimal('10000.0000'),
                'batch_number': 'PKG-BATCH-F01',
                'standard_bom_quantity': Decimal('10000.0000')
            }
        ]

        slip = ProductionBatchService.issue_materials(
            batch=batch,
            warehouse=self.raw_warehouse,
            items_data=items_to_issue,
            user=self.supervisor
        )

        self.assertTrue(slip.issue_number.startswith("MIS-"))
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.BatchStatus.MATERIAL_ISSUED)
        self.assertEqual(batch.current_stage, ProductionBatch.StageChoice.MIXING)

        # Verify Raw Material Stock Decreased
        raw_api_stock_after = StockLevel.objects.get(product=self.raw_api, warehouse=self.raw_warehouse, batch_number="RAW-BATCH-A01").quantity
        self.assertEqual(raw_api_stock_after, raw_api_stock_before - 50)

        # 4. Advance through Stages & Record IPQC Logs
        ProductionBatchService.advance_stage(batch=batch, next_stage=ProductionBatch.StageChoice.PROCESSING, user=self.operator)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage, ProductionBatch.StageChoice.PROCESSING)

        ProductionBatchService.advance_stage(batch=batch, next_stage=ProductionBatch.StageChoice.FILLING, user=self.operator)
        ProductionBatchService.record_stage_qc(
            batch=batch,
            stage=ProductionStageLog.StageName.FILLING,
            status=ProductionStageLog.StageStatus.PASSED,
            operator=self.operator,
            temperature_celsius=Decimal('22.50'),
            humidity_percentage=Decimal('42.00'),
            qc_parameters_json={'average_weight_mg': 650.0, 'hardness_kg': 6.5, 'disintegration_min': 7.5},
            remarks="IPQC Passed, tablets within tolerance"
        )

        ProductionBatchService.advance_stage(batch=batch, next_stage=ProductionBatch.StageChoice.PACKAGING, user=self.operator)
        ProductionBatchService.advance_stage(batch=batch, next_stage=ProductionBatch.StageChoice.QC_PENDING, user=self.supervisor)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.BatchStatus.QC_INSPECTION)

        # 5. Complete Batch & Transfer to Finished Goods Warehouse
        actual_produced = Decimal('99400.000')
        rejected = Decimal('600.000')
        transfer = ProductionBatchService.complete_and_transfer(
            batch=batch,
            actual_produced_quantity=actual_produced,
            rejected_quantity=rejected,
            qc_release_certificate_number="COA-RELEASE-2026-0089",
            destination_warehouse=self.fg_warehouse,
            user=self.supervisor
        )

        self.assertTrue(transfer.transfer_code.startswith("FGT-"))
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.BatchStatus.COMPLETED)
        self.assertEqual(batch.current_stage, ProductionBatch.StageChoice.FINISHED)
        self.assertEqual(batch.actual_produced_quantity, actual_produced)
        self.assertEqual(batch.yield_percentage, Decimal('99.40'))

        # 6. Verify Finished Goods Stock Inflow
        fg_stock = StockLevel.objects.get(
            product=self.finished_med,
            warehouse=self.fg_warehouse,
            batch_number=batch.batch_number
        )
        self.assertEqual(fg_stock.quantity, actual_produced)
        self.assertEqual(fg_stock.mfg_date, mfg_date)
        self.assertEqual(fg_stock.expiry_date, exp_date)

        # 6b. Verify Manufacturing Cost Capitalization Journal Voucher
        transfer.refresh_from_db()
        self.assertIsNotNone(
            transfer.accounting_voucher,
            "Manufacturing cost was not capitalized to the General Ledger."
        )
        voucher = transfer.accounting_voucher
        self.assertEqual(voucher.voucher_type, VoucherType.JOURNAL)
        self.assertEqual(voucher.status, VoucherStatus.POSTED)
        self.assertEqual(voucher.source_module, 'PRODUCTION')
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertGreater(voucher.total_debit, Decimal('0.00'))

        # Debit Finished Goods (1140), Credit Raw & Packing Materials (1141)
        fg_line = voucher.entries.get(account__code='1140')
        rm_line = voucher.entries.get(account__code='1141')
        self.assertEqual(fg_line.debit_amount, voucher.total_debit)
        self.assertEqual(fg_line.credit_amount, Decimal('0.00'))
        self.assertEqual(rm_line.credit_amount, voucher.total_debit)
        self.assertEqual(rm_line.debit_amount, Decimal('0.00'))

        # 7. Verify 360° Batch Traceability Audit
        traceability = ProductionReportService.get_batch_traceability(batch_number=batch.batch_number)
        self.assertEqual(traceability['batch_info']['batch_number'], batch.batch_number)
        self.assertEqual(traceability['batch_info']['yield_percentage'], Decimal('99.40'))
        self.assertEqual(traceability['inventory_status']['current_warehouse_stock'], actual_produced)
        self.assertEqual(len(traceability['issued_materials']), 2)
        self.assertTrue(len(traceability['in_process_qc_logs']) >= 1)
        self.assertEqual(len(traceability['finished_goods_transfers']), 1)

        # 8. Verify Dashboard Metrics
        dashboard = ProductionReportService.get_production_dashboard()
        self.assertEqual(dashboard['overview']['total_batches_count'], 1)
        self.assertEqual(dashboard['overview']['completed_batches_this_month'], 1)
        self.assertEqual(dashboard['overview']['units_produced_this_month'], actual_produced)


class AccountingFailureIsLoggedTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='log_guard', password='x')
        cat = Category.objects.create(name='Tablets', code='TAB-LG')
        self.med = Product.objects.create(name='Napa 500', generic_name='Paracetamol', category=cat)
        self.src = Warehouse.objects.create(name='RM Store', code='WH-RM-LG')
        self.dst = Warehouse.objects.create(name='FG Depot', code='WH-FG-LG')
        self.bom = BOMHeader.objects.create(
            finished_product=self.med, standard_batch_size=Decimal('1000.000'),
            batch_unit='Tablets', is_active=True, is_approved=True
        )
        self.line = ProductionLine.objects.create(line_name='Press 1', is_active=True)
        self.batch = ProductionBatch.objects.create(
            bom=self.bom, finished_product=self.med, production_line=self.line,
            source_warehouse=self.src, destination_warehouse=self.dst,
            planned_quantity=Decimal('1000.000'),
            manufacturing_date=datetime.date(2026, 8, 1),
            expiry_date=datetime.date(2028, 8, 1),
        )

    def test_voucher_failure_is_logged_not_swallowed(self):
        with mock.patch(
            'production.services.VoucherPostingService.create_and_post_voucher',
            side_effect=ValueError("Accounting Period 'August 2026' is locked.")
        ):
            with self.assertLogs('production.services', level='ERROR') as captured:
                transfer = ProductionBatchService.complete_and_transfer(
                    batch=self.batch,
                    actual_produced_quantity=Decimal('990.000'),
                    rejected_quantity=Decimal('10.000'),
                    qc_release_certificate_number='COA-LG-1',
                    user=self.user,
                )

        # The batch still completes; the failure is recorded rather than hidden.
        self.assertIsNone(transfer.accounting_voucher)
        joined = "\n".join(captured.output)
        self.assertIn('Failed to post manufacturing cost voucher', joined)
        self.assertIn(self.batch.batch_number, joined)
        self.assertIn("is locked", joined)
