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
        return obj.orders.count()

    def get_total_delivered_orders(self, obj):
        return obj.orders.filter(status='DELIVERED').count()


class SimpleCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ('id', 'customer_code', 'name', 'proprietor_name', 'phone', 'customer_type', 'city', 'address')


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
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField(required=False, allow_null=True)
    batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    vat_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class CustomerOrderSerializer(serializers.ModelSerializer):
    customer = SimpleCustomerSerializer(read_only=True)
    items = CustomerOrderItemSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
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
            'notes',
            'cancellation_reason',
            'created_by_username',
            'items_count',
            'items',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('order_number', 'subtotal', 'tax_amount', 'total_amount', 'created_at', 'updated_at')

    def get_items_count(self, obj):
        return obj.items.count()


class CustomerOrderCreateSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    order_date = serializers.DateField(required=False)
    delivery_date = serializers.DateField(required=False, allow_null=True)
    discount_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0.00)
    discount_flat = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0.00)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False, default=PaymentMethod.CASH)
    shipping_address = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    items = CustomerOrderItemCreateSerializer(many=True)


class OrderCancelSerializer(serializers.Serializer):
    cancellation_reason = serializers.CharField(required=True, allow_blank=False)
