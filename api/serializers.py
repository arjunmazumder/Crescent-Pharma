from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from core.models import Lookup, Role, AuditLog
from hr.models import (
    Holiday, WeekendConfig, OfficeLocation, Attendance,
    SalaryStructure, Payroll, PayrollApproval, Loan, TourAllowance,
    LeaveRequest
)
from inventory.models import (
    Category, Attribute, AttributeValue, Product,
    ProductAttributeValue, Warehouse, StockLevel, StockMovement
)
from sales.models import (
    Customer, CustomerOrder, CustomerOrderItem,
    CustomerType, OrderStatus, PaymentStatus, PaymentMethod
)
from django.db.models import Sum
User = get_user_model()

class PermissionSerializer(serializers.ModelSerializer):
    app_label = serializers.CharField(source='content_type.app_label', read_only=True)
    model = serializers.CharField(source='content_type.model', read_only=True)

    class Meta:
        model = Permission
        fields = ('id', 'name', 'codename', 'app_label', 'model')

class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), required=False
    )
    permissions_details = PermissionSerializer(source='permissions', many=True, read_only=True)

    class Meta:
        model = Role
        fields = ('id', 'role_name', 'permissions', 'permissions_details', 'is_active', 'created_at', 'updated_at')

class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    user_permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), required=False
    )
    role_permissions = PermissionSerializer(source='role.permissions', many=True, read_only=True)
    extra_permissions_details = PermissionSerializer(source='user_permissions', many=True, read_only=True)
    effective_permissions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'password', 'email', 'is_superuser', 'is_staff',
            'employee_id', 'role', 'role_name',
            'user_permissions', 'role_permissions', 'extra_permissions_details',
            'effective_permissions', 'contact', 'address', 'date_of_birth',
            'joining_date', 'nid_number', 'morning_shift_start', 'morning_shift_end',
            'evening_shift_start', 'evening_shift_end',
            'location_bounded_attendance'
        )
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'employee_id': {'required': False, 'allow_blank': True, 'allow_null': True}
        }
    
    def get_effective_permissions(self, obj):
        return obj.get_effective_permissions()
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user_permissions = validated_data.pop('user_permissions', None)
        user = super().create(validated_data)
        
        # If password is provided, set it; otherwise set a secure default password
        if password:
            user.set_password(password)
        else:
            user.set_password('Crescent@123') # Default fallback password
        user.save()
        
        if user_permissions is not None:
            user.user_permissions.set(user_permissions)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user_permissions = validated_data.pop('user_permissions', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        if user_permissions is not None:
            user.user_permissions.set(user_permissions)
        return user

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        return {
            'message': "Login successful",
            'access': data['access'],
            'refresh': data['refresh'],
            'data': UserSerializer(self.user).data
        }

class LookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lookup
        fields = '__all__'

class AttendanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = Attendance
        fields = '__all__'

class PayrollSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    generated_by_username = serializers.CharField(source='generated_by.username', read_only=True)

    class Meta:
        model = Payroll
        fields = '__all__'

class LoanSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = Loan
        fields = '__all__'

class TourAllowanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)

    class Meta:
        model = TourAllowance
        fields = '__all__'

class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = '__all__'

class WeekendConfigSerializer(serializers.ModelSerializer):
    day_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WeekendConfig
        fields = ('id', 'day_of_week', 'day_name', 'is_active')

    def get_day_name(self, obj):
        days = {
            0: "Monday",
            1: "Tuesday",
            2: "Wednesday",
            3: "Thursday",
            4: "Friday",
            5: "Saturday",
            6: "Sunday"
        }
        return days.get(obj.day_of_week, "")

class OfficeLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficeLocation
        fields = '__all__'

class SalaryStructureSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = SalaryStructure
        fields = '__all__'

class PayrollApprovalSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.name', read_only=True)
    approver_name = serializers.CharField(source='approver.username', read_only=True)

    class Meta:
        model = PayrollApproval
        fields = '__all__'


class LeaveRequestSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    employee_id = serializers.CharField(source='user.employee_id', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ('total_days', 'status', 'approved_by', 'applied_at', 'approved_at')
        extra_kwargs = {
            'user': {'required': False}
        }

    def validate(self, attrs):
        start_date = attrs.get('start_date') or (self.instance.start_date if self.instance else None)
        end_date = attrs.get('end_date') or (self.instance.end_date if self.instance else None)

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({"end_date": "End date must be on or after start date."})

        return attrs


# =======================================================
# PRODUCTS & INVENTORY SERIALIZERS
# =======================================================

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
            if 'category' in data and not isinstance(data['category'], dict):
                data['category_id'] = data['category']
            elif 'categoryId' in data and not isinstance(data['categoryId'], dict):
                data['category_id'] = data['categoryId']
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
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    batch_number = serializers.CharField(max_length=100)
    movement_type = serializers.ChoiceField(choices=[
        ('IN', 'Inflow (Purchase / Production)'),
        ('OUT', 'Outflow (Sales / Transfer)'),
        ('ADJUSTMENT', 'Stock Adjustment'),
        ('RETURN', 'Customer / Vendor Return'),
        ('DAMAGE', 'Damaged / Expired Write-off')
    ])
    quantity = serializers.IntegerField()
    mfg_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    rack_location = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reference_no = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class StockAdjustmentSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    batch_number = serializers.CharField(max_length=100)
    new_quantity = serializers.IntegerField(min_value=0)
    reference_no = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


# =======================================================
# CUSTOMER & SALES ORDER SERIALIZERS
# =======================================================

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



