from decimal import Decimal
from rest_framework import serializers
from .models import (
    AccountHead, FiscalYear, AccountingPeriod,
    Voucher, JournalEntry, PaymentRecord,
    BankReconciliation, VoucherType, VoucherStatus,
    PartyType, AccountType
)


# =====================================================================
# Chart of Accounts (COA) Serializers
# =====================================================================

class AccountHeadSerializer(serializers.ModelSerializer):
    parent_code = serializers.CharField(source='parent.code', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)

    class Meta:
        model = AccountHead
        fields = [
            'id', 'code', 'name', 'description', 'account_type',
            'parent', 'parent_code', 'parent_name',
            'is_group', 'currency', 'is_reconciliation',
            'bank_account_no', 'bank_branch', 'routing_number',
            'is_system_locked', 'is_active', 'created_at'
        ]
        read_only_fields = [
            'id', 'parent_code', 'parent_name', 'is_system_locked', 'created_at'
        ]


class AccountHeadTreeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = AccountHead
        fields = [
            'id', 'code', 'name', 'account_type', 'is_group',
            'currency', 'is_reconciliation', 'is_active', 'children'
        ]

    def get_children(self, obj):
        children = obj.children.filter(is_active=True).order_by('code')
        return AccountHeadTreeSerializer(children, many=True).data


# =====================================================================
# Fiscal Calendar Serializers
# =====================================================================

class FiscalYearMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalYear
        fields = [
            'id', 'name', 'code', 'start_date', 'end_date',
            'is_current', 'is_locked', 'is_closed'
        ]


class AccountingPeriodSerializer(serializers.ModelSerializer):
    fiscal_year_name = serializers.CharField(source='fiscal_year.name', read_only=True)
    fiscal_year_code = serializers.CharField(source='fiscal_year.code', read_only=True)
    fiscal_year_details = FiscalYearMiniSerializer(source='fiscal_year', read_only=True)

    class Meta:
        model = AccountingPeriod
        fields = [
            'id', 'fiscal_year', 'fiscal_year_code', 'fiscal_year_name', 'fiscal_year_details',
            'name', 'period_number',
            'start_date', 'end_date', 'is_current', 'is_locked', 'is_closed',
            'created_at'
        ]
        read_only_fields = [
            'id', 'fiscal_year_code', 'fiscal_year_name', 'fiscal_year_details', 'is_locked', 'is_closed', 'created_at'
        ]


class FiscalYearSerializer(serializers.ModelSerializer):
    periods = AccountingPeriodSerializer(many=True, read_only=True)

    class Meta:
        model = FiscalYear
        fields = [
            'id', 'name', 'code', 'start_date', 'end_date',
            'is_current', 'is_locked', 'is_closed',
            'retained_earnings_account', 'notes', 'periods', 'created_at'
        ]
        read_only_fields = [
            'id', 'is_locked', 'is_closed', 'periods', 'created_at'
        ]
        extra_kwargs = {
            'end_date': {'required': False}
        }


# =====================================================================
# Voucher & Journal Entry Serializers
# =====================================================================

class JournalEntrySerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_type = serializers.CharField(source='account.account_type', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            'id', 'line_no', 'account', 'account_code', 'account_name', 'account_type',
            'debit_amount', 'credit_amount', 'description',
            'party_type', 'party_id',
            'cost_center', 'product', 'product_name'
        ]
        read_only_fields = ['id', 'account_code', 'account_name', 'account_type', 'product_name']


class JournalEntryCreateSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(help_text="Target transactional AccountHead ID")
    debit_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    credit_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    description = serializers.CharField(required=False, allow_blank=True, default='')
    party_type = serializers.ChoiceField(choices=PartyType.choices, required=False, allow_null=True)
    party_id = serializers.IntegerField(required=False, allow_null=True)
    cost_center = serializers.CharField(required=False, allow_blank=True, default='')
    product_id = serializers.IntegerField(required=False, allow_null=True)


class VoucherSerializer(serializers.ModelSerializer):
    entries = JournalEntrySerializer(many=True, read_only=True)
    period_name = serializers.CharField(source='period.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    posted_by_username = serializers.CharField(source='posted_by.username', read_only=True)

    class Meta:
        model = Voucher
        fields = [
            'id', 'voucher_number', 'voucher_type', 'voucher_date',
            'period_name', 'reference_no', 'narration',
            'status', 'total_debit', 'total_credit',
            'attachment_url', 'is_auto_generated', 'source_module',
            'cheque_number', 'cheque_date', 'cheque_status',
            'is_reversed', 'created_by_username', 'posted_by_username',
            'entries', 'created_at'
        ]
        read_only_fields = [
            'id', 'voucher_number', 'period_name', 'status',
            'total_debit', 'total_credit', 'is_auto_generated', 'source_module',
            'is_reversed', 'created_by_username', 'posted_by_username', 'created_at'
        ]


class VoucherCreateSerializer(serializers.Serializer):
    voucher_type = serializers.ChoiceField(choices=VoucherType.choices, default=VoucherType.JOURNAL)
    voucher_date = serializers.DateField()
    narration = serializers.CharField()
    reference_no = serializers.CharField(required=False, allow_blank=True, default='', help_text="Bill No, TrxID, or Reference")
    attachment_url = serializers.URLField(required=False, allow_blank=True, default='')
    cheque_number = serializers.CharField(required=False, allow_blank=True, default='')
    cheque_date = serializers.DateField(required=False, allow_null=True)
    cheque_status = serializers.CharField(required=False, allow_blank=True, default='')
    auto_post = serializers.BooleanField(default=True, help_text="Immediately post to General Ledger if balanced")
    entries = JournalEntryCreateSerializer(many=True, help_text="Balanced debit and credit line items")


class VoucherReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, help_text="Reason for reversing the posted voucher")


# =====================================================================
# Payment & Collection Serializers
# =====================================================================

class PaymentRecordSerializer(serializers.ModelSerializer):
    deposit_account_name = serializers.CharField(source='deposit_to_account.name', read_only=True)
    deposit_account_code = serializers.CharField(source='deposit_to_account.code', read_only=True)
    voucher_number = serializers.CharField(source='voucher.voucher_number', read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)

    class Meta:
        model = PaymentRecord
        fields = [
            'id', 'receipt_no', 'payment_type', 'party_type', 'party_id',
            'order', 'order_number', 'payment_date', 'amount',
            'payment_method', 'deposit_to_account', 'deposit_account_name', 'deposit_account_code',
            'voucher_number', 'reference_no', 'notes', 'created_at'
        ]
        read_only_fields = [
            'id', 'receipt_no', 'order_number', 'deposit_account_name',
            'deposit_account_code', 'voucher_number', 'created_at'
        ]


class PaymentRecordCreateSerializer(serializers.Serializer):
    payment_type = serializers.ChoiceField(choices=['RECEIPT', 'PAYMENT'], default='RECEIPT', help_text="RECEIPT (Collection) / PAYMENT (Disbursement)")
    party_type = serializers.ChoiceField(choices=PartyType.choices, default=PartyType.CUSTOMER)
    party_id = serializers.IntegerField(help_text="Customer or Supplier ID")
    order_id = serializers.IntegerField(required=False, allow_null=True, help_text="Optional CustomerOrder ID for auto-reconciliation")
    payment_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_method = serializers.CharField(default='CASH', help_text="CASH, CHEQUE, BANK_TRANSFER, MFS_BKASH")
    deposit_to_account_id = serializers.IntegerField(help_text="AccountHead ID for Cash/Bank account")
    reference_no = serializers.CharField(required=False, allow_blank=True, default='', help_text="TrxID / Cheque No / Slip No")
    notes = serializers.CharField(required=False, allow_blank=True, default='')


# =====================================================================
# Bank Reconciliation Serializers
# =====================================================================

class BankReconciliationSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    reconciled_by_username = serializers.CharField(source='reconciled_by.username', read_only=True)

    class Meta:
        model = BankReconciliation
        fields = [
            'id', 'account', 'account_code', 'account_name', 'statement_date',
            'statement_balance', 'gl_balance', 'unpresented_cheques_total', 'uncredited_deposits_total',
            'adjusted_balance', 'difference', 'status',
            'attachment_url', 'notes', 'reconciled_by_username', 'created_at'
        ]
        read_only_fields = [
            'id', 'account_code', 'account_name', 'gl_balance',
            'unpresented_cheques_total', 'uncredited_deposits_total',
            'adjusted_balance', 'difference', 'status', 'reconciled_by_username', 'created_at'
        ]


class BankReconciliationCreateSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(help_text="Bank AccountHead ID")
    statement_date = serializers.DateField(help_text="Closing date of bank statement")
    statement_balance = serializers.DecimalField(max_digits=14, decimal_places=2, help_text="Closing balance from physical bank statement")
    cleared_entry_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text="List of JournalEntry IDs that have cleared in the bank statement"
    )
    attachment_url = serializers.URLField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
