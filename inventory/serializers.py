from rest_framework import serializers
from django.db.models import Sum
from inventory.models import (
    Category, Attribute, AttributeValue, Product,
    ProductAttributeValue, Warehouse, StockLevel, StockMovement
)


class CategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    product_count = serializers.SerializerMethodField()
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id',
            'name',
            'code',
            'parent',
            'parent_name',
            'description',
            'image_url',
            'display_order',
            'is_active',
            'product_count',
            'created_at',
            'updated_at',
            'subcategories',
        )

    def get_product_count(self, obj):
        return obj.products.count()

    def get_subcategories(self, obj):
        children = obj.subcategories.filter(is_active=True).order_by('display_order', 'name')
        return CategorySerializer(children, many=True).data


class SimpleAttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attribute
        fields = ('id', 'name', 'code')


class AttributeValueInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeValue
        fields = ('id', 'value', 'code', 'created_at')


class AttributeValueSerializer(serializers.ModelSerializer):
    attribute_details = SimpleAttributeSerializer(source='attribute', read_only=True)

    class Meta:
        model = AttributeValue
        fields = (
            'id',
            'value',
            'code',
            'created_at',
            'attribute',
            'attribute_details',
        )


class AttributeSerializer(serializers.ModelSerializer):
    values = AttributeValueInlineSerializer(many=True, read_only=True)

    class Meta:
        model = Attribute
        fields = (
            'id',
            'name',
            'code',
            'description',
            'is_active',
            'created_at',
            'updated_at',
            'values',
        )


class ProductAttributeValueSerializer(serializers.ModelSerializer):
    attribute_name = serializers.CharField(source='attribute_value.attribute.name', read_only=True)
    attribute_value_name = serializers.CharField(source='attribute_value.value', read_only=True)

    class Meta:
        model = ProductAttributeValue
        fields = ('id', 'product', 'attribute_value', 'attribute_name', 'attribute_value_name')


class SimpleCategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source='parent.name', read_only=True)

    class Meta:
        model = Category
        fields = ('id', 'name', 'code', 'parent', 'parent_name')


class ProductSerializer(serializers.ModelSerializer):
    category = SimpleCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category',
        write_only=True,
        required=False
    )
    attributes = ProductAttributeValueSerializer(source='product_attributes', many=True, read_only=True)
    attribute_value_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=AttributeValue.objects.all(),
        write_only=True,
        required=False
    )
    total_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            'id',
            'name',
            'generic_name',
            'unique_id',
            'description',
            'unit',
            'purchase_price',
            'selling_price',
            'vat_percentage',
            'min_stock_level',
            'max_stock_level',
            'drug_registration_number',
            'barcode',
            'requires_prescription',
            'storage_condition',
            'image_url',
            'is_active',
            'total_stock',
            'created_at',
            'updated_at',
            'category',
            'category_id',
            'attributes',
            'attribute_value_ids',
        )
        read_only_fields = ('unique_id', 'created_at', 'updated_at')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'categoryId': 'category_id',
                'category': 'category_id',
                'genericName': 'generic_name',
                'purchasePrice': 'purchase_price',
                'sellingPrice': 'selling_price',
                'vatPercentage': 'vat_percentage',
                'minStockLevel': 'min_stock_level',
                'maxStockLevel': 'max_stock_level',
                'drugRegistrationNumber': 'drug_registration_number',
                'requiresPrescription': 'requires_prescription',
                'storageCondition': 'storage_condition',
                'imageUrl': 'image_url',
                'isActive': 'is_active',
                'attributeValueIds': 'attribute_value_ids',
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)

    def get_total_stock(self, obj):
        result = obj.stock_levels.aggregate(total=Sum('quantity'))
        return result['total'] or 0

    def create(self, validated_data):
        attribute_values = validated_data.pop('attribute_value_ids', [])
        product = Product.objects.create(**validated_data)
        for val in attribute_values:
            ProductAttributeValue.objects.create(product=product, attribute_value=val)
        return product

    def update(self, instance, validated_data):
        attribute_values = validated_data.pop('attribute_value_ids', None)
        product = super().update(instance, validated_data)
        if attribute_values is not None:
            product.product_attributes.all().delete()
            for val in attribute_values:
                ProductAttributeValue.objects.create(product=product, attribute_value=val)
        return product


class SimpleProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ('id', 'name', 'generic_name', 'unique_id', 'unit')


class SimpleWarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ('id', 'name', 'code', 'address')


class WarehouseSerializer(serializers.ModelSerializer):
    total_products_count = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = '__all__'

    def get_total_products_count(self, obj):
        return obj.stock_levels.values('product').distinct().count()


class StockLevelSerializer(serializers.ModelSerializer):
    product = SimpleProductSerializer(read_only=True)
    warehouse = SimpleWarehouseSerializer(read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = StockLevel
        fields = (
            'id',
            'batch_number',
            'mfg_date',
            'expiry_date',
            'quantity',
            'reserved_quantity',
            'available_quantity',
            'rack_location',
            'created_at',
            'updated_at',
            'product',
            'warehouse',
        )


class StockMovementSerializer(serializers.ModelSerializer):
    product = SimpleProductSerializer(read_only=True)
    warehouse = SimpleWarehouseSerializer(read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = StockMovement
        fields = (
            'id',
            'batch_number',
            'movement_type',
            'quantity',
            'previous_stock',
            'new_stock',
            'reference_no',
            'notes',
            'created_by_username',
            'created_at',
            'product',
            'warehouse',
        )
        read_only_fields = ('previous_stock', 'new_stock', 'created_by', 'created_at')


class StockMovementCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(help_text='Product ID (e.g. 4)')
    warehouse_id = serializers.IntegerField(help_text='Warehouse ID (e.g. 2)')
    batch_number = serializers.CharField(max_length=100, help_text='Batch Number (e.g. BATCH-2026-A1)')
    movement_type = serializers.ChoiceField(
        choices=[
            ('IN', 'Inflow (Purchase / Production)'),
            ('OUT', 'Outflow (Sales / Transfer)'),
            ('ADJUSTMENT', 'Stock Adjustment'),
            ('RETURN', 'Customer / Vendor Return'),
            ('DAMAGE', 'Damaged / Expired Write-off')
        ],
        help_text='Type of movement (IN, OUT, ADJUSTMENT, RETURN, DAMAGE)'
    )
    quantity = serializers.IntegerField(min_value=1, help_text='Quantity moved (positive integer)')
    mfg_date = serializers.DateField(required=False, allow_null=True, help_text='Manufacturing Date (YYYY-MM-DD)')
    expiry_date = serializers.DateField(required=False, allow_null=True, help_text='Expiry Date (YYYY-MM-DD)')
    rack_location = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text='Warehouse Rack / Bin location')
    reference_no = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text='Invoice / GRN / Challan Number')
    notes = serializers.CharField(required=False, allow_blank=True, help_text='Optional remarks')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'productId': 'product_id',
                'warehouseId': 'warehouse_id',
                'batchNumber': 'batch_number',
                'movementType': 'movement_type',
                'mfgDate': 'mfg_date',
                'expiryDate': 'expiry_date',
                'rackLocation': 'rack_location',
                'referenceNo': 'reference_no'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class StockAdjustmentSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(help_text='Product ID')
    warehouse_id = serializers.IntegerField(help_text='Warehouse ID')
    batch_number = serializers.CharField(max_length=100, help_text='Batch Number')
    new_quantity = serializers.IntegerField(min_value=0, help_text='New physical count')
    reference_no = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text='Audit sheet number')
    notes = serializers.CharField(required=False, allow_blank=True, help_text='Reason for audit adjustment')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'productId': 'product_id',
                'warehouseId': 'warehouse_id',
                'batchNumber': 'batch_number',
                'newQuantity': 'new_quantity',
                'referenceNo': 'reference_no'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)
