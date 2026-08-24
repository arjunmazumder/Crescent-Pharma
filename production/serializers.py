from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from inventory.models import Product, Warehouse
from inventory.serializers import ProductSerializer, WarehouseSerializer
from users.serializers import UserSerializer
from .models import (
    BOMHeader, BOMItem, ProductionLine, ProductionPlan,
    ProductionBatch, MaterialIssueSlip, MaterialIssueItem,
    ProductionStageLog, FinishedGoodsTransfer
)


# -----------------------------------------------------------------------------
# 1. BOM Serializers
# -----------------------------------------------------------------------------

class BOMItemSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.unique_id', read_only=True)

    class Meta:
        model = BOMItem
        fields = [
            'id',
            'bom',
            'material',
            'material_name',
            'material_code',
            'material_type',
            'standard_quantity',
            'unit',
            'wastage_percentage',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'bom', 'created_at', 'updated_at']


class BOMItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BOMItem
        fields = [
            'material',
            'material_type',
            'standard_quantity',
            'unit',
            'wastage_percentage',
        ]


class BOMHeaderSerializer(serializers.ModelSerializer):
    items = BOMItemSerializer(many=True, read_only=True)
    finished_product_details = ProductSerializer(source='finished_product', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = BOMHeader
        fields = [
            'id',
            'bom_code',
            'mfr_number',
            'finished_product',
            'finished_product_details',
            'version',
            'standard_batch_size',
            'batch_unit',
            'is_active',
            'is_approved',
            'approved_by',
            'approved_by_name',
            'approved_at',
            'preparation_instructions',
            'created_by',
            'created_by_name',
            'created_at',
            'updated_at',
            'items',
        ]
        read_only_fields = ['id', 'bom_code', 'is_approved', 'approved_by', 'approved_at', 'created_by', 'created_at', 'updated_at']


class BOMCreateSerializer(serializers.ModelSerializer):
    items = BOMItemCreateSerializer(many=True, required=False)

    class Meta:
        model = BOMHeader
        fields = [
            'mfr_number',
            'finished_product',
            'version',
            'standard_batch_size',
            'batch_unit',
            'is_active',
            'preparation_instructions',
            'items',
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        request = self.context.get('request')
        user = request.user if request and request.user.is_authenticated else None

        with transaction.atomic():
            bom = BOMHeader.objects.create(created_by=user, **validated_data)
            items_to_create = []
            for item in items_data:
                items_to_create.append(BOMItem(bom=bom, **item))
            if items_to_create:
                BOMItem.objects.bulk_create(items_to_create)
            return bom


# -----------------------------------------------------------------------------
# 2. ProductionLine & ProductionPlan Serializers
# -----------------------------------------------------------------------------

class ProductionLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionLine
        fields = [
            'id',
            'line_code',
            'line_name',
            'daily_capacity',
            'cleanroom_classification',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProductionPlanSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    batches_count = serializers.IntegerField(source='batches.count', read_only=True)

    class Meta:
        model = ProductionPlan
        fields = [
            'id',
            'plan_code',
            'title',
            'plan_type',
            'start_date',
            'end_date',
            'status',
            'total_target_batches',
            'batches_count',
            'notes',
            'created_by',
            'created_by_name',
            'approved_by',
            'approved_by_name',
            'approved_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'plan_code', 'approved_by', 'approved_at', 'created_by', 'created_at', 'updated_at']


# -----------------------------------------------------------------------------
# 3. MaterialIssue & IPQC Stage Log Serializers
# -----------------------------------------------------------------------------

class MaterialIssueItemSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_code = serializers.CharField(source='material.unique_id', read_only=True)
    unit = serializers.CharField(source='material.unit', read_only=True)

    class Meta:
        model = MaterialIssueItem
        fields = [
            'id',
            'material_issue_slip',
            'material',
            'material_name',
            'material_code',
            'batch_number',
            'standard_bom_quantity',
            'issued_quantity',
            'actual_consumed_quantity',
            'wastage_quantity',
            'returned_quantity',
            'unit',
        ]
        read_only_fields = ['id', 'material_issue_slip']


class MaterialIssueSlipSerializer(serializers.ModelSerializer):
    items = MaterialIssueItemSerializer(many=True, read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    issued_by_name = serializers.CharField(source='issued_by.get_full_name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.get_full_name', read_only=True)

    class Meta:
        model = MaterialIssueSlip
        fields = [
            'id',
            'issue_number',
            'batch',
            'warehouse',
            'warehouse_name',
            'issued_date',
            'status',
            'issued_by',
            'issued_by_name',
            'received_by',
            'received_by_name',
            'notes',
            'created_at',
            'updated_at',
            'items',
        ]
        read_only_fields = ['id', 'issue_number', 'created_at', 'updated_at']


class ProductionStageLogSerializer(serializers.ModelSerializer):
    stage_display = serializers.CharField(source='get_stage_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    operator_name = serializers.CharField(source='operator.get_full_name', read_only=True)

    class Meta:
        model = ProductionStageLog
        fields = [
            'id',
            'batch',
            'stage',
            'stage_display',
            'started_at',
            'completed_at',
            'status',
            'status_display',
            'operator',
            'operator_name',
            'machine_equipment_name',
            'temperature_celsius',
            'humidity_percentage',
            'qc_parameters_json',
            'remarks',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class FinishedGoodsTransferSerializer(serializers.ModelSerializer):
    finished_product_name = serializers.CharField(source='finished_product.name', read_only=True)
    destination_warehouse_name = serializers.CharField(source='destination_warehouse.name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.get_full_name', read_only=True)
    voucher_number = serializers.CharField(source='accounting_voucher.voucher_number', read_only=True)

    class Meta:
        model = FinishedGoodsTransfer
        fields = [
            'id',
            'transfer_code',
            'batch',
            'finished_product',
            'finished_product_name',
            'destination_warehouse',
            'destination_warehouse_name',
            'transfer_quantity',
            'transfer_date',
            'qc_release_certificate_number',
            'is_received',
            'received_by',
            'received_by_name',
            'received_at',
            'created_by',
            'accounting_voucher',
            'voucher_number',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'transfer_code', 'created_at', 'updated_at']


# -----------------------------------------------------------------------------
# 4. ProductionBatch Serializers
# -----------------------------------------------------------------------------

class ProductionBatchListSerializer(serializers.ModelSerializer):
    finished_product_name = serializers.CharField(source='finished_product.name', read_only=True)
    finished_product_code = serializers.CharField(source='finished_product.unique_id', read_only=True)
    production_line_code = serializers.CharField(source='production_line.line_code', read_only=True)
    yield_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    supervisor_name = serializers.CharField(source='assigned_supervisor.get_full_name', read_only=True)

    class Meta:
        model = ProductionBatch
        fields = [
            'id',
            'batch_number',
            'production_plan',
            'bom',
            'finished_product',
            'finished_product_name',
            'finished_product_code',
            'production_line',
            'production_line_code',
            'source_warehouse',
            'destination_warehouse',
            'planned_quantity',
            'actual_produced_quantity',
            'rejected_quantity',
            'yield_percentage',
            'manufacturing_date',
            'expiry_date',
            'status',
            'current_stage',
            'assigned_supervisor',
            'supervisor_name',
            'created_at',
            'updated_at',
        ]


class ProductionBatchDetailSerializer(serializers.ModelSerializer):
    finished_product_details = ProductSerializer(source='finished_product', read_only=True)
    bom_details = BOMHeaderSerializer(source='bom', read_only=True)
    production_line_details = ProductionLineSerializer(source='production_line', read_only=True)
    source_warehouse_details = WarehouseSerializer(source='source_warehouse', read_only=True)
    destination_warehouse_details = WarehouseSerializer(source='destination_warehouse', read_only=True)
    supervisor_details = UserSerializer(source='assigned_supervisor', read_only=True)
    operators_details = UserSerializer(source='assigned_operators', many=True, read_only=True)
    yield_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)

    material_issue_slips = MaterialIssueSlipSerializer(many=True, read_only=True)
    stage_logs = ProductionStageLogSerializer(many=True, read_only=True)
    finished_goods_transfers = FinishedGoodsTransferSerializer(many=True, read_only=True)

    class Meta:
        model = ProductionBatch
        fields = [
            'id',
            'batch_number',
            'production_plan',
            'bom',
            'bom_details',
            'finished_product',
            'finished_product_details',
            'production_line',
            'production_line_details',
            'source_warehouse',
            'source_warehouse_details',
            'destination_warehouse',
            'destination_warehouse_details',
            'planned_quantity',
            'actual_produced_quantity',
            'rejected_quantity',
            'yield_percentage',
            'manufacturing_date',
            'expiry_date',
            'status',
            'current_stage',
            'assigned_supervisor',
            'supervisor_details',
            'assigned_operators',
            'operators_details',
            'notes',
            'created_by',
            'created_at',
            'updated_at',
            'material_issue_slips',
            'stage_logs',
            'finished_goods_transfers',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class ProductionBatchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionBatch
        fields = [
            'batch_number',
            'production_plan',
            'bom',
            'production_line',
            'source_warehouse',
            'destination_warehouse',
            'planned_quantity',
            'manufacturing_date',
            'expiry_date',
            'assigned_supervisor',
            'assigned_operators',
            'notes',
        ]


# -----------------------------------------------------------------------------
# 5. Action Payload Serializers
# -----------------------------------------------------------------------------

class BatchIssueMaterialsItemInputSerializer(serializers.Serializer):
    material_id = serializers.IntegerField(required=True)
    issued_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, required=True)
    batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    standard_bom_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, default=Decimal('0.0000'))


class BatchIssueMaterialsSerializer(serializers.Serializer):
    warehouse_id = serializers.IntegerField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = BatchIssueMaterialsItemInputSerializer(many=True, required=True)


class BatchAdvanceStageSerializer(serializers.Serializer):
    next_stage = serializers.ChoiceField(choices=ProductionBatch.StageChoice.choices, required=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class BatchRecordQCSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=ProductionStageLog.StageName.choices, required=True)
    status = serializers.ChoiceField(choices=ProductionStageLog.StageStatus.choices, default=ProductionStageLog.StageStatus.PASSED)
    machine_equipment_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    temperature_celsius = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    humidity_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    qc_parameters_json = serializers.DictField(required=False, default=dict)
    remarks = serializers.CharField(required=False, allow_blank=True, default='')
    completed = serializers.BooleanField(required=False, default=True)


class BatchCompleteTransferSerializer(serializers.Serializer):
    actual_produced_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=True)
    rejected_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, default=Decimal('0.000'))
    qc_release_certificate_number = serializers.CharField(max_length=100, required=True)
    destination_warehouse_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class BatchReconcileReturnItemInputSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(required=True)
    actual_consumed_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, required=True)
    wastage_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, default=Decimal('0.0000'))
    returned_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, default=Decimal('0.0000'))


class BatchReconcileReturnSerializer(serializers.Serializer):
    items = BatchReconcileReturnItemInputSerializer(many=True, required=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
