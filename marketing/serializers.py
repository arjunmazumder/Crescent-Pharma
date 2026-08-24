from django.contrib.auth import get_user_model
from rest_framework import serializers
from marketing.models import SalesTarget, ProductTargetItem, PeriodType, TargetType, TargetStatus

User = get_user_model()


class SimpleUserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.role_name', read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'employee_id', 'email', 'contact', 'role_name')


class ProductTargetItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unique_id = serializers.CharField(source='product.unique_id', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = ProductTargetItem
        fields = (
            'id',
            'product',
            'product_name',
            'product_unique_id',
            'unit',
            'target_quantity',
            'unit_price',
            'target_amount',
        )
        read_only_fields = ('target_amount',)


class ProductTargetItemCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    target_quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)


class SalesTargetSerializer(serializers.ModelSerializer):
    product_items = ProductTargetItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField(read_only=True)
    assigned_to = SimpleUserSerializer(read_only=True)
    assigned_by = SimpleUserSerializer(read_only=True)

    class Meta:
        model = SalesTarget
        fields = (
            'id',
            'title',
            'target_code',
            'period_type',
            'start_date',
            'end_date',
            'target_type',
            'total_target_amount',
            'status',
            'territory_name',
            'notes',
            'items_count',
            'product_items',
            'assigned_to',
            'assigned_by',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('target_code', 'created_at', 'updated_at')

    def get_items_count(self, obj):
        return obj.product_items.count()


class SalesTargetCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    assigned_to_id = serializers.IntegerField()
    period_type = serializers.ChoiceField(choices=PeriodType.choices, default=PeriodType.MONTHLY)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    target_type = serializers.ChoiceField(choices=TargetType.choices, default=TargetType.HYBRID)
    total_target_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=0.00)
    status = serializers.ChoiceField(choices=TargetStatus.choices, required=False, default=TargetStatus.ACTIVE)
    territory_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    items = ProductTargetItemCreateSerializer(many=True, required=False)

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({"end_date": "End date must be on or after start date."})
        return attrs


# -----------------------------------------------------------------------------
# Doctor & Sample Distribution Serializers
# -----------------------------------------------------------------------------

from marketing.models import Doctor, DoctorSampleDistribution, DoctorSampleItem, VisitingShift
from inventory.serializers import SimpleProductSerializer, SimpleWarehouseSerializer


class DoctorSerializer(serializers.ModelSerializer):
    assigned_mpo_details = SimpleUserSerializer(source='assigned_mpo', read_only=True)
    total_distributions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Doctor
        fields = (
            'id',
            'doctor_code',
            'name',
            'degrees',
            'specialty',
            'bmdc_reg_number',
            'chamber_or_hospital_name',
            'address',
            'territory_name',
            'phone',
            'email',
            'visiting_shift',
            'assigned_mpo',
            'assigned_mpo_details',
            'is_active',
            'total_distributions',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('doctor_code', 'created_at', 'updated_at')

    def get_total_distributions(self, obj):
        return obj.sample_distributions.count()


class DoctorSampleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unique_id = serializers.CharField(source='product.unique_id', read_only=True)

    class Meta:
        model = DoctorSampleItem
        fields = (
            'id',
            'product',
            'product_name',
            'product_unique_id',
            'batch_number',
            'quantity',
            'unit',
        )


class DoctorSampleDistributionSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source='doctor.name', read_only=True)
    doctor_code = serializers.CharField(source='doctor.doctor_code', read_only=True)
    doctor_specialty = serializers.CharField(source='doctor.specialty', read_only=True)
    doctor_chamber = serializers.CharField(source='doctor.chamber_or_hospital_name', read_only=True)
    mpo_username = serializers.CharField(source='mpo.username', read_only=True)
    source_warehouse_name = serializers.CharField(source='source_warehouse.name', read_only=True)
    items = DoctorSampleItemSerializer(many=True, read_only=True)

    class Meta:
        model = DoctorSampleDistribution
        fields = (
            'id',
            'distribution_number',
            'doctor',
            'doctor_code',
            'doctor_name',
            'doctor_specialty',
            'doctor_chamber',
            'mpo',
            'mpo_username',
            'source_warehouse',
            'source_warehouse_name',
            'distribution_date',
            'total_items_count',
            'notes',
            'items',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('distribution_number', 'total_items_count', 'created_at', 'updated_at')


class DoctorSampleItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(help_text="Product / Medicine ID")
    batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="", help_text="Batch Number")
    quantity = serializers.IntegerField(min_value=1, default=1, help_text="Quantity distributed")
    unit = serializers.CharField(max_length=50, required=False, default="Strips", help_text="Unit (e.g. Strips, Boxes)")

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'productId': 'product_id',
                'batchNumber': 'batch_number'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)


class DoctorSampleDistributionCreateSerializer(serializers.Serializer):
    doctor_id = serializers.IntegerField(help_text="Doctor ID")
    source_warehouse_id = serializers.IntegerField(required=False, allow_null=True, help_text="Warehouse ID from which samples are issued")
    distribution_date = serializers.DateField(required=False, help_text="Distribution Date (YYYY-MM-DD)")
    notes = serializers.CharField(required=False, allow_blank=True, default="", help_text="Visit notes / feedback")
    items = DoctorSampleItemInputSerializer(many=True, help_text="List of sample items")

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            mapping = {
                'doctorId': 'doctor_id',
                'sourceWarehouseId': 'source_warehouse_id',
                'distributionDate': 'distribution_date'
            }
            for camel, snake in mapping.items():
                if camel in data and snake not in data:
                    data[snake] = data[camel]
        return super().to_internal_value(data)

