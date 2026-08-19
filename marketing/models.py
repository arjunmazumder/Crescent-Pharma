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
