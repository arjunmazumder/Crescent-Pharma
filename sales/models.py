import re
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone


class CustomerType(models.TextChoices):
    RETAIL = 'RETAIL', 'Retail Pharmacy'
    WHOLESALE = 'WHOLESALE', 'Wholesale Distributor'
    HOSPITAL = 'HOSPITAL', 'Hospital / Clinic'
    PRACTITIONER = 'PRACTITIONER', 'Doctor / Practitioner'
    INSTITUTION = 'INSTITUTION', 'Institution / NGO'


class Customer(models.Model):
    customer_code = models.CharField(max_length=50, unique=True, blank=True)
    name = models.CharField(
        max_length=255,
        help_text="Name of the pharmacy, hospital, clinic, or client business"
    )
    proprietor_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Name of the owner, proprietor, doctor, or primary contact person"
    )
    phone = models.CharField(max_length=30, db_index=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    drug_license_no = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    drug_license_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expiry date of the DGDA drug license"
    )
    trade_license_no = models.CharField(max_length=100, null=True, blank=True)
    customer_type = models.CharField(
        max_length=50,
        choices=CustomerType.choices,
        default=CustomerType.RETAIL
    )
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customers'
        ordering = ['-id']

    def __str__(self):
        return f"{self.name} ({self.customer_code or 'No Code'})"

    def save(self, *args, **kwargs):
        if not self.customer_code:
            with transaction.atomic():
                last_customer = Customer.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_customer:
                    for c in Customer.objects.all():
                        if c.customer_code:
                            match = re.search(r'CUST-(\d+)', c.customer_code)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                candidate_code = f"CUST-{next_number:04d}"
                while Customer.objects.filter(customer_code=candidate_code).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate_code = f"CUST-{next_number:04d}"
                self.customer_code = candidate_code
        super().save(*args, **kwargs)


class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    PENDING = 'PENDING', 'Pending'
    CONFIRMED = 'CONFIRMED', 'Confirmed'
    PROCESSING = 'PROCESSING', 'Processing'
    SHIPPED = 'SHIPPED', 'Shipped'
    DELIVERED = 'DELIVERED', 'Delivered'
    CANCELLED = 'CANCELLED', 'Cancelled'


class PaymentStatus(models.TextChoices):
    UNPAID = 'UNPAID', 'Unpaid'
    PARTIAL = 'PARTIAL', 'Partially Paid'
    PAID = 'PAID', 'Paid'


class PaymentMethod(models.TextChoices):
    CASH = 'CASH', 'Cash'
    CHEQUE = 'CHEQUE', 'Cheque'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    MFS = 'MFS', 'bKash / Nagad / Rocket'
    CREDIT = 'CREDIT', 'Credit (Due)'


class CustomerOrder(models.Model):
    order_number = models.CharField(max_length=50, unique=True, blank=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='orders'
    )
    order_date = models.DateField(default=timezone.now)
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING
    )
    payment_status = models.CharField(
        max_length=50,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID
    )
    payment_method = models.CharField(
        max_length=50,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Overall order discount percentage, e.g. 5.00%"
    )
    discount_flat = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="Flat cash discount amount in BDT"
    )
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    shipping_address = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    cancellation_reason = models.TextField(
        null=True,
        blank=True,
        help_text="Reason for cancelling or rejecting the order"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_orders'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_orders'
        ordering = ['-id']

    def __str__(self):
        return f"{self.order_number or 'Draft'} - {self.customer.name} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.order_number:
            year = timezone.now().year
            with transaction.atomic():
                prefix = f"ORD-{year}-"
                last_order = CustomerOrder.objects.select_for_update().filter(order_number__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_order:
                    for o in CustomerOrder.objects.filter(order_number__startswith=prefix):
                        match = re.search(r'ORD-\d+-(\d+)', o.order_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate_num = f"{prefix}{next_number:04d}"
                while CustomerOrder.objects.filter(order_number=candidate_num).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate_num = f"{prefix}{next_number:04d}"
                self.order_number = candidate_num
        super().save(*args, **kwargs)


class CustomerOrderItem(models.Model):
    order = models.ForeignKey(
        CustomerOrder,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='order_items'
    )
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='order_items'
    )
    batch_number = models.CharField(max_length=100, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'customer_order_items'
        ordering = ['id']

    def __str__(self):
        return f"{self.product.name} x {self.quantity} ({self.order.order_number})"
