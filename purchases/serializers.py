from decimal import Decimal
from rest_framework import serializers
from purchases.models import (
    Supplier, SupplierType, SupplyCategory, AuditStatus, IncotermsChoice,
    PurchaseOrder, PurchaseOrderItem, OrderType, OrderStatus,
    LetterOfCredit, LetterOfCreditType, LetterOfCreditStatus, LCDocument,
    LetterOfCreditDocumentType, LCLandingCost,
    GoodsReceivedNote, GoodsReceivedNoteItem, GoodsReceivedNoteStatus
)
from inventory.models import Product, Warehouse
from inventory.serializers import SimpleProductSerializer, WarehouseSerializer
from accounting.models import AccountHead


# -----------------------------------------------------------------------------
# 1. Supplier Serializers
# -----------------------------------------------------------------------------

class SimpleSupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = (
            'id',
            'supplier_code',
            'company_name',
            'supplier_type',
            'supply_category',
            'country',
            'currency',
            'phone_number',
            'email_address',
            'is_active',
        )


class SupplierSerializer(serializers.ModelSerializer):
    total_orders_count = serializers.SerializerMethodField()
    active_lcs_count = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ('id', 'supplier_code', 'created_at', 'updated_at')

    def get_total_orders_count(self, obj):
        return obj.purchase_orders.count()

    def get_active_lcs_count(self, obj):
        return obj.letters_of_credit.exclude(status__in=[LetterOfCreditStatus.CLOSED, LetterOfCreditStatus.CANCELLED]).count()


# -----------------------------------------------------------------------------
# 2. Purchase Order & Item Serializers
# -----------------------------------------------------------------------------

class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_details = SimpleProductSerializer(source='product', read_only=True)
    remaining_quantity_to_receive = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    is_fully_received = serializers.BooleanField(read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = (
            'id',
            'purchase_order',
            'product',
            'product_details',
            'ordered_quantity',
            'received_quantity',
            'remaining_quantity_to_receive',
            'is_fully_received',
            'unit_price_in_order_currency',
            'total_price_in_order_currency',
            'total_price_in_bdt',
            'technical_specifications',
        )
        read_only_fields = ('id', 'received_quantity', 'total_price_in_order_currency', 'total_price_in_bdt')


class PurchaseOrderItemCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=True)
    ordered_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, required=True)
    unit_price_in_order_currency = serializers.DecimalField(max_digits=14, decimal_places=4, required=False)
    technical_specifications = serializers.CharField(required=False, allow_blank=True, default="")


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_details = SimpleSupplierSerializer(source='supplier', read_only=True)
    delivery_warehouse_details = WarehouseSerializer(source='delivery_warehouse', read_only=True)
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            'id',
            'purchase_order_number',
            'supplier',
            'order_date',
            'expected_delivery_date',
            'delivery_warehouse',
            'order_type',
            'status',
            'currency',
            'exchange_rate',
            'total_amount_in_foreign_currency',
            'total_amount_in_bdt',
            'payment_terms',
            'proforma_invoice_number',
            'proforma_invoice_date',
            'dgda_blocklist_number',
            'incoterm',
            'special_notes',
            'cancellation_reason',
            'created_by',
            'created_by_username',
            'approved_by',
            'approved_by_username',
            'approved_at',
            'created_at',
            'updated_at',
            'delivery_warehouse_details',
            'supplier_details',
            'items',
        )
        read_only_fields = (
            'id',
            'purchase_order_number',
            'status',
            'total_amount_in_foreign_currency',
            'total_amount_in_bdt',
            'created_by',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        )


class PurchaseOrderCreateSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(required=True)
    order_date = serializers.DateField(required=False)
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    delivery_warehouse_id = serializers.IntegerField(required=False, allow_null=True)
    order_type = serializers.ChoiceField(choices=OrderType.choices, default=OrderType.RAW_MATERIAL)
    currency = serializers.CharField(max_length=10, default='BDT')
    exchange_rate = serializers.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1.0000'))
    payment_terms = serializers.CharField(required=False, allow_blank=True, default="")
    proforma_invoice_number = serializers.CharField(required=False, allow_blank=True, default="")
    proforma_invoice_date = serializers.DateField(required=False, allow_null=True)
    dgda_blocklist_number = serializers.CharField(required=False, allow_blank=True, default="")
    incoterm = serializers.CharField(required=False, allow_blank=True, default="")
    special_notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = PurchaseOrderItemCreateSerializer(many=True, required=True)


class PurchaseOrderCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)


# -----------------------------------------------------------------------------
# 3. Letter of Credit & Landed Cost Serializers
# -----------------------------------------------------------------------------

class LCDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)

    class Meta:
        model = LCDocument
        fields = (
            'id',
            'letter_of_credit',
            'document_type',
            'document_title',
            'document_file_url',
            'uploaded_by',
            'uploaded_by_username',
            'uploaded_at',
        )
        read_only_fields = ('id', 'uploaded_by', 'uploaded_at')


class LCLandingCostSerializer(serializers.ModelSerializer):
    class Meta:
        model = LCLandingCost
        fields = '__all__'
        read_only_fields = ('id', 'total_landed_cost', 'is_finalized', 'finalized_at', 'finalized_by')


class LetterOfCreditSerializer(serializers.ModelSerializer):
    supplier_details = SimpleSupplierSerializer(source='supplier', read_only=True)
    issuing_bank_name = serializers.CharField(source='issuing_bank_account.name', read_only=True)
    documents = LCDocumentSerializer(many=True, read_only=True)
    landing_cost = LCLandingCostSerializer(read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = LetterOfCredit
        fields = (
            'id',
            'letter_of_credit_number',
            'supplier',
            'purchase_order',
            'issuing_bank_account',
            'issuing_bank_name',
            'issuing_branch_name',
            'letter_of_credit_type',
            'incoterm',
            'currency',
            'total_amount_in_foreign_currency',
            'exchange_rate_to_bdt',
            'total_amount_in_bdt',
            'bank_margin_percentage',
            'bank_margin_amount_in_bdt',
            'lc_opening_date',
            'lc_expiry_date',
            'latest_shipment_date',
            'status',
            'harmonized_system_code',
            'port_of_loading',
            'port_of_discharge',
            'clearing_and_forwarding_agent_name',
            'insurance_company_name',
            'insurance_cover_note_number',
            'margin_voucher',
            'special_notes',
            'created_by',
            'created_by_username',
            'created_at',
            'updated_at',
            'landing_cost',
            'supplier_details',
            'documents',
        )
        read_only_fields = (
            'id',
            'letter_of_credit_number',
            'total_amount_in_bdt',
            'bank_margin_amount_in_bdt',
            'margin_voucher',
            'created_by',
            'created_at',
            'updated_at',
        )


class LetterOfCreditCreateSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(required=True)
    purchase_order_id = serializers.IntegerField(required=False, allow_null=True)
    issuing_bank_account_id = serializers.IntegerField(required=True)
    issuing_branch_name = serializers.CharField(max_length=150, required=True)
    letter_of_credit_type = serializers.ChoiceField(choices=LetterOfCreditType.choices, default=LetterOfCreditType.SIGHT)
    incoterm = serializers.ChoiceField(choices=IncotermsChoice.choices, default=IncotermsChoice.CFR)
    currency = serializers.CharField(max_length=10, default='USD')
    total_amount_in_foreign_currency = serializers.DecimalField(max_digits=14, decimal_places=2, required=True)
    exchange_rate_to_bdt = serializers.DecimalField(max_digits=10, decimal_places=4, required=True)
    bank_margin_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    lc_opening_date = serializers.DateField(required=True)
    lc_expiry_date = serializers.DateField(required=True)
    latest_shipment_date = serializers.DateField(required=False, allow_null=True)
    harmonized_system_code = serializers.CharField(required=False, allow_blank=True, default="")
    port_of_loading = serializers.CharField(max_length=100, required=True)
    port_of_discharge = serializers.CharField(max_length=100, default="Chattogram Sea Port / Dhaka Airport")
    clearing_and_forwarding_agent_name = serializers.CharField(required=False, allow_blank=True, default="")
    insurance_company_name = serializers.CharField(required=False, allow_blank=True, default="")
    insurance_cover_note_number = serializers.CharField(required=False, allow_blank=True, default="")
    special_notes = serializers.CharField(required=False, allow_blank=True, default="")
    post_margin_voucher = serializers.BooleanField(default=True)


class LCStageAdvanceSerializer(serializers.Serializer):
    next_status = serializers.ChoiceField(choices=LetterOfCreditStatus.choices)


# -----------------------------------------------------------------------------
# 4. Goods Received Note (GRN) Serializers
# -----------------------------------------------------------------------------

class GoodsReceivedNoteItemSerializer(serializers.ModelSerializer):
    product_details = SimpleProductSerializer(source='product', read_only=True)

    class Meta:
        model = GoodsReceivedNoteItem
        fields = '__all__'
        read_only_fields = ('id', 'total_landed_cost')


class GoodsReceivedNoteItemCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=True)
    purchase_order_item_id = serializers.IntegerField(required=False, allow_null=True)
    batch_number = serializers.CharField(max_length=100, required=True)
    manufacturing_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    challan_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, required=True)
    received_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, required=False)
    accepted_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, required=False)
    rejected_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    unit_landed_cost = serializers.DecimalField(max_digits=14, decimal_places=4, required=False)
    qc_remarks = serializers.CharField(required=False, allow_blank=True, default="")


class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
    receiving_warehouse_details = WarehouseSerializer(source='receiving_warehouse', read_only=True)
    items = GoodsReceivedNoteItemSerializer(many=True, read_only=True)
    purchase_order_number = serializers.CharField(source='purchase_order.purchase_order_number', read_only=True)
    letter_of_credit_number = serializers.CharField(source='letter_of_credit.letter_of_credit_number', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    accounting_voucher_number = serializers.CharField(source='accounting_voucher.voucher_number', read_only=True)

    class Meta:
        model = GoodsReceivedNote
        fields = (
            'id',
            'goods_received_note_number',
            'purchase_order',
            'purchase_order_number',
            'letter_of_credit',
            'letter_of_credit_number',
            'receiving_warehouse',
            'received_date',
            'bill_of_entry_number',
            'challan_number',
            'status',
            'accounting_voucher',
            'accounting_voucher_number',
            'special_notes',
            'created_by',
            'created_by_username',
            'approved_by',
            'approved_by_username',
            'approved_at',
            'created_at',
            'updated_at',
            'receiving_warehouse_details',
            'items',
        )
        read_only_fields = (
            'id',
            'goods_received_note_number',
            'status',
            'accounting_voucher',
            'created_by',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        )


class GoodsReceivedNoteCreateSerializer(serializers.Serializer):
    receiving_warehouse_id = serializers.IntegerField(required=True)
    purchase_order_id = serializers.IntegerField(required=False, allow_null=True)
    letter_of_credit_id = serializers.IntegerField(required=False, allow_null=True)
    received_date = serializers.DateField(required=False)
    bill_of_entry_number = serializers.CharField(required=False, allow_blank=True, default="")
    challan_number = serializers.CharField(required=False, allow_blank=True, default="")
    special_notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = GoodsReceivedNoteItemCreateSerializer(many=True, required=True)
