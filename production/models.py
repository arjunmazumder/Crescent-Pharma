import re
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone


# -----------------------------------------------------------------------------
# 1. BOMHeader & BOMItem Models
# -----------------------------------------------------------------------------

class BOMHeader(models.Model):
    bom_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated unique code (e.g. BOM-2026-0001)"
    )
    mfr_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Master Formula Record Number for DGDA inspection (e.g. MFR-TAB-PAR-001)"
    )
    finished_product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='boms',
        help_text="Commercial pharmaceutical finished product"
    )
    version = models.CharField(
        max_length=20,
        default='v1.0',
        help_text="Recipe version (e.g. v1.0, v1.1, v2.0)"
    )
    standard_batch_size = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Standard batch size (e.g. 100000.000 Tablets or 5000.000 Bottles)"
    )
    batch_unit = models.CharField(
        max_length=50,
        default='Tablets',
        help_text="Unit of measurement (e.g. Tablets, Bottles, Capsules, Vials, Pcs)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this formula is currently active in factory"
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="Designates whether this formula is QA approved for production"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_boms',
        help_text="QA Head or Plant Manager who approved this formula"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    preparation_instructions = models.TextField(
        null=True,
        blank=True,
        help_text="Standard Operating Procedure (SOP) and manufacturing instructions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_boms'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_bom_headers'
        ordering = ['-id']
        verbose_name = "Bill of Materials (BOM) Header"
        verbose_name_plural = "Bill of Materials (BOM) Headers"

    def __str__(self):
        return f"{self.bom_code or 'Draft'} - {self.finished_product.name} ({self.version})"

    def save(self, *args, **kwargs):
        if not self.bom_code:
            current_year = timezone.now().year
            prefix = f"BOM-{current_year}-"
            with transaction.atomic():
                last_bom = BOMHeader.objects.select_for_update().filter(bom_code__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_bom:
                    for b in BOMHeader.objects.filter(bom_code__startswith=prefix):
                        match = re.search(r'BOM-\d{4}-(\d+)', b.bom_code)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while BOMHeader.objects.filter(bom_code=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.bom_code = candidate
        super().save(*args, **kwargs)


class BOMItem(models.Model):
    class MaterialType(models.TextChoices):
        RAW_MATERIAL = 'RAW_MATERIAL', 'Raw Material (Active / Excipient)'
        PACKING_MATERIAL = 'PACKING_MATERIAL', 'Packaging Material (Primary / Secondary)'

    bom = models.ForeignKey(
        BOMHeader,
        on_delete=models.CASCADE,
        related_name='items',
        help_text="Linked BOM Header master recipe"
    )
    material = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='bom_usages',
        help_text="Raw drug API, excipient chemical, or packaging component"
    )
    material_type = models.CharField(
        max_length=50,
        choices=MaterialType.choices,
        default=MaterialType.RAW_MATERIAL
    )
    standard_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text="Required standard material quantity for the standard batch size"
    )
    unit = models.CharField(
        max_length=50,
        default='kg',
        help_text="Unit of measurement (e.g. kg, gm, liter, ml, pcs, meter)"
    )
    wastage_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Expected process scrap/loss percentage (e.g. 1.50%)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_bom_items'
        ordering = ['id']
        verbose_name = "BOM Item"
        verbose_name_plural = "BOM Items"

    def __str__(self):
        return f"{self.bom.bom_code} -> {self.material.name} ({self.standard_quantity} {self.unit})"


# -----------------------------------------------------------------------------
# 2. ProductionLine & ProductionPlan Models
# -----------------------------------------------------------------------------

class ProductionLine(models.Model):
    line_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Unique line identifier (Auto-generated as LINE-0001 if left blank, or custom code e.g. LINE-TAB-01)"
    )
    line_name = models.CharField(
        max_length=255,
        help_text="Descriptive name (e.g. High-Speed Rotary Tablet Press Line 1)"
    )
    daily_capacity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Standard 24-hour maximum production capacity"
    )
    cleanroom_classification = models.CharField(
        max_length=50,
        default='Grade D',
        help_text="WHO-GMP Cleanroom Air Quality Grade (e.g. Grade A, Grade B, Grade C, Grade D, CNC)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether line is operational and available for batch allocation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_lines'
        ordering = ['line_code']
        verbose_name = "Production Line"
        verbose_name_plural = "Production Lines"

    def __str__(self):
        return f"{self.line_code} - {self.line_name} [{self.cleanroom_classification}]"

    def save(self, *args, **kwargs):
        if not self.line_code or not str(self.line_code).strip():
            with transaction.atomic():
                last_line = ProductionLine.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_line:
                    for line in ProductionLine.objects.all():
                        if line.line_code:
                            match = re.search(r'LINE-(\d+)', line.line_code)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                candidate_code = f"LINE-{next_number:04d}"
                while ProductionLine.objects.filter(line_code=candidate_code).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate_code = f"LINE-{next_number:04d}"
                self.line_code = candidate_code
        super().save(*args, **kwargs)


class ProductionPlan(models.Model):
    class PlanType(models.TextChoices):
        DAILY = 'DAILY', 'Daily Production Plan'
        WEEKLY = 'WEEKLY', 'Weekly Production Plan'
        MONTHLY = 'MONTHLY', 'Monthly Master Schedule'
        CAMPAIGN = 'CAMPAIGN', 'Special Drive / Campaign Schedule'

    class PlanStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft Planning'
        APPROVED = 'APPROVED', 'Approved by Plant Management'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        COMPLETED = 'COMPLETED', 'Fully Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    plan_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated plan code (e.g. PLAN-2026-0001)"
    )
    title = models.CharField(
        max_length=255,
        help_text="Descriptive plan title (e.g. September 2026 Monthly Essential Drugs Production Plan)"
    )
    plan_type = models.CharField(
        max_length=50,
        choices=PlanType.choices,
        default=PlanType.MONTHLY
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=PlanStatus.choices,
        default=PlanStatus.DRAFT
    )
    total_target_batches = models.IntegerField(
        default=1,
        help_text="Total number of target batches scheduled in this plan"
    )
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_production_plans'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_production_plans'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_plans'
        ordering = ['-start_date', '-id']
        verbose_name = "Production Plan"
        verbose_name_plural = "Production Plans"

    def __str__(self):
        return f"{self.plan_code} - {self.title} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.plan_code:
            current_year = timezone.now().year
            prefix = f"PLAN-{current_year}-"
            with transaction.atomic():
                last_plan = ProductionPlan.objects.select_for_update().filter(plan_code__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_plan:
                    for p in ProductionPlan.objects.filter(plan_code__startswith=prefix):
                        match = re.search(r'PLAN-\d{4}-(\d+)', p.plan_code)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while ProductionPlan.objects.filter(plan_code=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.plan_code = candidate
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 3. ProductionBatch Model (Manufacturing Batch Lifecycle & BMR)
# -----------------------------------------------------------------------------

class ProductionBatch(models.Model):
    class BatchStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled / Pending Material'
        MATERIAL_ISSUED = 'MATERIAL_ISSUED', 'Materials Issued & Deducted'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress (WIP)'
        QC_INSPECTION = 'QC_INSPECTION', 'Quality Inspection Pending'
        COMPLETED = 'COMPLETED', 'Completed & Stock Inflow Incurred'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class StageChoice(models.TextChoices):
        PLANNED = 'PLANNED', 'Planned'
        MIXING = 'MIXING', 'Mixing & Blending'
        PROCESSING = 'PROCESSING', 'Granulation / Processing / Drying'
        FILLING = 'FILLING', 'Compression / Liquid Bottling / Capsule Filling'
        PACKAGING = 'PACKAGING', 'Blistering & Final Packaging'
        QC_PENDING = 'QC_PENDING', 'QC Inspection & Testing'
        FINISHED = 'FINISHED', 'Finished & Transferred to Warehouse'

    batch_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Unique pharmaceutical batch number printed on commercial package (e.g. BATCH-2026-0101)"
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches',
        help_text="Master production schedule reference"
    )
    bom = models.ForeignKey(
        BOMHeader,
        on_delete=models.PROTECT,
        related_name='batches',
        help_text="Approved Master Formula Record (BOM) used for this batch"
    )
    finished_product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='production_batches',
        help_text="Commercial pharmaceutical medicine to be produced"
    )
    production_line = models.ForeignKey(
        ProductionLine,
        on_delete=models.PROTECT,
        related_name='batches',
        help_text="Physical manufacturing line and cleanroom suite"
    )
    source_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='source_batches',
        help_text="Raw material and packaging store from which ingredients are issued"
    )
    destination_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='destination_batches',
        help_text="Finished goods depot where approved medicine will be transferred"
    )
    planned_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Planned target production quantity (e.g. 100000.000 Tablets)"
    )
    actual_produced_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Actual QC-passed produced quantity transferred to finished warehouse"
    )
    rejected_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Quantity scrapped or rejected during manufacturing & QC testing"
    )
    manufacturing_date = models.DateField(
        help_text="Batch manufacturing date (Mfg Date)"
    )
    expiry_date = models.DateField(
        help_text="Batch expiration date (Exp Date)"
    )
    status = models.CharField(
        max_length=50,
        choices=BatchStatus.choices,
        default=BatchStatus.SCHEDULED
    )
    current_stage = models.CharField(
        max_length=50,
        choices=StageChoice.choices,
        default=StageChoice.PLANNED
    )
    assigned_supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supervised_batches',
        help_text="Quality Pharmacist / Shift In-Charge supervising manufacturing"
    )
    assigned_operators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='operated_batches',
        help_text="Machine technicians and operators assigned to this batch"
    )
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_batches'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_batches'
        ordering = ['-manufacturing_date', '-id']
        verbose_name = "Production Batch"
        verbose_name_plural = "Production Batches"

    def __str__(self):
        return f"{self.batch_number} - {self.finished_product.name} ({self.status})"

    @property
    def yield_percentage(self):
        if self.planned_quantity and self.planned_quantity > Decimal('0.000'):
            return ((self.actual_produced_quantity / self.planned_quantity) * Decimal('100.0')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        return Decimal('0.00')

    def save(self, *args, **kwargs):
        if not self.batch_number or not str(self.batch_number).strip():
            current_year = self.manufacturing_date.year if self.manufacturing_date else timezone.now().year
            prefix = f"BATCH-{current_year}-"
            with transaction.atomic():
                last_batch = ProductionBatch.objects.select_for_update().filter(batch_number__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_batch:
                    for b in ProductionBatch.objects.filter(batch_number__startswith=prefix):
                        match = re.search(r'BATCH-\d{4}-(\d+)', b.batch_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while ProductionBatch.objects.filter(batch_number=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.batch_number = candidate
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 4. MaterialIssueSlip & MaterialIssueItem Models
# -----------------------------------------------------------------------------

class MaterialIssueSlip(models.Model):
    class IssueStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft Requisition'
        ISSUED = 'ISSUED', 'Materials Issued & Deducted from Stock'
        RETURNED = 'RETURNED', 'Reconciled & Excess Materials Returned'

    issue_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated store delivery voucher (e.g. MIS-2026-0001)"
    )
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.CASCADE,
        related_name='material_issue_slips',
        help_text="Target production batch"
    )
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='issued_material_slips',
        help_text="Source raw and packaging store"
    )
    issued_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=50,
        choices=IssueStatus.choices,
        default=IssueStatus.ISSUED
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_material_slips',
        help_text="Storekeeper who dispensed and issued the material"
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_material_slips',
        help_text="Production pharmacist who received the ingredients"
    )
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_material_issue_slips'
        ordering = ['-issued_date', '-id']
        verbose_name = "Material Issue Slip (MIS)"
        verbose_name_plural = "Material Issue Slips (MIS)"

    def __str__(self):
        return f"{self.issue_number} - Batch: {self.batch.batch_number} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.issue_number:
            current_year = self.issued_date.year if self.issued_date else timezone.now().year
            prefix = f"MIS-{current_year}-"
            with transaction.atomic():
                last_slip = MaterialIssueSlip.objects.select_for_update().filter(issue_number__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_slip:
                    for s in MaterialIssueSlip.objects.filter(issue_number__startswith=prefix):
                        match = re.search(r'MIS-\d{4}-(\d+)', s.issue_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while MaterialIssueSlip.objects.filter(issue_number=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.issue_number = candidate
        super().save(*args, **kwargs)


class MaterialIssueItem(models.Model):
    material_issue_slip = models.ForeignKey(
        MaterialIssueSlip,
        on_delete=models.CASCADE,
        related_name='items'
    )
    material = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='issued_items'
    )
    batch_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Source batch number of the raw material dispensed from store"
    )
    standard_bom_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Theoretical required quantity based on BOM formula scaling"
    )
    issued_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text="Actual quantity weighed and dispensed by storekeeper"
    )
    actual_consumed_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Actual quantity consumed in manufacturing"
    )
    wastage_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Process loss / scrap during manufacturing"
    )
    returned_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Excess unused material returned back to store"
    )

    class Meta:
        db_table = 'production_material_issue_items'
        ordering = ['id']
        verbose_name = "Material Issue Item"
        verbose_name_plural = "Material Issue Items"

    def __str__(self):
        return f"{self.material.name} (Issued: {self.issued_quantity} {self.material.unit}) - Slip: {self.material_issue_slip.issue_number}"


# -----------------------------------------------------------------------------
# 5. ProductionStageLog Model (In-Process Quality Control - IPQC)
# -----------------------------------------------------------------------------

class ProductionStageLog(models.Model):
    class StageName(models.TextChoices):
        MIXING = 'MIXING', 'Mixing & Blending'
        PROCESSING = 'PROCESSING', 'Granulation / Processing / Drying'
        FILLING = 'FILLING', 'Compression / Liquid Bottling / Capsule Filling'
        PACKAGING = 'PACKAGING', 'Blistering & Final Packaging'
        QC_INSPECTION = 'QC_INSPECTION', 'QC Inspection & Testing'

    class StageStatus(models.TextChoices):
        RUNNING = 'RUNNING', 'Running / In-Progress'
        PASSED = 'PASSED', 'Passed & Validated'
        FAILED = 'FAILED', 'Failed / Out of Specification (OOS)'

    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.CASCADE,
        related_name='stage_logs'
    )
    stage = models.CharField(
        max_length=50,
        choices=StageName.choices
    )
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=StageStatus.choices,
        default=StageStatus.RUNNING
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logged_production_stages',
        help_text="Technician/Chemist who operated the machine or tested the stage"
    )
    machine_equipment_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Machine/Equipment name (e.g. Rotary Tablet Press RTP-02, High Shear Mixer HSM-01)"
    )
    temperature_celsius = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Room temperature in Celsius (e.g. 21.50 °C)"
    )
    humidity_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Room relative humidity percentage (e.g. 42.00 %)"
    )
    qc_parameters_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic IPQC test results (e.g. pH, hardness, disintegration, friability, viscosity, clarity)"
    )
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_stage_logs'
        ordering = ['started_at', 'id']
        verbose_name = "Production Stage & IPQC Log"
        verbose_name_plural = "Production Stage & IPQC Logs"

    def __str__(self):
        return f"{self.batch.batch_number} -> {self.get_stage_display()} [{self.status}]"


# -----------------------------------------------------------------------------
# 6. FinishedGoodsTransfer Model (FGT & Accounting Link)
# -----------------------------------------------------------------------------

class FinishedGoodsTransfer(models.Model):
    transfer_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated finished goods transfer delivery code (e.g. FGT-2026-0001)"
    )
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.CASCADE,
        related_name='finished_goods_transfers'
    )
    finished_product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='transferred_finished_goods'
    )
    destination_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='received_finished_transfers',
        help_text="Commercial finished goods central depot"
    )
    transfer_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Actual quantity of finished medicine transferred to commercial stock"
    )
    transfer_date = models.DateField(default=timezone.now)
    qc_release_certificate_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Official QC / QA Laboratory Release Certificate Number (e.g. COA-REL-2026-0089)"
    )
    is_received = models.BooleanField(
        default=False,
        help_text="Flag indicating finished warehouse manager has received and stocked the goods"
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_finished_goods',
        help_text="Finished goods warehouse in-charge"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_finished_transfers'
    )
    accounting_voucher = models.ForeignKey(
        'accounting.Voucher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_transfer_vouchers',
        help_text="Double-entry Journal Voucher (JV) posted to General Ledger"
    )
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_finished_goods_transfers'
        ordering = ['-transfer_date', '-id']
        verbose_name = "Finished Goods Transfer (FGT)"
        verbose_name_plural = "Finished Goods Transfers (FGT)"

    def __str__(self):
        return f"{self.transfer_code} - {self.finished_product.name} ({self.transfer_quantity} {self.finished_product.unit})"

    def save(self, *args, **kwargs):
        if not self.transfer_code:
            current_year = self.transfer_date.year if self.transfer_date else timezone.now().year
            prefix = f"FGT-{current_year}-"
            with transaction.atomic():
                last_fgt = FinishedGoodsTransfer.objects.select_for_update().filter(transfer_code__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_fgt:
                    for f in FinishedGoodsTransfer.objects.filter(transfer_code__startswith=prefix):
                        match = re.search(r'FGT-\d{4}-(\d+)', f.transfer_code)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while FinishedGoodsTransfer.objects.filter(transfer_code=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.transfer_code = candidate
        super().save(*args, **kwargs)
