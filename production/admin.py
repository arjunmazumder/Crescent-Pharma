from django.contrib import admin
from .models import (
    BOMHeader, BOMItem, ProductionLine, ProductionPlan,
    ProductionBatch, MaterialIssueSlip, MaterialIssueItem,
    ProductionStageLog, FinishedGoodsTransfer
)


class BOMItemInline(admin.TabularInline):
    model = BOMItem
    extra = 1
    fields = ['material', 'material_type', 'standard_quantity', 'unit', 'wastage_percentage']


@admin.register(BOMHeader)
class BOMHeaderAdmin(admin.ModelAdmin):
    list_display = ['bom_code', 'mfr_number', 'finished_product', 'version', 'standard_batch_size', 'batch_unit', 'is_approved', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_approved', 'batch_unit']
    search_fields = ['bom_code', 'mfr_number', 'finished_product__name', 'finished_product__unique_id']
    inlines = [BOMItemInline]
    readonly_fields = ['bom_code', 'created_at', 'updated_at']


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ['line_code', 'line_name', 'daily_capacity', 'cleanroom_classification', 'is_active', 'created_at']
    list_filter = ['is_active', 'cleanroom_classification']
    search_fields = ['line_code', 'line_name']


@admin.register(ProductionPlan)
class ProductionPlanAdmin(admin.ModelAdmin):
    list_display = ['plan_code', 'title', 'plan_type', 'start_date', 'end_date', 'status', 'total_target_batches', 'created_at']
    list_filter = ['plan_type', 'status']
    search_fields = ['plan_code', 'title']
    readonly_fields = ['plan_code', 'created_at', 'updated_at']


class MaterialIssueSlipInline(admin.TabularInline):
    model = MaterialIssueSlip
    extra = 0
    show_change_link = True
    fields = ['issue_number', 'warehouse', 'issued_date', 'status', 'issued_by']
    readonly_fields = ['issue_number']


class ProductionStageLogInline(admin.TabularInline):
    model = ProductionStageLog
    extra = 0
    fields = ['stage', 'started_at', 'completed_at', 'status', 'operator', 'machine_equipment_name', 'temperature_celsius', 'humidity_percentage']


class FinishedGoodsTransferInline(admin.TabularInline):
    model = FinishedGoodsTransfer
    extra = 0
    show_change_link = True
    fields = ['transfer_code', 'destination_warehouse', 'transfer_quantity', 'transfer_date', 'qc_release_certificate_number', 'is_received']
    readonly_fields = ['transfer_code']


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ['batch_number', 'finished_product', 'production_line', 'planned_quantity', 'actual_produced_quantity', 'status', 'current_stage', 'manufacturing_date', 'expiry_date']
    list_filter = ['status', 'current_stage', 'production_line', 'source_warehouse', 'destination_warehouse']
    search_fields = ['batch_number', 'finished_product__name', 'finished_product__unique_id', 'bom__bom_code']
    inlines = [ProductionStageLogInline, MaterialIssueSlipInline, FinishedGoodsTransferInline]
    readonly_fields = ['batch_number', 'created_at', 'updated_at']


class MaterialIssueItemInline(admin.TabularInline):
    model = MaterialIssueItem
    extra = 1
    fields = ['material', 'batch_number', 'standard_bom_quantity', 'issued_quantity', 'actual_consumed_quantity', 'wastage_quantity', 'returned_quantity']


@admin.register(MaterialIssueSlip)
class MaterialIssueSlipAdmin(admin.ModelAdmin):
    list_display = ['issue_number', 'batch', 'warehouse', 'issued_date', 'status', 'issued_by', 'received_by']
    list_filter = ['status', 'warehouse']
    search_fields = ['issue_number', 'batch__batch_number']
    inlines = [MaterialIssueItemInline]
    readonly_fields = ['issue_number', 'created_at', 'updated_at']


@admin.register(ProductionStageLog)
class ProductionStageLogAdmin(admin.ModelAdmin):
    list_display = ['batch', 'stage', 'started_at', 'completed_at', 'status', 'operator', 'temperature_celsius', 'humidity_percentage']
    list_filter = ['stage', 'status']
    search_fields = ['batch__batch_number', 'machine_equipment_name']


@admin.register(FinishedGoodsTransfer)
class FinishedGoodsTransferAdmin(admin.ModelAdmin):
    list_display = ['transfer_code', 'batch', 'finished_product', 'destination_warehouse', 'transfer_quantity', 'transfer_date', 'qc_release_certificate_number', 'is_received']
    list_filter = ['is_received', 'destination_warehouse']
    search_fields = ['transfer_code', 'batch__batch_number', 'qc_release_certificate_number']
    readonly_fields = ['transfer_code', 'created_at', 'updated_at']
