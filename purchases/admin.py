from django.contrib import admin
from purchases.models import (
    Supplier,
    PurchaseOrder, PurchaseOrderItem,
    LetterOfCredit, LCDocument, LCLandingCost,
    GoodsReceivedNote, GoodsReceivedNoteItem
)


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    fields = ('product', 'ordered_quantity', 'received_quantity', 'unit_price_in_order_currency', 'total_price_in_order_currency', 'total_price_in_bdt')
    readonly_fields = ('received_quantity', 'total_price_in_order_currency', 'total_price_in_bdt')


class LCDocumentInline(admin.TabularInline):
    model = LCDocument
    extra = 1
    fields = ('document_type', 'document_title', 'document_file_url', 'uploaded_by', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


class LCLandingCostInline(admin.StackedInline):
    model = LCLandingCost
    can_delete = False
    fields = (
        ('customs_duty', 'regulatory_duty', 'supplementary_duty'),
        ('value_added_tax', 'advance_income_tax', 'advance_tax'),
        ('freight_charges', 'insurance_premium', 'clearing_and_forwarding_agency_fee'),
        ('port_demurrage_charges', 'bank_charges', 'other_handling_charges'),
        ('total_landed_cost', 'is_finalized')
    )
    readonly_fields = ('total_landed_cost',)


class GoodsReceivedNoteItemInline(admin.TabularInline):
    model = GoodsReceivedNoteItem
    extra = 1
    fields = ('product', 'batch_number', 'manufacturing_date', 'expiry_date', 'challan_quantity', 'received_quantity', 'accepted_quantity', 'rejected_quantity', 'unit_landed_cost', 'total_landed_cost')
    readonly_fields = ('total_landed_cost',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('supplier_code', 'company_name', 'supplier_type', 'supply_category', 'country', 'currency', 'phone_number', 'audit_status', 'is_active')
    list_filter = ('supplier_type', 'supply_category', 'audit_status', 'is_active', 'country')
    search_fields = ('company_name', 'supplier_code', 'phone_number', 'email_address', 'drug_license_number')
    readonly_fields = ('supplier_code', 'created_at', 'updated_at')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('purchase_order_number', 'supplier', 'order_date', 'status', 'currency', 'total_amount_in_foreign_currency', 'total_amount_in_bdt', 'created_by')
    list_filter = ('status', 'order_type', 'currency', 'order_date')
    search_fields = ('purchase_order_number', 'supplier__company_name', 'proforma_invoice_number', 'dgda_blocklist_number')
    readonly_fields = ('purchase_order_number', 'total_amount_in_foreign_currency', 'total_amount_in_bdt', 'created_at', 'updated_at')
    inlines = [PurchaseOrderItemInline]


@admin.register(LetterOfCredit)
class LetterOfCreditAdmin(admin.ModelAdmin):
    list_display = ('letter_of_credit_number', 'supplier', 'letter_of_credit_type', 'currency', 'total_amount_in_foreign_currency', 'total_amount_in_bdt', 'status', 'lc_opening_date')
    list_filter = ('status', 'letter_of_credit_type', 'currency', 'lc_opening_date')
    search_fields = ('letter_of_credit_number', 'supplier__company_name', 'harmonized_system_code')
    readonly_fields = ('letter_of_credit_number', 'total_amount_in_bdt', 'bank_margin_amount_in_bdt', 'created_at', 'updated_at')
    inlines = [LCDocumentInline, LCLandingCostInline]


@admin.register(GoodsReceivedNote)
class GoodsReceivedNoteAdmin(admin.ModelAdmin):
    list_display = ('goods_received_note_number', 'purchase_order', 'letter_of_credit', 'receiving_warehouse', 'received_date', 'status', 'created_by')
    list_filter = ('status', 'receiving_warehouse', 'received_date')
    search_fields = ('goods_received_note_number', 'bill_of_entry_number', 'challan_number')
    readonly_fields = ('goods_received_note_number', 'created_at', 'updated_at')
    inlines = [GoodsReceivedNoteItemInline]
