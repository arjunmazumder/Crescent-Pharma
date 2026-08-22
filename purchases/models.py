import re
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone


# -----------------------------------------------------------------------------
# 1. Supplier Model & Enums
# -----------------------------------------------------------------------------

class SupplierType(models.TextChoices):
    LOCAL = 'LOCAL', 'Local Supplier'
    OVERSEAS = 'OVERSEAS', 'Overseas / International'


class SupplyCategory(models.TextChoices):
    API = 'API', 'Active Pharmaceutical Ingredient (API)'
    EXCIPIENT = 'EXCIPIENT', 'Excipients & Raw Chemicals'
    PACKAGING_PRIMARY = 'PACKAGING_PRIMARY', 'Primary Packaging (Foil, Ampoules, Vials)'
    PACKAGING_SECONDARY = 'PACKAGING_SECONDARY', 'Secondary Packaging (Cartons, Leaflets)'
    LAB_REAGENTS = 'LAB_REAGENTS', 'Lab Reagents & Chemicals'
    MACHINERY_SPARES = 'MACHINERY_SPARES', 'Machinery & Spare Parts'
    GENERAL = 'GENERAL', 'General Supplies & Services'


class AuditStatus(models.TextChoices):
    APPROVED = 'APPROVED', 'Approved / Qualified'
    PROVISIONAL = 'PROVISIONAL', 'Provisional / Trial'
    PENDING = 'PENDING', 'Audit Pending'
    BLACKLISTED = 'BLACKLISTED', 'Blacklisted / Blocked'


class IncotermsChoice(models.TextChoices):
    FOB = 'FOB', 'Free on Board (FOB)'
    CIF = 'CIF', 'Cost, Insurance & Freight (CIF)'
    CFR = 'CFR', 'Cost & Freight (CFR)'
    EXW = 'EXW', 'Ex Works (EXW)'
    CIP = 'CIP', 'Carriage and Insurance Paid to (CIP)'
    DAP = 'DAP', 'Delivered at Place (DAP)'
    DDP = 'DDP', 'Delivered Duty Paid (DDP)'


class Supplier(models.Model):
    # 1. Primary Identification
    supplier_code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Supplier Code",
        help_text="Unique auto-generated identifier (e.g. SUP-0001)"
    )
    company_name = models.CharField(
        max_length=255,
        verbose_name="Company / Supplier Name"
    )
    supplier_type = models.CharField(
        max_length=20,
        choices=SupplierType.choices,
        default=SupplierType.LOCAL,
        verbose_name="Supplier Type"
    )
    supply_category = models.CharField(
        max_length=50,
        choices=SupplyCategory.choices,
        default=SupplyCategory.API,
        verbose_name="Material Supply Category"
    )
    country = models.CharField(
        max_length=100,
        default='Bangladesh',
        verbose_name="Country of Origin"
    )
    currency = models.CharField(
        max_length=10,
        default='BDT',
        verbose_name="Transaction Currency"
    )

    # 2. Primary & Alternative Contact Information
    contact_person_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Contact Person Name"
    )
    contact_person_designation = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Contact Person Designation"
    )
    phone_number = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="Phone Number"
    )
    alternative_phone_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Alternative Phone Number"
    )
    email_address = models.EmailField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Email Address"
    )
    website_url = models.URLField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Website URL"
    )

    # 3. Addresses
    office_address = models.TextField(
        verbose_name="Office / Billing Address"
    )
    factory_or_dispatch_address = models.TextField(
        null=True,
        blank=True,
        verbose_name="Factory / Dispatch Location Address"
    )
    city = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="City"
    )
    postal_code = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Postal Code"
    )

    # 4. Pharma Regulatory & DGDA Compliance
    drug_license_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="DGDA Drug License Number"
    )
    drug_license_expiry_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Drug License Expiry Date"
    )
    trade_license_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Trade License Number"
    )
    gmp_certified = models.BooleanField(
        default=False,
        verbose_name="WHO / EU GMP Certified"
    )
    audit_status = models.CharField(
        max_length=20,
        choices=AuditStatus.choices,
        default=AuditStatus.APPROVED,
        verbose_name="Quality Audit Status"
    )
    quality_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal('5.00'),
        verbose_name="Vendor Quality Rating (Out of 5.00)"
    )

    # 5. Tax, VAT & Legal Identifiers (Bangladesh NBR Compliance)
    tax_identification_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Tax Identification Number (TIN / e-TIN)"
    )
    business_identification_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Business Identification Number (13-digit BIN / VAT)"
    )
    tax_deducted_at_source_applicable = models.BooleanField(
        default=True,
        verbose_name="TDS Applicable (উৎসে আয়কর কর্তন)"
    )
    vat_deducted_at_source_applicable = models.BooleanField(
        default=True,
        verbose_name="VDS Applicable (উৎসে মূসক কর্তন)"
    )

    # 6. Financial, Commercial & Credit Terms
    payment_terms = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Payment Terms",
        help_text="e.g. 100% LC at sight / 30 Days Credit"
    )
    credit_period_in_days = models.PositiveIntegerField(
        default=0,
        verbose_name="Credit Period in Days"
    )
    credit_limit_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Maximum Credit Limit Amount"
    )
    opening_balance_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Opening Balance Amount"
    )

    # 7. Banking & International Trade (For LC & Foreign Remittance)
    bank_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Bank Name"
    )
    bank_branch_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Bank Branch Name"
    )
    bank_account_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Bank Account Name / Beneficiary Name"
    )
    bank_account_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Bank Account Number"
    )
    bank_swift_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Bank SWIFT / BIC Code"
    )
    bank_routing_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Bank Routing Number"
    )
    international_bank_account_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="IBAN"
    )
    incoterm = models.CharField(
        max_length=20,
        choices=IncotermsChoice.choices,
        null=True,
        blank=True,
        verbose_name="Incoterms (FOB, CIF, CFR)"
    )
    port_of_loading = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Port of Loading / Origin Port"
    )
    lead_time_in_days = models.PositiveIntegerField(
        default=7,
        verbose_name="Average Lead Time in Days"
    )

    # 8. Status & System Metadata
    is_active = models.BooleanField(
        default=True,
        verbose_name="Is Active Status"
    )
    special_notes = models.TextField(
        null=True,
        blank=True,
        verbose_name="Special Instructions & Remarks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_suppliers'
        ordering = ['-id']
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"

    def __str__(self):
        return f"{self.company_name} ({self.supplier_code or 'No Code'})"

    def save(self, *args, **kwargs):
        if not self.supplier_code:
            with transaction.atomic():
                last_supplier = Supplier.objects.select_for_update().order_by('-id').first()
                max_num = 0
                if last_supplier:
                    for s in Supplier.objects.all():
                        if s.supplier_code:
                            match = re.search(r'SUP-(\d+)', s.supplier_code)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                next_number = max_num + 1
                candidate = f"SUP-{next_number:04d}"
                while Supplier.objects.filter(supplier_code=candidate).exists():
                    next_number += 1
                    candidate = f"SUP-{next_number:04d}"
                self.supplier_code = candidate
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 2. Purchase Order & Line Items Models
# -----------------------------------------------------------------------------

class OrderType(models.TextChoices):
    RAW_MATERIAL = 'RAW_MATERIAL', 'Raw Material (API/Excipients)'
    PACKAGING_MATERIAL = 'PACKAGING_MATERIAL', 'Packaging Material'
    LAB_REAGENTS = 'LAB_REAGENTS', 'Lab Reagents & Chemicals'
    CAPEX_MACHINERY = 'CAPEX_MACHINERY', 'Machinery & Equipment'
    GENERAL = 'GENERAL', 'General & Consumables'


class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    ISSUED = 'ISSUED', 'Issued to Vendor'
    PARTIALLY_RECEIVED = 'PARTIALLY_RECEIVED', 'Partially Received'
    COMPLETED = 'COMPLETED', 'Fully Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class PurchaseOrder(models.Model):
    purchase_order_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Purchase Order Number"
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        verbose_name="Supplier / Vendor"
    )
    order_date = models.DateField(
        verbose_name="Order Date"
    )
    expected_delivery_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Expected Delivery Date"
    )
    delivery_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='destination_purchase_orders',
        verbose_name="Destination Warehouse"
    )
    order_type = models.CharField(
        max_length=30,
        choices=OrderType.choices,
        default=OrderType.RAW_MATERIAL,
        verbose_name="Order Type / Category"
    )
    status = models.CharField(
        max_length=30,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
        verbose_name="Order Status"
    )

    # Currency & Exchange Rate
    currency = models.CharField(
        max_length=10,
        default='BDT',
        verbose_name="Transaction Currency"
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('1.0000'),
        verbose_name="Exchange Rate to BDT"
    )

    # Financial Totals
    total_amount_in_foreign_currency = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Foreign Amount"
    )
    total_amount_in_bdt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Amount in BDT"
    )
    payment_terms = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Payment Terms"
    )

    # Proforma Invoice & DGDA Compliance
    proforma_invoice_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Proforma Invoice Number"
    )
    proforma_invoice_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Proforma Invoice Date"
    )
    dgda_blocklist_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="DGDA Import Permission / Blocklist Number"
    )
    incoterm = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Incoterms (FOB/CIF/CFR)"
    )

    # Remarks & Audit Trail
    special_notes = models.TextField(
        null=True,
        blank=True,
        verbose_name="Special Instructions & Notes"
    )
    cancellation_reason = models.TextField(
        null=True,
        blank=True,
        verbose_name="Cancellation Reason"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_purchase_orders',
        verbose_name="Created By"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_purchase_orders',
        verbose_name="Approved By"
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Approved At"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_purchase_orders'
        ordering = ['-order_date', '-id']
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"

    def __str__(self):
        return f"{self.purchase_order_number} - {self.supplier.company_name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.purchase_order_number:
            year = self.order_date.year if self.order_date else timezone.now().year
            prefix = f"PO-{year}-"
            with transaction.atomic():
                last_po = PurchaseOrder.objects.select_for_update().filter(
                    purchase_order_number__startswith=prefix
                ).order_by('-id').first()
                max_num = 0
                if last_po:
                    for po in PurchaseOrder.objects.filter(purchase_order_number__startswith=prefix):
                        match = re.search(r'PO-\d+-(\d+)', po.purchase_order_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while PurchaseOrder.objects.filter(purchase_order_number=candidate).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.purchase_order_number = candidate
        super().save(*args, **kwargs)


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Purchase Order Reference"
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='purchase_order_items',
        verbose_name="Product / Raw Material",
        help_text="Active Pharmaceutical Ingredient (API), Excipient, or Packaging Material"
    )
    ordered_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Ordered Quantity",
        help_text="Total quantity ordered (e.g. in KG, Litre, Box, Roll)"
    )
    received_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Received Quantity",
        help_text="Total quantity delivered and accepted in warehouse via GRN"
    )
    unit_price_in_order_currency = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name="Unit Price in Order Currency"
    )
    total_price_in_order_currency = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Price in Order Currency"
    )
    total_price_in_bdt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Price in BDT"
    )
    technical_specifications = models.TextField(
        null=True,
        blank=True,
        verbose_name="Technical & Pharmacopeial Specifications"
    )

    class Meta:
        db_table = 'purchases_purchase_order_items'
        ordering = ['id']
        verbose_name = "Purchase Order Item"
        verbose_name_plural = "Purchase Order Items"

    def __str__(self):
        return f"{self.product.name} ({self.ordered_quantity} {self.product.unit}) - PO: {self.purchase_order.purchase_order_number}"

    @property
    def remaining_quantity_to_receive(self):
        return max(Decimal('0.000'), self.ordered_quantity - self.received_quantity)

    @property
    def is_fully_received(self):
        return self.received_quantity >= self.ordered_quantity

    def save(self, *args, **kwargs):
        if self.ordered_quantity and self.unit_price_in_order_currency:
            self.total_price_in_order_currency = (
                Decimal(str(self.ordered_quantity)) * Decimal(str(self.unit_price_in_order_currency))
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            rate = self.purchase_order.exchange_rate if (self.purchase_order and self.purchase_order.exchange_rate) else Decimal('1.0000')
            self.total_price_in_bdt = (
                self.total_price_in_order_currency * Decimal(str(rate))
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 3. Letter of Credit (LC), Documents & Landed Cost Models
# -----------------------------------------------------------------------------

class LetterOfCreditType(models.TextChoices):
    SIGHT = 'SIGHT', 'Sight LC (পেমেন্ট ডকুমেন্টস আসার সাথে সাথে)'
    DEFERRED = 'DEFERRED', 'Deferred Payment LC (বিলম্বিত পেমেন্ট)'
    USANCE = 'USANCE', 'Usance LC (মেয়াদী ঋণপত্র - ৩০/৬০/৯০ দিন)'
    REVOLVING = 'REVOLVING', 'Revolving LC (নবায়নযোগ্য ঋণপত্র)'


class LetterOfCreditStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft Application'
    APPLICATION = 'APPLICATION', 'Submitted to Bank'
    OPENED = 'OPENED', 'LC Opened & Active'
    SHIPPED = 'SHIPPED', 'Goods Shipped by Supplier (On Vessel)'
    PORT_ARRIVED = 'PORT_ARRIVED', 'Arrived at Discharge Port'
    CUSTOMS_CLEARED = 'CUSTOMS_CLEARED', 'Customs Assessment & Duty Cleared'
    RECEIVED = 'RECEIVED', 'Goods Received at Factory Warehouse'
    CLOSED = 'CLOSED', 'LC Fully Settled & Closed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class LetterOfCredit(models.Model):
    letter_of_credit_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Letter of Credit (LC) Number",
        help_text="Bank issued LC reference or auto-generated system code (e.g. LC-2026-0001)"
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='letters_of_credit',
        verbose_name="Overseas Supplier / Beneficiary"
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='letters_of_credit',
        verbose_name="Purchase Order Reference"
    )

    # Issuing Bank Account (Linked to Chart of Accounts)
    issuing_bank_account = models.ForeignKey(
        'accounting.AccountHead',
        on_delete=models.PROTECT,
        related_name='issued_lcs',
        verbose_name="Issuing Bank Ledger Account",
        help_text="Bank account head used to fund and open this LC"
    )
    issuing_branch_name = models.CharField(
        max_length=150,
        verbose_name="Bank Branch Name"
    )

    letter_of_credit_type = models.CharField(
        max_length=20,
        choices=LetterOfCreditType.choices,
        default=LetterOfCreditType.SIGHT,
        verbose_name="LC Type"
    )
    incoterm = models.CharField(
        max_length=20,
        choices=IncotermsChoice.choices,
        default=IncotermsChoice.CFR,
        verbose_name="Incoterms (FOB/CIF/CFR/EXW)"
    )

    # Currencies & Values
    currency = models.CharField(
        max_length=10,
        default='USD',
        verbose_name="LC Currency"
    )
    total_amount_in_foreign_currency = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Total Foreign Currency Amount"
    )
    exchange_rate_to_bdt = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="Exchange Rate to BDT"
    )
    total_amount_in_bdt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Amount in BDT"
    )
    bank_margin_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Bank Margin Percentage (%)"
    )
    bank_margin_amount_in_bdt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Bank Margin Cash Amount (BDT)"
    )

    # Key Dates
    lc_opening_date = models.DateField(
        verbose_name="LC Opening Date"
    )
    lc_expiry_date = models.DateField(
        verbose_name="LC Expiry Date"
    )
    latest_shipment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Latest Shipment Deadline"
    )

    # Pipeline Status
    status = models.CharField(
        max_length=30,
        choices=LetterOfCreditStatus.choices,
        default=LetterOfCreditStatus.DRAFT,
        verbose_name="LC Stage / Status"
    )

    # Logistics & Customs
    harmonized_system_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="HS Code"
    )
    port_of_loading = models.CharField(
        max_length=100,
        verbose_name="Port of Loading (Origin)"
    )
    port_of_discharge = models.CharField(
        max_length=100,
        default="Chattogram Sea Port / Dhaka Airport",
        verbose_name="Port of Discharge (Destination)"
    )
    clearing_and_forwarding_agent_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="C&F Agent Name"
    )
    insurance_company_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Marine Insurance Company"
    )
    insurance_cover_note_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Insurance Cover Note Number"
    )

    # Accounting Margin Voucher Link
    margin_voucher = models.ForeignKey(
        'accounting.Voucher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='margin_funded_lcs',
        verbose_name="LC Margin Accounting Voucher"
    )

    special_notes = models.TextField(
        null=True,
        blank=True,
        verbose_name="Special Conditions & Notes"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_lcs',
        verbose_name="Created By"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_letters_of_credit'
        ordering = ['-lc_opening_date', '-id']
        verbose_name = "Letter of Credit (LC)"
        verbose_name_plural = "Letters of Credit (LCs)"

    def __str__(self):
        return f"{self.letter_of_credit_number} - {self.supplier.company_name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.letter_of_credit_number:
            year = self.lc_opening_date.year if self.lc_opening_date else timezone.now().year
            prefix = f"LC-{year}-"
            with transaction.atomic():
                last_lc = LetterOfCredit.objects.select_for_update().filter(
                    letter_of_credit_number__startswith=prefix
                ).order_by('-id').first()
                max_num = 0
                if last_lc:
                    for lc in LetterOfCredit.objects.filter(letter_of_credit_number__startswith=prefix):
                        match = re.search(r'LC-\d+-(\d+)', lc.letter_of_credit_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while LetterOfCredit.objects.filter(letter_of_credit_number=candidate).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.letter_of_credit_number = candidate

        if self.total_amount_in_foreign_currency and self.exchange_rate_to_bdt:
            self.total_amount_in_bdt = (
                Decimal(str(self.total_amount_in_foreign_currency)) * Decimal(str(self.exchange_rate_to_bdt))
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if self.bank_margin_percentage:
                self.bank_margin_amount_in_bdt = (
                    self.total_amount_in_bdt * (Decimal(str(self.bank_margin_percentage)) / Decimal('100'))
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        super().save(*args, **kwargs)


class LetterOfCreditDocumentType(models.TextChoices):
    PROFORMA_INVOICE = 'PROFORMA_INVOICE', 'Proforma Invoice (PI - প্রফর্মা ইনভয়েস)'
    BILL_OF_LADING = 'BILL_OF_LADING', 'Bill of Lading / Air Waybill (B/L - জাহাজীকরণ দলিল)'
    PACKING_LIST = 'PACKING_LIST', 'Packing List (প্যাকিং ও ওজন তালিকা)'
    CERTIFICATE_OF_ANALYSIS = 'CERTIFICATE_OF_ANALYSIS', 'Certificate of Analysis (COA - ল্যাব টেস্ট রিপোর্ট)'
    BILL_OF_ENTRY = 'BILL_OF_ENTRY', 'Bill of Entry (B/E - কাস্টমস শুল্কায়ন ছাড়পত্র)'
    INSURANCE_CERTIFICATE = 'INSURANCE_CERTIFICATE', 'Marine Insurance Certificate (বীমা পলিসি সনদ)'
    CERTIFICATE_OF_ORIGIN = 'CERTIFICATE_OF_ORIGIN', 'Certificate of Origin (উৎস দেশ সনদ)'
    OTHER = 'OTHER', 'Other Regulatory Document (অন্যান্য নথি)'


class LCDocument(models.Model):
    letter_of_credit = models.ForeignKey(
        LetterOfCredit,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name="Letter of Credit Reference"
    )
    document_type = models.CharField(
        max_length=50,
        choices=LetterOfCreditDocumentType.choices,
        default=LetterOfCreditDocumentType.PROFORMA_INVOICE,
        verbose_name="Document Type / Classification"
    )
    document_title = models.CharField(
        max_length=255,
        verbose_name="Document Title / File Name"
    )
    document_file_url = models.URLField(
        max_length=500,
        verbose_name="Document File URL"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_lc_documents',
        verbose_name="Uploaded By"
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Uploaded Timestamp"
    )

    class Meta:
        db_table = 'purchases_lc_documents'
        ordering = ['-uploaded_at']
        verbose_name = "Letter of Credit Document"
        verbose_name_plural = "Letter of Credit Documents"

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.document_title} (LC: {self.letter_of_credit.letter_of_credit_number})"


class LCLandingCost(models.Model):
    letter_of_credit = models.OneToOneField(
        LetterOfCredit,
        on_delete=models.CASCADE,
        related_name='landing_cost',
        verbose_name="Letter of Credit Reference"
    )
    # Customs Duties & Government Taxes
    customs_duty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Customs Duty (CD - আমদানি শুল্ক)"
    )
    regulatory_duty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Regulatory Duty (RD - রেগুলেটরি শুল্ক)"
    )
    supplementary_duty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Supplementary Duty (SD - সম্পূরক শুল্ক)"
    )
    value_added_tax = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Value Added Tax (VAT - আমদানি মূসক)"
    )
    advance_income_tax = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Advance Income Tax (AIT - অগ্রিম আয়কর)"
    )
    advance_tax = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Advance Tax (AT - অগ্রিম কর)"
    )

    # Freight, Insurance & Logistics
    freight_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="International Freight Charges"
    )
    insurance_premium = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Marine Insurance Premium"
    )
    clearing_and_forwarding_agency_fee = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="C&F Agency Service Fee"
    )
    port_demurrage_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Port & Demurrage Charges"
    )
    bank_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Bank Processing & LTR Charges"
    )
    other_handling_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Other Handling & Local Transport Charges"
    )

    total_landed_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Grand Total Landed Cost (BDT)"
    )
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="Is Landed Cost Finalized"
    )
    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Finalized Timestamp"
    )
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finalized_landed_costs',
        verbose_name="Finalized By"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_lc_landing_costs'
        verbose_name = "LC Landing Cost"
        verbose_name_plural = "LC Landing Costs"

    def __str__(self):
        return f"Landed Cost for LC: {self.letter_of_credit.letter_of_credit_number} -> Total: {self.total_landed_cost} BDT"

    def compute_total(self):
        base_bdt = self.letter_of_credit.total_amount_in_bdt or Decimal('0.00')
        duties_and_charges = (
            self.customs_duty +
            self.regulatory_duty +
            self.supplementary_duty +
            self.value_added_tax +
            self.advance_income_tax +
            self.advance_tax +
            self.freight_charges +
            self.insurance_premium +
            self.clearing_and_forwarding_agency_fee +
            self.port_demurrage_charges +
            self.bank_charges +
            self.other_handling_charges
        )
        self.total_landed_cost = base_bdt + duties_and_charges
        return self.total_landed_cost

    def save(self, *args, **kwargs):
        self.compute_total()
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 4. Goods Received Note (GRN) & Items Models
# -----------------------------------------------------------------------------

class GoodsReceivedNoteStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft GRN'
    QC_PENDING = 'QC_PENDING', 'Quality Control (QC) Pending'
    APPROVED = 'APPROVED', 'Approved & Stock Inflow Incurred'
    REJECTED = 'REJECTED', 'Rejected by Quality Control'


class GoodsReceivedNote(models.Model):
    goods_received_note_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="GRN Number",
        help_text="Unique auto-generated identifier (e.g. GRN-2026-0001)"
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='goods_received_notes',
        verbose_name="Purchase Order Reference"
    )
    letter_of_credit = models.ForeignKey(
        LetterOfCredit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='goods_received_notes',
        verbose_name="Letter of Credit Reference"
    )
    receiving_warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='received_grns',
        verbose_name="Receiving Warehouse"
    )
    received_date = models.DateField(
        verbose_name="Goods Received Date"
    )
    bill_of_entry_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Customs Bill of Entry (B/E) Number"
    )
    challan_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Vendor Delivery Challan Number"
    )
    status = models.CharField(
        max_length=30,
        choices=GoodsReceivedNoteStatus.choices,
        default=GoodsReceivedNoteStatus.DRAFT,
        verbose_name="GRN / QC Status"
    )

    # Double-entry Accounting Voucher Link
    accounting_voucher = models.ForeignKey(
        'accounting.Voucher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_purchase_vouchers',
        verbose_name="Accounting Purchase Bill Voucher"
    )

    special_notes = models.TextField(
        null=True,
        blank=True,
        verbose_name="Receiving Notes & Remarks"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_grns',
        verbose_name="Received By"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_grns',
        verbose_name="QC / Manager Approved By"
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Approved At"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_goods_received_notes'
        ordering = ['-received_date', '-id']
        verbose_name = "Goods Received Note (GRN)"
        verbose_name_plural = "Goods Received Notes (GRNs)"

    def __str__(self):
        return f"{self.goods_received_note_number} @ {self.receiving_warehouse.name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.goods_received_note_number:
            year = self.received_date.year if self.received_date else timezone.now().year
            prefix = f"GRN-{year}-"
            with transaction.atomic():
                last_grn = GoodsReceivedNote.objects.select_for_update().filter(
                    goods_received_note_number__startswith=prefix
                ).order_by('-id').first()
                max_num = 0
                if last_grn:
                    for grn in GoodsReceivedNote.objects.filter(goods_received_note_number__startswith=prefix):
                        match = re.search(r'GRN-\d+-(\d+)', grn.goods_received_note_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while GoodsReceivedNote.objects.filter(goods_received_note_number=candidate).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.goods_received_note_number = candidate
        super().save(*args, **kwargs)


class GoodsReceivedNoteItem(models.Model):
    goods_received_note = models.ForeignKey(
        GoodsReceivedNote,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="GRN Reference"
    )
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn_received_items',
        verbose_name="Matched PO Item Line"
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='grn_received_items',
        verbose_name="Received Product"
    )

    # Batch & Expiry (Critical for Pharma Manufacturing)
    batch_number = models.CharField(
        max_length=100,
        verbose_name="Batch / Lot Number"
    )
    manufacturing_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Manufacturing Date"
    )
    expiry_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Expiry Date"
    )

    # Quantities
    challan_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Challan / Invoiced Quantity"
    )
    received_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Physically Received Quantity"
    )
    accepted_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="QC Accepted Quantity"
    )
    rejected_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="QC Rejected Quantity"
    )

    # Landed Cost Valuation
    unit_landed_cost = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Unit Landed Cost (BDT)"
    )
    total_landed_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Line Landed Cost (BDT)"
    )
    qc_remarks = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="QC Inspection Notes"
    )

    class Meta:
        db_table = 'purchases_goods_received_note_items'
        ordering = ['id']
        verbose_name = "GRN Item"
        verbose_name_plural = "GRN Items"

    def __str__(self):
        return f"{self.product.name} [Batch: {self.batch_number}] -> Accepted: {self.accepted_quantity} {self.product.unit}"

    def save(self, *args, **kwargs):
        if self.accepted_quantity and self.unit_landed_cost:
            self.total_landed_cost = (
                Decimal(str(self.accepted_quantity)) * Decimal(str(self.unit_landed_cost))
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)
