import calendar
import re
import datetime
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone


class AccountType(models.TextChoices):
    ASSET = 'ASSET', 'Asset (সম্পদ)'
    LIABILITY = 'LIABILITY', 'Liability (দায়)'
    EQUITY = 'EQUITY', 'Equity (মালিকানাস্বত্ব)'
    REVENUE = 'REVENUE', 'Revenue (আয়/বিক্রয়)'
    EXPENSE = 'EXPENSE', 'Expense (ব্যয়/খরচ)'


class PartyType(models.TextChoices):
    CUSTOMER = 'CUSTOMER', 'Customer / Client'
    SUPPLIER = 'SUPPLIER', 'Supplier / Vendor'
    EMPLOYEE = 'EMPLOYEE', 'Employee / Staff'


class VoucherType(models.TextChoices):
    JOURNAL = 'JOURNAL', 'Journal Voucher (JV)'
    CONTRA = 'CONTRA', 'Contra Voucher (CV)'
    PAYMENT = 'PAYMENT', 'Payment Voucher (CPV/BPV)'
    RECEIPT = 'RECEIPT', 'Receipt Voucher (CRV/BRV)'
    SALES_INVOICE = 'SALES_INVOICE', 'Sales Invoice Voucher (SIV)'
    PURCHASE_BILL = 'PURCHASE_BILL', 'Purchase Bill Voucher (PIV)'
    PAYROLL = 'PAYROLL', 'Payroll Disbursement Voucher (PYV)'


class VoucherStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SUBMITTED = 'SUBMITTED', 'Submitted for Approval'
    POSTED = 'POSTED', 'Posted / Committed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class ChequeStatus(models.TextChoices):
    ISSUED = 'ISSUED', 'Issued / Received'
    CLEARED = 'CLEARED', 'Cleared in Bank'
    BOUNCED = 'BOUNCED', 'Bounced / Dishonored'
    CANCELLED = 'CANCELLED', 'Cancelled'


class ReconciliationStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    RECONCILED = 'RECONCILED', 'Reconciled / Audited'


class AccountHead(models.Model):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    account_type = models.CharField(max_length=50, choices=AccountType.choices)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    is_group = models.BooleanField(
        default=False,
        help_text="True if this is a header/folder, False if transactional leaf account"
    )
    currency = models.CharField(max_length=10, default='BDT')
    is_reconciliation = models.BooleanField(
        default=False,
        help_text="Enabled for Cash/Bank reconciliation"
    )
    bank_account_no = models.CharField(max_length=100, null=True, blank=True)
    bank_branch = models.CharField(max_length=150, null=True, blank=True)
    routing_number = models.CharField(max_length=50, null=True, blank=True)
    is_system_locked = models.BooleanField(
        default=False,
        help_text="Protects vital ERP accounts (AR, AP, Retained Earnings) from accidental deletion"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounting_account_heads'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name} [{self.account_type}]"

    def save(self, *args, **kwargs):
        if not self.code:
            # Auto-generate code based on parent or account_type
            if self.parent and self.parent.code:
                last_child = AccountHead.objects.filter(parent=self.parent).order_by('-code').first()
                if last_child and last_child.code:
                    try:
                        num = int(last_child.code) + 1
                        self.code = str(num)
                    except ValueError:
                        self.code = f"{self.parent.code}-01"
                else:
                    self.code = f"{self.parent.code}01" if self.parent.code.isdigit() else f"{self.parent.code}-01"
            else:
                prefix_map = {
                    AccountType.ASSET: '1000',
                    AccountType.LIABILITY: '2000',
                    AccountType.EQUITY: '3000',
                    AccountType.REVENUE: '4000',
                    AccountType.EXPENSE: '5000'
                }
                base_code = prefix_map.get(self.account_type, '9000')
                candidate = base_code
                counter = 1
                while AccountHead.objects.filter(code=candidate).exists():
                    candidate = str(int(base_code) + counter * 100)
                    counter += 1
                self.code = candidate

        super().save(*args, **kwargs)


class FiscalYear(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g. FY 2026-2027")
    code = models.CharField(max_length=50, unique=True, help_text="e.g. FY26-27")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False, help_text="Prevents back-dated postings")
    is_closed = models.BooleanField(default=False, help_text="Year-end closed flag")
    retained_earnings_account = models.ForeignKey(
        AccountHead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retained_fiscal_years'
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_fiscal_years'
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_fiscal_years'
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounting_fiscal_years'
        ordering = ['-start_date']

    def __str__(self):
        status = " (Current)" if self.is_current else (" (Locked)" if self.is_locked else "")
        return f"{self.name}{status}"

    def generate_monthly_periods(self):
        """
        Automatically generates monthly AccountingPeriod records from start_date to end_date.
        """
        if not self.start_date or not self.end_date:
            return

        today = datetime.date.today()
        curr_start = self.start_date
        period_no = 1

        while curr_start <= self.end_date:
            _, last_day = calendar.monthrange(curr_start.year, curr_start.month)
            curr_month_end = datetime.date(curr_start.year, curr_start.month, last_day)
            period_end = min(curr_month_end, self.end_date)
            period_name = curr_start.strftime("%B %Y")

            is_cur = curr_start <= today <= period_end if self.is_current else False

            AccountingPeriod.objects.get_or_create(
                fiscal_year=self,
                period_number=period_no,
                defaults={
                    'name': period_name,
                    'start_date': curr_start,
                    'end_date': period_end,
                    'is_current': is_cur
                }
            )

            # Advance to the first day of next month
            if curr_start.month == 12:
                next_month_start = datetime.date(curr_start.year + 1, 1, 1)
            else:
                next_month_start = datetime.date(curr_start.year, curr_start.month + 1, 1)

            curr_start = next_month_start
            period_no += 1

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.end_date and self.start_date:
            try:
                next_year = self.start_date.replace(year=self.start_date.year + 1)
            except ValueError:
                next_year = self.start_date.replace(year=self.start_date.year + 1, day=28)
            self.end_date = next_year - datetime.timedelta(days=1)

        if self.is_current:
            FiscalYear.objects.exclude(pk=self.pk).update(is_current=False)

        super().save(*args, **kwargs)

        if is_new or not self.periods.exists():
            self.generate_monthly_periods()


class AccountingPeriod(models.Model):
    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.CASCADE,
        related_name='periods'
    )
    name = models.CharField(max_length=100, help_text="e.g. July 2026")
    period_number = models.IntegerField(help_text="1 to 12 sequence within fiscal year")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_accounting_periods'
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounting_periods'
        unique_together = ('fiscal_year', 'period_number')
        ordering = ['fiscal_year', 'period_number']

    def __str__(self):
        return f"{self.name} ({self.fiscal_year.code})"


class Voucher(models.Model):
    voucher_number = models.CharField(max_length=50, unique=True, db_index=True)
    voucher_type = models.CharField(max_length=50, choices=VoucherType.choices)
    voucher_date = models.DateField(db_index=True)
    period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='vouchers'
    )
    reference_no = models.CharField(max_length=100, null=True, blank=True)
    narration = models.TextField()
    status = models.CharField(
        max_length=50,
        choices=VoucherStatus.choices,
        default=VoucherStatus.DRAFT
    )
    total_debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    attachment_url = models.URLField(max_length=500, null=True, blank=True)
    is_auto_generated = models.BooleanField(default=False)
    source_module = models.CharField(max_length=50, null=True, blank=True)  # SALES, PAYROLL, INVENTORY, MANUAL
    source_id = models.IntegerField(null=True, blank=True)
    cheque_number = models.CharField(max_length=100, null=True, blank=True)
    cheque_date = models.DateField(null=True, blank=True)
    cheque_status = models.CharField(max_length=50, choices=ChequeStatus.choices, null=True, blank=True)
    reversal_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_by'
    )
    is_reversed = models.BooleanField(default=False)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rejected_vouchers'
    )
    rejection_reason = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_vouchers'
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posted_vouchers'
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounting_vouchers'
        ordering = ['-voucher_date', '-id']

    def __str__(self):
        return f"{self.voucher_number} [{self.voucher_type}] - {self.voucher_date} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.voucher_number:
            type_code_map = {
                VoucherType.JOURNAL: 'JV',
                VoucherType.CONTRA: 'CV',
                VoucherType.PAYMENT: 'CPV',
                VoucherType.RECEIPT: 'CRV',
                VoucherType.SALES_INVOICE: 'SIV',
                VoucherType.PURCHASE_BILL: 'PIV',
                VoucherType.PAYROLL: 'PYV'
            }
            prefix_code = type_code_map.get(self.voucher_type, 'JV')
            year = self.voucher_date.year if self.voucher_date else timezone.now().year
            prefix = f"{prefix_code}-{year}-"
            with transaction.atomic():
                last_voucher = Voucher.objects.select_for_update().filter(voucher_number__startswith=prefix).order_by('-id').first()
                max_num = 0
                if last_voucher:
                    for v in Voucher.objects.filter(voucher_number__startswith=prefix):
                        match = re.search(r'^[A-Z]+-\d+-(\d+)', v.voucher_number)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{prefix}{next_number:04d}"
                while Voucher.objects.filter(voucher_number=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{prefix}{next_number:04d}"
                self.voucher_number = candidate
        super().save(*args, **kwargs)


class JournalEntry(models.Model):
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.CASCADE,
        related_name='entries'
    )
    line_no = models.IntegerField(default=1)
    account = models.ForeignKey(
        AccountHead,
        on_delete=models.PROTECT,
        related_name='journal_entries'
    )
    debit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    credit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    description = models.CharField(max_length=255, null=True, blank=True)
    party_type = models.CharField(max_length=50, choices=PartyType.choices, null=True, blank=True)
    party_id = models.IntegerField(null=True, blank=True, db_index=True)
    foreign_currency = models.CharField(max_length=10, null=True, blank=True)
    foreign_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    cost_center = models.CharField(max_length=100, null=True, blank=True)
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounting_entries'
    )
    is_reconciled = models.BooleanField(default=False)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounting_journal_entries'
        ordering = ['line_no', 'id']

    def __str__(self):
        amt = f"Dr {self.debit_amount}" if self.debit_amount > 0 else f"Cr {self.credit_amount}"
        return f"{self.voucher.voucher_number} Line {self.line_no}: {self.account.name} -> {amt}"


class PaymentRecord(models.Model):
    PAYMENT_TYPE_CHOICES = [
        ('RECEIPT', 'Customer Collection (টাকা প্রাপ্তি)'),
        ('PAYMENT', 'Supplier / Vendor Payment (টাকা প্রদান)'),
    ]

    receipt_no = models.CharField(max_length=50, unique=True, db_index=True)
    payment_type = models.CharField(max_length=50, choices=PAYMENT_TYPE_CHOICES, default='RECEIPT')
    party_type = models.CharField(max_length=50, choices=PartyType.choices, default=PartyType.CUSTOMER)
    party_id = models.IntegerField(db_index=True)
    order = models.ForeignKey(
        'sales.CustomerOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_records'
    )
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='CASH')
    deposit_to_account = models.ForeignKey(
        AccountHead,
        on_delete=models.PROTECT,
        related_name='deposited_payments'
    )
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_payments'
    )
    reference_no = models.CharField(max_length=100, null=True, blank=True, help_text="TrxID / Cheque No / Slip No")
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounting_payment_records'
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"{self.receipt_no} - {self.payment_type} ({self.amount} BDT)"

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            prefix = "MR-" if self.payment_type == 'RECEIPT' else "PV-"
            year = self.payment_date.year if self.payment_date else timezone.now().year
            full_prefix = f"{prefix}{year}-"
            with transaction.atomic():
                last_rec = PaymentRecord.objects.select_for_update().filter(receipt_no__startswith=full_prefix).order_by('-id').first()
                max_num = 0
                if last_rec:
                    for r in PaymentRecord.objects.filter(receipt_no__startswith=full_prefix):
                        match = re.search(r'^[A-Z]+-\d+-(\d+)', r.receipt_no)
                        if match:
                            num = int(match.group(1))
                            if num > max_num:
                                max_num = num
                next_number = max_num + 1
                candidate = f"{full_prefix}{next_number:04d}"
                while PaymentRecord.objects.filter(receipt_no=candidate).exclude(pk=self.pk).exists():
                    next_number += 1
                    candidate = f"{full_prefix}{next_number:04d}"
                self.receipt_no = candidate
        super().save(*args, **kwargs)


class BankReconciliation(models.Model):
    account = models.ForeignKey(
        AccountHead,
        on_delete=models.PROTECT,
        related_name='bank_reconciliations'
    )
    statement_date = models.DateField()
    statement_balance = models.DecimalField(max_digits=14, decimal_places=2)
    gl_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    unpresented_cheques_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    uncredited_deposits_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    adjusted_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    difference = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(
        max_length=50,
        choices=ReconciliationStatus.choices,
        default=ReconciliationStatus.DRAFT
    )
    attachment_url = models.URLField(max_length=500, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounting_bank_reconciliations'
        ordering = ['-statement_date', '-id']

    def __str__(self):
        return f"BRS: {self.account.name} @ {self.statement_date} [{self.status}]"
