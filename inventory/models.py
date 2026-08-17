import re
from django.db import models, transaction
from django.conf import settings


class Category(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True, null=True, blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subcategories'
    )
    description = models.TextField(null=True, blank=True)
    image_url = models.URLField(max_length=500, null=True, blank=True)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'categories'
        ordering = ['display_order', 'name']

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} -> {self.name}"
        return self.name


class Attribute(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'attributes'
        ordering = ['name']

    def __str__(self):
        return self.name


class AttributeValue(models.Model):
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)
    code = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attribute_values'
        unique_together = ('attribute', 'value')
        ordering = ['attribute', 'value']

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"


class Product(models.Model):
    name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255)
    unique_id = models.CharField(max_length=50, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    description = models.TextField(null=True, blank=True)
    unit = models.CharField(max_length=50, default='Box')
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    min_stock_level = models.IntegerField(default=10)
    max_stock_level = models.IntegerField(null=True, blank=True)
    drug_registration_number = models.CharField(max_length=100, null=True, blank=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    requires_prescription = models.BooleanField(default=False)
    storage_condition = models.CharField(max_length=255, null=True, blank=True)
    image_url = models.URLField(max_length=500, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        ordering = ['-id']

    def __str__(self):
        return f"{self.name} ({self.unique_id})"

    def save(self, *args, **kwargs):
        if not self.unique_id:
            with transaction.atomic():
                last_product = Product.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_product:
                    for p in Product.objects.all():
                        if p.unique_id:
                            match = re.search(r'PRD-(\d+)', p.unique_id)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                new_id = f"PRD-{next_number:04d}"
                while Product.objects.filter(unique_id=new_id).exists():
                    next_number += 1
                    new_id = f"PRD-{next_number:04d}"
                self.unique_id = new_id
        super().save(*args, **kwargs)


class ProductAttributeValue(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_attributes')
    attribute_value = models.ForeignKey(AttributeValue, on_delete=models.CASCADE, related_name='product_attributes')

    class Meta:
        db_table = 'product_attribute_values'
        unique_together = ('product', 'attribute_value')

    def __str__(self):
        return f"{self.product.name} -> {self.attribute_value}"


class Warehouse(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField(null=True, blank=True)
    contact_number = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'warehouses'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class StockLevel(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_levels')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_levels')
    batch_number = models.CharField(max_length=100)
    mfg_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.IntegerField(default=0)
    reserved_quantity = models.IntegerField(default=0)
    rack_location = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stock_levels'
        unique_together = ('product', 'warehouse', 'batch_number')
        ordering = ['expiry_date', 'batch_number']

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.name} [Batch: {self.batch_number}] -> Qty: {self.quantity}"

    @property
    def available_quantity(self):
        return max(0, self.quantity - self.reserved_quantity)


class StockMovement(models.Model):
    MOVEMENT_TYPE_CHOICES = {
        'IN': 'Inflow (Purchase / Production)',
        'OUT': 'Outflow (Sales / Transfer)',
        'ADJUSTMENT': 'Stock Adjustment',
        'RETURN': 'Customer / Vendor Return',
        'DAMAGE': 'Damaged / Expired Write-off',
    }

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_movements')
    batch_number = models.CharField(max_length=100)
    movement_type = models.CharField(
        max_length=50,
        choices=[(value, value) for value in MOVEMENT_TYPE_CHOICES.values()],
        default=MOVEMENT_TYPE_CHOICES['IN']
    )
    quantity = models.IntegerField()
    previous_stock = models.IntegerField(default=0)
    new_stock = models.IntegerField(default=0)
    reference_no = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stock_movements'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.movement_type}: {self.product.name} ({self.quantity}) @ {self.warehouse.name}"
