from django.contrib import admin
from .models import (
    AccountHead, FiscalYear, AccountingPeriod,
    Voucher, JournalEntry, PaymentRecord,
    BankReconciliation
)


class JournalEntryInline(admin.TabularInline):
    model = JournalEntry
    extra = 0
    fields = ('line_no', 'account', 'debit_amount', 'credit_amount', 'description', 'party_type', 'party_id')


@admin.register(AccountHead)
class AccountHeadAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_group', 'is_reconciliation', 'is_active')
    list_filter = ('account_type', 'is_group', 'is_reconciliation', 'is_active')
    search_fields = ('code', 'name', 'description')
    ordering = ('code',)


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'start_date', 'end_date', 'is_current', 'is_locked', 'is_closed')
    list_filter = ('is_current', 'is_locked', 'is_closed')
    search_fields = ('name', 'code')


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'fiscal_year', 'period_number', 'start_date', 'end_date', 'is_current', 'is_locked', 'is_closed')
    list_filter = ('fiscal_year', 'is_current', 'is_locked', 'is_closed')
    ordering = ('fiscal_year', 'period_number')


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('voucher_number', 'voucher_type', 'voucher_date', 'status', 'total_debit', 'total_credit', 'is_reversed', 'created_by')
    list_filter = ('voucher_type', 'status', 'is_auto_generated', 'is_reversed', 'voucher_date')
    search_fields = ('voucher_number', 'reference_no', 'narration')
    inlines = [JournalEntryInline]
    date_hierarchy = 'voucher_date'


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('voucher', 'line_no', 'account', 'debit_amount', 'credit_amount', 'party_type', 'party_id')
    list_filter = ('account__account_type', 'party_type')
    search_fields = ('voucher__voucher_number', 'account__name', 'description')


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('receipt_no', 'payment_type', 'party_type', 'party_id', 'amount', 'payment_method', 'payment_date', 'voucher')
    list_filter = ('payment_type', 'party_type', 'payment_method', 'payment_date')
    search_fields = ('receipt_no', 'reference_no', 'notes')


@admin.register(BankReconciliation)
class BankReconciliationAdmin(admin.ModelAdmin):
    list_display = ('account', 'statement_date', 'statement_balance', 'gl_balance', 'difference', 'status', 'reconciled_by')
    list_filter = ('status', 'statement_date')
    search_fields = ('account__name', 'notes')
