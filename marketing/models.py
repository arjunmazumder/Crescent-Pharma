from decimal import Decimal
import datetime
import re
from django.db import models, transaction
from django.conf import settings


class PeriodType(models.TextChoices):
    MONTHLY = 'MONTHLY', 'Monthly'
    QUARTERLY = 'QUARTERLY', 'Quarterly (3 Months)'
    HALF_YEARLY = 'HALF_YEARLY', 'Half-Yearly (6 Months)'
    YEARLY = 'YEARLY', 'Yearly / Annual'
    CAMPAIGN = 'CAMPAIGN', 'Special Campaign / Drive'


class TargetType(models.TextChoices):
    AMOUNT_WISE = 'AMOUNT_WISE', 'Amount-Wise Target'
    PRODUCT_WISE = 'PRODUCT_WISE', 'Product-Wise Target'
    HYBRID = 'HYBRID', 'Hybrid (Amount & Product Targets)'


class TargetStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    ACTIVE = 'ACTIVE', 'Active / In-Progress'
    ACHIEVED = 'ACHIEVED', 'Achieved'
    MISSED = 'MISSED', 'Missed'
    CLOSED = 'CLOSED', 'Closed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class SalesTarget(models.Model):
    title = models.CharField(
        max_length=255,
        help_text="Descriptive title (e.g. 'August 2026 Monthly Sales Target')"
    )
    target_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated unique code (e.g. TGT-2026-0001)"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sales_targets',
        help_text="The MPO / Marketing Staff assigned to this target"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_sales_targets',
        help_text="The Manager / Admin who created this target"
    )
    period_type = models.CharField(
        max_length=50,
        choices=PeriodType.choices,
        default=PeriodType.MONTHLY
    )
    start_date = models.DateField(help_text="Campaign / Target start date")
    end_date = models.DateField(help_text="Campaign / Target end date")
    target_type = models.CharField(
        max_length=50,
        choices=TargetType.choices,
        default=TargetType.HYBRID
    )
    total_target_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total overall sales revenue target in BDT"
    )
    status = models.CharField(
        max_length=50,
        choices=TargetStatus.choices,
        default=TargetStatus.ACTIVE
    )
    territory_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Assigned work area / territory"
    )
    notes = models.TextField(
        null=True,
        blank=True,
        help_text="Manager guidelines and campaign focus instructions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_targets'
        ordering = ['-start_date', '-created_at']

    def __str__(self):
        return f"{self.target_code} - {self.title} ({self.assigned_to.username})"

    def save(self, *args, **kwargs):
        if not self.target_code:
            current_year = datetime.date.today().year
            with transaction.atomic():
                last_target = SalesTarget.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_target:
                    for t in SalesTarget.objects.all():
                        if t.target_code:
                            match = re.search(r'TGT-\d{4}-(\d+)', t.target_code)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                new_code = f"TGT-{current_year}-{next_number:04d}"
                while SalesTarget.objects.filter(target_code=new_code).exists():
                    next_number += 1
                    new_code = f"TGT-{current_year}-{next_number:04d}"
                self.target_code = new_code
        super().save(*args, **kwargs)


class ProductTargetItem(models.Model):
    sales_target = models.ForeignKey(
        SalesTarget,
        on_delete=models.CASCADE,
        related_name='product_items'
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='target_items'
    )
    target_quantity = models.IntegerField(default=1, help_text="Target units/boxes to sell")
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Auto-fetched from Product.selling_price as historical price snapshot"
    )
    target_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Auto-calculated: target_quantity * unit_price"
    )

    class Meta:
        db_table = 'product_target_items'
        unique_together = ('sales_target', 'product')
        ordering = ['id']

    def __str__(self):
        return f"{self.sales_target.target_code} -> {self.product.name}: {self.target_quantity} units"

    def save(self, *args, **kwargs):
        if (self.unit_price is None or self.unit_price == 0) and self.product_id:
            from inventory.models import Product
            try:
                prod = self.product if hasattr(self, 'product') else Product.objects.get(id=self.product_id)
                self.unit_price = prod.selling_price
            except Exception:
                self.unit_price = Decimal('0.00')

        unit_p = Decimal(str(self.unit_price or '0.00'))
        self.target_amount = (Decimal(self.target_quantity) * unit_p).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 2. Doctor Directory & Physician Sample Distribution Models
# -----------------------------------------------------------------------------

class VisitingShift(models.TextChoices):
    MORNING = 'MORNING', 'Morning Shift'
    EVENING = 'EVENING', 'Evening Shift'


class Doctor(models.Model):
    doctor_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated unique code (e.g. DOC-0001)"
    )
    name = models.CharField(max_length=255, help_text="Doctor full name with title")
    degrees = models.CharField(max_length=255, null=True, blank=True, help_text="e.g. MBBS, FCPS (Medicine)")
    specialty = models.CharField(max_length=150, help_text="e.g. Cardiology, Medicine, Pediatrics, Dermatology")
    bmdc_reg_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="BM&DC Registration Number for statutory compliance"
    )
    chamber_or_hospital_name = models.CharField(max_length=255, help_text="Clinic, Chamber or Hospital Name")
    address = models.TextField(null=True, blank=True, help_text="Detailed chamber address")
    territory_name = models.CharField(max_length=255, null=True, blank=True, help_text="Assigned sales territory")
    phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    visiting_shift = models.CharField(
        max_length=20,
        choices=VisitingShift.choices,
        default=VisitingShift.EVENING
    )
    assigned_mpo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_doctors',
        help_text="The MPO / Marketing Representative responsible for regular visits"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_doctors'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.specialty}) - {self.chamber_or_hospital_name}"

    def save(self, *args, **kwargs):
        if not self.doctor_code:
            with transaction.atomic():
                last_doc = Doctor.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_doc:
                    for d in Doctor.objects.all():
                        if d.doctor_code:
                            match = re.search(r'DOC-(\d+)', d.doctor_code)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                candidate = f"DOC-{next_number:04d}"
                while Doctor.objects.filter(doctor_code=candidate).exists():
                    next_number += 1
                    candidate = f"DOC-{next_number:04d}"
                self.doctor_code = candidate
        super().save(*args, **kwargs)


class DoctorSampleDistribution(models.Model):
    distribution_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Auto-generated distribution number (e.g. SMP-2026-0001)"
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name='sample_distributions',
        help_text="Doctor / Medical practitioner recipient"
    )
    mpo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='distributed_samples',
        help_text="The Marketing Officer who delivered the samples"
    )
    source_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sample_distributions',
        help_text="Warehouse / Depot from which samples were drawn"
    )
    distribution_date = models.DateField(default=datetime.date.today)
    total_items_count = models.IntegerField(default=0)
    notes = models.TextField(null=True, blank=True, help_text="Physician feedback / visit notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_doctor_sample_distributions'
        ordering = ['-distribution_date', '-id']

    def __str__(self):
        return f"{self.distribution_number} -> Dr. {self.doctor.name} ({self.distribution_date})"

    def save(self, *args, **kwargs):
        if not self.distribution_number:
            year = self.distribution_date.year if self.distribution_date else datetime.date.today().year
            prefix = f"SMP-{year}-"
            with transaction.atomic():
                last_dist = DoctorSampleDistribution.objects.select_for_update().filter(
                    distribution_number__startswith=prefix
                ).order_by('-id').first()
                max_num = 0
                if last_dist:
                    for d in DoctorSampleDistribution.objects.filter(distribution_number__startswith=prefix):
                        match = re.search(r'SMP-\d+-(\d+)', d.distribution_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while DoctorSampleDistribution.objects.filter(distribution_number=candidate).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.distribution_number = candidate
        super().save(*args, **kwargs)


class DoctorSampleItem(models.Model):
    distribution = models.ForeignKey(
        DoctorSampleDistribution,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='distributed_samples',
        help_text="Sample medicine distributed"
    )
    batch_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Batch / Lot number of sample medicine for pharmacovigilance"
    )
    quantity = models.IntegerField(default=1, help_text="Number of sample units given")
    unit = models.CharField(max_length=50, default='Strips')

    class Meta:
        db_table = 'marketing_doctor_sample_items'
        ordering = ['id']

    def __str__(self):
        return f"{self.product.name} ({self.quantity} {self.unit}) [Batch: {self.batch_number or 'N/A'}]"


class MPOClosingSnapshot(models.Model):
    mpo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='monthly_closing_snapshots'
    )
    month = models.IntegerField()
    year = models.IntegerField()
    total_sales_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_collected_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_credit_due = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_invoices_count = models.IntegerField(default=0)
    total_receipts_count = models.IntegerField(default=0)
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_mpo_closings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'marketing_mpo_closing_snapshots'
        unique_together = ('mpo', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Closing {self.mpo.username} - {self.month}/{self.year} (Sales: {self.total_sales_amount})"

