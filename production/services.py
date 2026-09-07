import logging
from decimal import Decimal, ROUND_HALF_UP
import datetime
from django.db import transaction
from django.db.models import Sum, F, Q, Count, Avg
from django.utils import timezone
from django.contrib.auth import get_user_model

from inventory.models import Product, Warehouse, StockLevel, StockMovement
from inventory.services import InventoryService
from accounting.models import AccountHead, AccountType, Voucher, VoucherType, VoucherStatus, JournalEntry
from accounting.services import VoucherPostingService

from .models import (
    BOMHeader, BOMItem, ProductionLine, ProductionPlan,
    ProductionBatch, MaterialIssueSlip, MaterialIssueItem,
    ProductionStageLog, FinishedGoodsTransfer
)

User = get_user_model()

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. BOMService
# -----------------------------------------------------------------------------

class BOMService:
    @staticmethod
    def estimate_materials(bom: BOMHeader, batch_target_quantity: Decimal, source_warehouse: Warehouse = None):
        """
        Calculates theoretical and expected material requirement for a given batch size:
        Required Qty = (Batch Target Qty / BOM Standard Batch Size) * Standard Material Qty * (1 + Wastage% / 100)
        Also evaluates available stock levels in warehouse and calculates estimated cost.
        """
        if not batch_target_quantity or batch_target_quantity <= Decimal('0.000'):
            raise ValueError("Batch target quantity must be greater than zero.")

        if not bom.standard_batch_size or bom.standard_batch_size <= Decimal('0.000'):
            raise ValueError(f"BOM {bom.bom_code} has invalid standard batch size.")

        scaling_factor = batch_target_quantity / bom.standard_batch_size
        items = bom.items.select_related('material').all()

        estimated_materials = []
        total_estimated_cost = Decimal('0.00')
        all_materials_available = True

        for item in items:
            standard_qty = item.standard_quantity * scaling_factor
            wastage_multiplier = Decimal('1.00') + (item.wastage_percentage / Decimal('100.0'))
            required_qty = (standard_qty * wastage_multiplier).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

            # Available stock check
            available_qty = Decimal('0.0000')
            if source_warehouse:
                stock_agg = StockLevel.objects.filter(
                    product=item.material,
                    warehouse=source_warehouse
                ).aggregate(
                    total_qty=Sum('quantity'),
                    total_reserved=Sum('reserved_quantity')
                )
                total_qty = stock_agg['total_qty'] or Decimal('0.0000')
                total_reserved = stock_agg['total_reserved'] or Decimal('0.0000')
                available_qty = max(Decimal('0.0000'), total_qty - total_reserved)

            unit_cost = item.material.purchase_price or Decimal('0.00')
            material_cost = (required_qty * unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_estimated_cost += material_cost

            is_sufficient = available_qty >= required_qty if source_warehouse else True
            if not is_sufficient:
                all_materials_available = False

            estimated_materials.append({
                'material_id': item.material.id,
                'material_name': item.material.name,
                'material_code': item.material.unique_id,
                'material_type': item.material_type,
                'unit': item.unit,
                'standard_quantity': standard_qty.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP),
                'wastage_percentage': item.wastage_percentage,
                'required_quantity': required_qty,
                'available_quantity': available_qty,
                'is_sufficient': is_sufficient,
                'unit_cost': unit_cost,
                'estimated_cost': material_cost,
            })

        return {
            'bom_code': bom.bom_code,
            'mfr_number': bom.mfr_number,
            'finished_product_id': bom.finished_product.id,
            'finished_product_name': bom.finished_product.name,
            'batch_target_quantity': batch_target_quantity,
            'batch_unit': bom.batch_unit,
            'total_items_count': len(estimated_materials),
            'total_estimated_cost': total_estimated_cost,
            'all_materials_available': all_materials_available,
            'items': estimated_materials,
        }

    @staticmethod
    def approve_bom(bom: BOMHeader, user, remarks=None):
        """
        Approves a BOM for production release.
        """
        with transaction.atomic():
            bom.is_approved = True
            bom.approved_by = user
            bom.approved_at = timezone.now()
            if remarks:
                bom.preparation_instructions = (bom.preparation_instructions or '') + f"\n[Approval Note by {user.username}]: {remarks}"
            bom.save()
            return bom

    @staticmethod
    def create_new_version(bom: BOMHeader, new_version_str: str, user=None):
        """
        Clones an existing BOM to create a new revision (e.g. v2.0) with is_approved=False.
        """
        with transaction.atomic():
            new_bom = BOMHeader.objects.create(
                mfr_number=bom.mfr_number,
                finished_product=bom.finished_product,
                version=new_version_str,
                standard_batch_size=bom.standard_batch_size,
                batch_unit=bom.batch_unit,
                is_active=True,
                is_approved=False,
                preparation_instructions=bom.preparation_instructions,
                created_by=user
            )

            items_to_create = []
            for item in bom.items.all():
                items_to_create.append(BOMItem(
                    bom=new_bom,
                    material=item.material,
                    material_type=item.material_type,
                    standard_quantity=item.standard_quantity,
                    unit=item.unit,
                    wastage_percentage=item.wastage_percentage
                ))
            BOMItem.objects.bulk_create(items_to_create)

            return new_bom


# -----------------------------------------------------------------------------
# 2. ProductionBatchService
# -----------------------------------------------------------------------------

class ProductionBatchService:
    @staticmethod
    def schedule_batch(
        bom: BOMHeader,
        planned_quantity: Decimal,
        production_line: ProductionLine,
        source_warehouse: Warehouse,
        destination_warehouse: Warehouse,
        manufacturing_date,
        expiry_date,
        batch_number=None,
        production_plan: ProductionPlan = None,
        assigned_supervisor=None,
        assigned_operators=None,
        notes="",
        user=None
    ):
        """
        Schedules a new pharmaceutical manufacturing batch.
        Validates BOM approval status, line availability, and manufacturing dates.
        """
        if not bom.is_approved:
            raise ValueError(f"Cannot schedule batch: BOM {bom.bom_code} is not approved by QA.")

        if not bom.is_active:
            raise ValueError(f"Cannot schedule batch: BOM {bom.bom_code} is inactive.")

        if planned_quantity <= Decimal('0.000'):
            raise ValueError("Planned quantity must be greater than zero.")

        if expiry_date <= manufacturing_date:
            raise ValueError("Expiry date must be after manufacturing date.")

        if not production_line.is_active:
            raise ValueError(f"Production line '{production_line.line_name}' is currently inactive.")

        with transaction.atomic():
            batch = ProductionBatch.objects.create(
                batch_number=batch_number or "",
                production_plan=production_plan,
                bom=bom,
                finished_product=bom.finished_product,
                production_line=production_line,
                source_warehouse=source_warehouse,
                destination_warehouse=destination_warehouse,
                planned_quantity=planned_quantity,
                actual_produced_quantity=Decimal('0.000'),
                rejected_quantity=Decimal('0.000'),
                manufacturing_date=manufacturing_date,
                expiry_date=expiry_date,
                status=ProductionBatch.BatchStatus.SCHEDULED,
                current_stage=ProductionBatch.StageChoice.PLANNED,
                assigned_supervisor=assigned_supervisor,
                notes=notes,
                created_by=user
            )

            if assigned_operators:
                batch.assigned_operators.set(assigned_operators)

            # Create initial stage log for Planning
            ProductionStageLog.objects.create(
                batch=batch,
                stage=ProductionStageLog.StageName.MIXING,
                started_at=timezone.now(),
                status=ProductionStageLog.StageStatus.RUNNING,
                operator=user,
                machine_equipment_name=production_line.line_name,
                remarks=f"Batch scheduled for {planned_quantity} {bom.batch_unit}."
            )

            return batch

    @staticmethod
    def issue_materials(
        batch: ProductionBatch,
        warehouse: Warehouse,
        items_data: list,
        user=None,
        notes=""
    ):
        """
        Dispenses and issues raw and packaging materials from warehouse to the production floor.
        Deducts physical inventory stock (StockMovement type 'OUT') and creates MaterialIssueSlip & Items.
        Updates batch status to MATERIAL_ISSUED and advances stage to MIXING.
        """
        if batch.status in [ProductionBatch.BatchStatus.COMPLETED, ProductionBatch.BatchStatus.CANCELLED]:
            raise ValueError(f"Cannot issue materials: Batch {batch.batch_number} is already {batch.status}.")

        if not items_data:
            raise ValueError("At least one material line item must be specified for issuance.")

        with transaction.atomic():
            slip = MaterialIssueSlip.objects.create(
                batch=batch,
                warehouse=warehouse,
                issued_date=timezone.now().date(),
                status=MaterialIssueSlip.IssueStatus.ISSUED,
                issued_by=user,
                received_by=batch.assigned_supervisor or user,
                notes=notes or f"Material issued for batch {batch.batch_number}"
            )

            for entry in items_data:
                material_id = entry.get('material_id')
                issued_qty = Decimal(str(entry.get('issued_quantity', '0')))
                batch_number = entry.get('batch_number') or ""
                standard_bom_qty = Decimal(str(entry.get('standard_bom_quantity', '0')))

                if issued_qty <= Decimal('0.0000'):
                    continue

                material = Product.objects.get(id=material_id)

                # Deduct inventory stock
                InventoryService.record_stock_movement(
                    product=material,
                    warehouse=warehouse,
                    batch_number=batch_number,
                    movement_type='OUT',
                    quantity=int(round(issued_qty)),
                    reference_no=slip.issue_number,
                    notes=f"Issued for Production Batch {batch.batch_number}",
                    user=user
                )

                MaterialIssueItem.objects.create(
                    material_issue_slip=slip,
                    material=material,
                    batch_number=batch_number,
                    standard_bom_quantity=standard_bom_qty,
                    issued_quantity=issued_qty,
                    actual_consumed_quantity=issued_qty,  # default consumed to issued until reconciliation
                    wastage_quantity=Decimal('0.0000'),
                    returned_quantity=Decimal('0.0000')
                )

            batch.status = ProductionBatch.BatchStatus.MATERIAL_ISSUED
            if batch.current_stage == ProductionBatch.StageChoice.PLANNED:
                batch.current_stage = ProductionBatch.StageChoice.MIXING
            batch.save()

            return slip

    @staticmethod
    def reconcile_and_return_materials(
        batch: ProductionBatch,
        return_items_data: list,
        user=None,
        notes=""
    ):
        """
        Reconciles actual consumed quantities, wastage, and returns excess unused materials back to store.
        Inflows stock (StockMovement type 'IN') for returned quantities.
        """
        with transaction.atomic():
            for entry in return_items_data:
                item_id = entry.get('item_id')
                consumed_qty = Decimal(str(entry.get('actual_consumed_quantity', '0')))
                wastage_qty = Decimal(str(entry.get('wastage_quantity', '0')))
                returned_qty = Decimal(str(entry.get('returned_quantity', '0')))

                issue_item = MaterialIssueItem.objects.select_for_update().get(id=item_id)
                issue_item.actual_consumed_quantity = consumed_qty
                issue_item.wastage_quantity = wastage_qty
                issue_item.returned_quantity = returned_qty
                issue_item.save()

                if returned_qty > Decimal('0.0000'):
                    # Inflow returned stock back to store
                    InventoryService.record_stock_movement(
                        product=issue_item.material,
                        warehouse=issue_item.material_issue_slip.warehouse,
                        batch_number=issue_item.batch_number or "",
                        movement_type='IN',
                        quantity=int(round(returned_qty)),
                        reference_no=f"RET-{issue_item.material_issue_slip.issue_number}",
                        notes=f"Excess material returned from Batch {batch.batch_number}",
                        user=user
                    )

            # Check if all items reconciled
            slips = batch.material_issue_slips.all()
            for s in slips:
                s.status = MaterialIssueSlip.IssueStatus.RETURNED
                s.save()

            return True

    @staticmethod
    def advance_stage(batch: ProductionBatch, next_stage: str, user=None, notes=None):
        """
        Advances the manufacturing stage of a batch (WIP State Machine).
        PLANNED -> MIXING -> PROCESSING -> FILLING -> PACKAGING -> QC_PENDING -> FINISHED
        """
        valid_stages = [choice[0] for choice in ProductionBatch.StageChoice.choices]
        if next_stage not in valid_stages:
            raise ValueError(f"Invalid stage '{next_stage}'. Valid stages are: {valid_stages}")

        with transaction.atomic():
            # Close previous running stage log if any
            last_log = batch.stage_logs.filter(status=ProductionStageLog.StageStatus.RUNNING).order_by('-started_at').first()
            if last_log:
                last_log.completed_at = timezone.now()
                last_log.status = ProductionStageLog.StageStatus.PASSED
                last_log.save()

            batch.current_stage = next_stage
            if next_stage == ProductionBatch.StageChoice.QC_PENDING:
                batch.status = ProductionBatch.BatchStatus.QC_INSPECTION
            elif next_stage == ProductionBatch.StageChoice.FINISHED:
                batch.status = ProductionBatch.BatchStatus.COMPLETED
            else:
                batch.status = ProductionBatch.BatchStatus.IN_PROGRESS

            batch.save()

            # Start new stage log
            if next_stage != ProductionBatch.StageChoice.FINISHED:
                stage_name_map = {
                    ProductionBatch.StageChoice.MIXING: ProductionStageLog.StageName.MIXING,
                    ProductionBatch.StageChoice.PROCESSING: ProductionStageLog.StageName.PROCESSING,
                    ProductionBatch.StageChoice.FILLING: ProductionStageLog.StageName.FILLING,
                    ProductionBatch.StageChoice.PACKAGING: ProductionStageLog.StageName.PACKAGING,
                    ProductionBatch.StageChoice.QC_PENDING: ProductionStageLog.StageName.QC_INSPECTION,
                }
                mapped_stage = stage_name_map.get(next_stage, ProductionStageLog.StageName.MIXING)
                ProductionStageLog.objects.create(
                    batch=batch,
                    stage=mapped_stage,
                    started_at=timezone.now(),
                    status=ProductionStageLog.StageStatus.RUNNING,
                    operator=user,
                    machine_equipment_name=batch.production_line.line_name,
                    remarks=notes or f"Advanced to {batch.get_current_stage_display()}"
                )

            return batch

    @staticmethod
    def record_stage_qc(
        batch: ProductionBatch,
        stage: str,
        status: str,
        operator=None,
        machine_equipment_name=None,
        temperature_celsius=None,
        humidity_percentage=None,
        qc_parameters_json=None,
        remarks=None,
        completed=False
    ):
        """
        Records an In-Process Quality Control (IPQC) test log or environmental room parameters.
        """
        with transaction.atomic():
            now = timezone.now()
            log = ProductionStageLog.objects.create(
                batch=batch,
                stage=stage,
                started_at=now,
                completed_at=now if completed else None,
                status=status,
                operator=operator,
                machine_equipment_name=machine_equipment_name or batch.production_line.line_name,
                temperature_celsius=temperature_celsius,
                humidity_percentage=humidity_percentage,
                qc_parameters_json=qc_parameters_json or {},
                remarks=remarks
            )
            return log

    @staticmethod
    def complete_and_transfer(
        batch: ProductionBatch,
        actual_produced_quantity: Decimal,
        rejected_quantity: Decimal,
        qc_release_certificate_number: str,
        destination_warehouse: Warehouse = None,
        user=None,
        notes=""
    ):
        """
        Finalizes batch production after QC pass and transfers finished medicine to commercial inventory.
        1. Updates batch actual produced and rejected quantities, status to COMPLETED, stage to FINISHED.
        2. Inflows finished goods stock into destination warehouse with batch number & expiry dates.
        3. Creates FinishedGoodsTransfer (FGT) record.
        4. Auto-posts a double-entry Journal Voucher (JV) to the General Ledger:
           - Debit: 1140 Finished Goods Inventory Stock
           - Credit: 1141 Raw & Packaging Material Stock
           - Credit: 5110 Direct Labor & Factory Overhead (if applicable)
        """
        if batch.status == ProductionBatch.BatchStatus.COMPLETED:
            raise ValueError(f"Batch {batch.batch_number} is already completed.")

        if actual_produced_quantity <= Decimal('0.000'):
            raise ValueError("Actual produced quantity must be greater than zero.")

        dest_warehouse = destination_warehouse or batch.destination_warehouse

        with transaction.atomic():
            # 1. Update Batch
            batch.actual_produced_quantity = actual_produced_quantity
            batch.rejected_quantity = rejected_quantity or Decimal('0.000')
            batch.status = ProductionBatch.BatchStatus.COMPLETED
            batch.current_stage = ProductionBatch.StageChoice.FINISHED
            batch.save()

            # 2. Inflow finished goods stock
            InventoryService.record_stock_movement(
                product=batch.finished_product,
                warehouse=dest_warehouse,
                batch_number=batch.batch_number,
                movement_type='IN',
                quantity=int(round(actual_produced_quantity)),
                mfg_date=batch.manufacturing_date,
                expiry_date=batch.expiry_date,
                reference_no=f"PROD-{batch.batch_number}",
                notes=f"Manufactured via Batch {batch.batch_number} ({batch.yield_percentage}% yield)",
                user=user
            )

            # 3. Create Finished Goods Transfer record
            transfer = FinishedGoodsTransfer.objects.create(
                batch=batch,
                finished_product=batch.finished_product,
                destination_warehouse=dest_warehouse,
                transfer_quantity=actual_produced_quantity,
                transfer_date=timezone.now().date(),
                qc_release_certificate_number=qc_release_certificate_number,
                is_received=True,
                received_by=user,
                received_at=timezone.now(),
                created_by=user,
                notes=notes or f"QC Released batch {batch.batch_number} to {dest_warehouse.name}"
            )

            # 4. Calculate total raw material cost consumed for accounting JV
            total_material_cost = Decimal('0.00')
            for slip in batch.material_issue_slips.all():
                for item in slip.items.all():
                    qty = item.actual_consumed_quantity if item.actual_consumed_quantity > Decimal('0.0000') else item.issued_quantity
                    cost_per_unit = item.material.purchase_price or Decimal('0.00')
                    total_material_cost += (qty * cost_per_unit).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if total_material_cost <= Decimal('0.00'):
                # Fallback: estimate standard cost from BOM or product purchase_price
                unit_cost = batch.finished_product.purchase_price or Decimal('10.00')
                total_material_cost = (actual_produced_quantity * unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # 5. Post Accounting Double-Entry Journal Voucher (JV)
            try:
                head_fg, _ = AccountHead.objects.get_or_create(
                    code='1140',
                    defaults={
                        'name': 'Finished Goods Inventory Stock',
                        'account_type': AccountType.ASSET,
                        'is_group': False,
                        'is_active': True,
                        'currency': 'BDT'
                    }
                )
                head_rm, _ = AccountHead.objects.get_or_create(
                    code='1141',
                    defaults={
                        'name': 'Raw & Packing Materials Inventory',
                        'account_type': AccountType.ASSET,
                        'is_group': False,
                        'is_active': True,
                        'currency': 'BDT'
                    }
                )

                entries = [
                    {
                        'account_id': head_fg.id,
                        'debit_amount': total_material_cost,
                        'credit_amount': Decimal('0.00'),
                        'description': f"Finished goods inventory capitalized for Batch {batch.batch_number}"
                    },
                    {
                        'account_id': head_rm.id,
                        'debit_amount': Decimal('0.00'),
                        'credit_amount': total_material_cost,
                        'description': f"Raw and packaging materials consumption for Batch {batch.batch_number}"
                    }
                ]

                voucher = VoucherPostingService.create_and_post_voucher(
                    voucher_type=VoucherType.JOURNAL,
                    voucher_date=timezone.now().date(),
                    narration=f"Automated Manufacturing Cost Capitalization: Batch {batch.batch_number} -> {batch.finished_product.name} (Yield: {batch.yield_percentage}%)",
                    entries_data=entries,
                    reference_no=transfer.transfer_code,
                    is_auto_generated=True,
                    source_module='PRODUCTION',
                    source_id=transfer.id,
                    user=user,
                    auto_post=True
                )
                transfer.accounting_voucher = voucher
                transfer.save()
            except ValueError:
                logger.exception(
                    "Failed to post manufacturing cost voucher for batch %s (transfer %s). "
                    "Finished goods entered stock but were not capitalized in the General Ledger.",
                    batch.batch_number, transfer.transfer_code
                )

            return transfer


# -----------------------------------------------------------------------------
# 3. ProductionReportService
# -----------------------------------------------------------------------------

class ProductionReportService:
    @staticmethod
    def get_production_dashboard():
        """
        Aggregates plant-wide production statistics, active batches, stage distributions, and line utilization.
        """
        now = timezone.now()
        first_day_of_month = now.date().replace(day=1)

        total_batches = ProductionBatch.objects.count()
        active_batches = ProductionBatch.objects.filter(
            status__in=[
                ProductionBatch.BatchStatus.SCHEDULED,
                ProductionBatch.BatchStatus.MATERIAL_ISSUED,
                ProductionBatch.BatchStatus.IN_PROGRESS,
                ProductionBatch.BatchStatus.QC_INSPECTION
            ]
        ).count()

        completed_this_month = ProductionBatch.objects.filter(
            status=ProductionBatch.BatchStatus.COMPLETED,
            updated_at__gte=first_day_of_month
        )
        completed_count = completed_this_month.count()

        units_produced_this_month = completed_this_month.aggregate(
            total_units=Sum('actual_produced_quantity')
        )['total_units'] or Decimal('0.000')

        # Calculate average yield for completed batches
        all_completed = ProductionBatch.objects.filter(
            status=ProductionBatch.BatchStatus.COMPLETED,
            planned_quantity__gt=0
        )
        avg_yield = Decimal('0.00')
        if all_completed.exists():
            yields = [b.yield_percentage for b in all_completed]
            avg_yield = (sum(yields) / Decimal(str(len(yields)))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Stage breakdown
        stage_counts = ProductionBatch.objects.values('current_stage').annotate(count=Count('id'))
        stages_summary = {s['current_stage']: s['count'] for s in stage_counts}

        # Line utilization
        lines = ProductionLine.objects.all()
        lines_summary = []
        for line in lines:
            running_batches = line.batches.filter(
                status__in=[
                    ProductionBatch.BatchStatus.MATERIAL_ISSUED,
                    ProductionBatch.BatchStatus.IN_PROGRESS,
                    ProductionBatch.BatchStatus.QC_INSPECTION
                ]
            ).count()
            lines_summary.append({
                'line_id': line.id,
                'line_code': line.line_code,
                'line_name': line.line_name,
                'cleanroom_classification': line.cleanroom_classification,
                'daily_capacity': line.daily_capacity,
                'is_active': line.is_active,
                'active_running_batches': running_batches,
                'status': 'BUSY' if running_batches > 0 else ('ACTIVE' if line.is_active else 'OFFLINE')
            })

        # Recent batch list
        recent_batches = ProductionBatch.objects.select_related(
            'finished_product', 'production_line', 'assigned_supervisor'
        ).order_by('-id')[:10]

        recent_list = []
        for b in recent_batches:
            recent_list.append({
                'id': b.id,
                'batch_number': b.batch_number,
                'product_name': b.finished_product.name,
                'line_code': b.production_line.line_code,
                'planned_quantity': b.planned_quantity,
                'actual_produced_quantity': b.actual_produced_quantity,
                'yield_percentage': b.yield_percentage,
                'status': b.status,
                'current_stage': b.current_stage,
                'supervisor_name': b.assigned_supervisor.display_name if b.assigned_supervisor else None,
                'manufacturing_date': b.manufacturing_date,
                'expiry_date': b.expiry_date
            })

        return {
            'overview': {
                'total_batches_count': total_batches,
                'active_batches_count': active_batches,
                'completed_batches_this_month': completed_count,
                'units_produced_this_month': units_produced_this_month,
                'average_yield_percentage': avg_yield,
            },
            'stages_breakdown': stages_summary,
            'production_lines': lines_summary,
            'recent_batches': recent_list
        }

    @staticmethod
    def get_batch_traceability(batch_number: str):
        """
        Compiles complete 360° pharmaceutical genealogy & traceability audit report for a batch:
        - Master batch info & formula recipe (BOM / MFR Number)
        - Production Line, cleanroom grade, supervisor & operators
        - Issued raw and packaging materials with source warehouse & batch numbers
        - In-process IPQC logs (temperatures, humidity, machine names, test parameters)
        - Finished goods warehouse transfer receipt and QC release certificate
        - Current remaining stock in finished goods depot
        """
        batch = ProductionBatch.objects.filter(batch_number=batch_number).select_related(
            'bom', 'finished_product', 'production_line', 'source_warehouse',
            'destination_warehouse', 'assigned_supervisor', 'production_plan'
        ).first()

        if not batch:
            raise ValueError(f"Batch with number '{batch_number}' not found.")

        # 1. Materials Issued
        material_slips = batch.material_issue_slips.prefetch_related('items__material', 'issued_by', 'received_by').all()
        issued_materials_list = []
        for slip in material_slips:
            for item in slip.items.all():
                issued_materials_list.append({
                    'issue_slip_number': slip.issue_number,
                    'issued_date': slip.issued_date,
                    'material_id': item.material.id,
                    'material_name': item.material.name,
                    'material_code': item.material.unique_id,
                    'material_batch_number': item.batch_number or 'N/A',
                    'standard_bom_quantity': item.standard_bom_quantity,
                    'issued_quantity': item.issued_quantity,
                    'actual_consumed_quantity': item.actual_consumed_quantity,
                    'wastage_quantity': item.wastage_quantity,
                    'returned_quantity': item.returned_quantity,
                    'unit': item.material.unit,
                    'issued_by': slip.issued_by.display_name if slip.issued_by else None,
                    'received_by': slip.received_by.display_name if slip.received_by else None,
                })

        # 2. IPQC Stage Logs
        stage_logs = batch.stage_logs.select_related('operator').order_by('started_at')
        logs_list = []
        for log in stage_logs:
            logs_list.append({
                'id': log.id,
                'stage': log.stage,
                'stage_display': log.get_stage_display(),
                'started_at': log.started_at,
                'completed_at': log.completed_at,
                'status': log.status,
                'operator_name': log.operator.display_name if log.operator else None,
                'machine_name': log.machine_equipment_name,
                'temperature_celsius': log.temperature_celsius,
                'humidity_percentage': log.humidity_percentage,
                'qc_parameters': log.qc_parameters_json,
                'remarks': log.remarks
            })

        # 3. Finished Goods Transfers
        transfers = batch.finished_goods_transfers.select_related(
            'destination_warehouse', 'received_by', 'accounting_voucher'
        ).all()
        transfers_list = []
        for t in transfers:
            transfers_list.append({
                'transfer_code': t.transfer_code,
                'transfer_date': t.transfer_date,
                'destination_warehouse': t.destination_warehouse.name,
                'transfer_quantity': t.transfer_quantity,
                'qc_release_certificate_number': t.qc_release_certificate_number,
                'is_received': t.is_received,
                'received_by': t.received_by.display_name if t.received_by else None,
                'received_at': t.received_at,
                'voucher_number': t.accounting_voucher.voucher_number if t.accounting_voucher else None
            })

        # 4. Current Stock in Warehouse
        current_stock = StockLevel.objects.filter(
            product=batch.finished_product,
            batch_number=batch.batch_number
        ).aggregate(
            total_qty=Sum('quantity'),
            total_reserved=Sum('reserved_quantity')
        )
        stock_qty = current_stock['total_qty'] or Decimal('0.000')
        reserved_qty = current_stock['total_reserved'] or Decimal('0.000')

        return {
            'batch_info': {
                'batch_number': batch.batch_number,
                'finished_product_name': batch.finished_product.name,
                'finished_product_code': batch.finished_product.unique_id,
                'dosage_form': getattr(batch.finished_product, 'dosage_form', 'Tablet'),
                'bom_code': batch.bom.bom_code,
                'mfr_number': batch.bom.mfr_number,
                'bom_version': batch.bom.version,
                'production_plan_code': batch.production_plan.plan_code if batch.production_plan else None,
                'production_line_code': batch.production_line.line_code,
                'production_line_name': batch.production_line.line_name,
                'cleanroom_classification': batch.production_line.cleanroom_classification,
                'source_warehouse': batch.source_warehouse.name,
                'destination_warehouse': batch.destination_warehouse.name,
                'planned_quantity': batch.planned_quantity,
                'actual_produced_quantity': batch.actual_produced_quantity,
                'rejected_quantity': batch.rejected_quantity,
                'yield_percentage': batch.yield_percentage,
                'manufacturing_date': batch.manufacturing_date,
                'expiry_date': batch.expiry_date,
                'status': batch.status,
                'current_stage': batch.current_stage,
                'assigned_supervisor': batch.assigned_supervisor.display_name if batch.assigned_supervisor else None,
                'operators': [op.display_name for op in batch.assigned_operators.all()],
                'created_at': batch.created_at
            },
            'inventory_status': {
                'current_warehouse_stock': stock_qty,
                'current_reserved_quantity': reserved_qty,
                'available_for_sales': max(Decimal('0.000'), stock_qty - reserved_qty)
            },
            'issued_materials': issued_materials_list,
            'in_process_qc_logs': logs_list,
            'finished_goods_transfers': transfers_list
        }
