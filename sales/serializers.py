from rest_framework import serializers
from sales.models import Customer, CustomerOrder, CustomerOrderItem, PaymentMethod
from inventory.serializers import SimpleProductSerializer, SimpleWarehouseSerializer


class CustomerSerializer(serializers.ModelSerializer):
    total_orders = serializers.SerializerMethodField(read_only=True)
    total_delivered_orders = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Customer
        fields = (
            'id',
            'customer_code',
            'name',
            'proprietor_name',
            'phone',
            'email',
            'drug_license_no',
            'drug_license_expiry_date',
            'trade_license_no',
            'customer_type',
            'address',
            'city',
            'is_active',
            'total_orders',
            'total_delivered_orders',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('customer_code', 'created_at', 'updated_at')

    def get_total_orders(self, obj):
        # orders is prefetched by the viewset; .count()/.filter() on the manager
        # would each cost an extra query per customer.
        return len(obj.orders.all())

    def get_total_delivered_orders(self, obj):
        return sum(1 for order in obj.orders.all() if order.status == 'DELIVERED')


class SimpleCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        # drug_license_no and its expiry are printed on a pharmaceutical
        # invoice, so they must travel with every embedded customer.
        fields = (
            'id', 'customer_code', 'name', 'proprietor_name', 'phone',
            'customer_type', 'city', 'address',
            'drug_license_no', 'drug_license_expiry_date',
        )


class CustomerOrderItemSerializer(serializers.ModelSerializer):
    product = SimpleProductSerializer(read_only=True)
    warehouse = SimpleWarehouseSerializer(read_only=True)

    class Meta:
        model = CustomerOrderItem
        fields = (
            'id',
            'product',
            'warehouse',
            'batch_number',
            'quantity',
            'unit_price',
            'vat_percentage',
            'discount_percentage',
            'total_price',
        )


class CustomerOrderItemCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(help_text='Product ID (e.g. 4)')
    warehouse_id = serializers.IntegerField(required=False, allow_null=True, help_text='Warehouse ID (e.g. 2)')
    batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text='Specific Batch Number (e.g. BATCH-2026-A1)')
    quantity = serializers.IntegerField(min_value=1, help_text='Quantity ordered (positive integer)')
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, help_text='Optional unit price override')
    vat_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0.00, help_text='VAT percentage (e.g. 0.00)')
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0.00, help_text='Discount percentage (e.g. 0.00)')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'productId': 'product_id',
                'warehouseId': 'warehouse_id',
                'batchNumber': 'batch_number',
                'unitPrice': 'unit_price',
                'vatPercentage': 'vat_percentage',
                'discountPercentage': 'discount_percentage'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class CustomerOrderSerializer(serializers.ModelSerializer):
    customer = SimpleCustomerSerializer(read_only=True)
    delivery_branch = SimpleWarehouseSerializer(read_only=True)
    items = CustomerOrderItemSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    items_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CustomerOrder
        fields = (
            'id',
            'order_number',
            'customer',
            'order_date',
            'delivery_date',
            'status',
            'payment_status',
            'payment_method',
            'subtotal',
            'discount_percentage',
            'discount_flat',
            'tax_amount',
            'total_amount',
            'paid_amount',
            'shipping_address',
            'is_branch_booking',
            'delivery_branch',
            'booking_reference_number',
            'booking_notes',
            'notes',
            'cancellation_reason',
            'created_by_username',
            'created_by_name',
            'items_count',
            'items',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('order_number', 'booking_reference_number', 'subtotal', 'tax_amount', 'total_amount', 'created_at', 'updated_at')

    def get_items_count(self, obj):
        return len(obj.items.all())


class CustomerOrderCreateSerializer(serializers.Serializer):
    as_draft = serializers.BooleanField(
        required=False, default=False,
        help_text='Save as an editable draft. A draft reserves no stock.'
    )
    customer_id = serializers.IntegerField(help_text='Customer / Pharmacy ID (e.g. 1)')
    order_date = serializers.DateField(required=False, help_text='Order Date (YYYY-MM-DD)')
    delivery_date = serializers.DateField(required=False, allow_null=True, help_text='Expected Delivery Date (YYYY-MM-DD)')
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0.00, help_text='Overall order discount percentage')
    discount_flat = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0.00, help_text='Overall order discount flat amount')
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False, default=PaymentMethod.CASH, help_text='Payment method (CASH, BANK_TRANSFER, CHEQUE, BKASH, NAGAD)')
    shipping_address = serializers.CharField(required=False, allow_blank=True, help_text='Delivery / Pharmacy branch address')
    is_branch_booking = serializers.BooleanField(required=False, default=False, help_text='True if booking for fulfillment by another branch / depot')
    delivery_branch_id = serializers.IntegerField(required=False, allow_null=True, help_text='Destination branch warehouse ID')
    booking_notes = serializers.CharField(required=False, allow_blank=True, help_text='Special instructions for destination branch')
    notes = serializers.CharField(required=False, allow_blank=True, help_text='Special delivery instructions')
    items = CustomerOrderItemCreateSerializer(many=True, help_text='List of ordered products, batches, and quantities')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'customerId': 'customer_id',
                'orderDate': 'order_date',
                'deliveryDate': 'delivery_date',
                'discountPercentage': 'discount_percentage',
                'discountFlat': 'discount_flat',
                'paymentMethod': 'payment_method',
                'shippingAddress': 'shipping_address',
                'isBranchBooking': 'is_branch_booking',
                'deliveryBranchId': 'delivery_branch_id',
                'bookingNotes': 'booking_notes'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class OrderCancelSerializer(serializers.Serializer):
    cancellation_reason = serializers.CharField(required=True, allow_blank=False, help_text='Reason for order cancellation')

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if 'cancellationReason' in data and 'cancellation_reason' not in data:
                data['cancellation_reason'] = data['cancellationReason']
        return super().to_internal_value(data)


class DraftUpdateSerializer(serializers.Serializer):
    """Every field optional: a draft is edited a piece at a time."""
    items = serializers.ListField(child=serializers.DictField(), required=False)
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    discount_flat = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    payment_method = serializers.CharField(required=False)
    shipping_address = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    delivery_date = serializers.DateField(required=False, allow_null=True)
