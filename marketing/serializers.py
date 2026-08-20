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
