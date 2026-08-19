from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema
from inventory.models import (
    Category, Attribute, AttributeValue, Product,
    Warehouse, StockLevel, StockMovement
)
from inventory.services import InventoryService
from inventory.serializers import (
    CategorySerializer, AttributeSerializer, AttributeValueSerializer,
    ProductSerializer, WarehouseSerializer, StockLevelSerializer,
    StockMovementSerializer, StockMovementCreateSerializer,
    StockAdjustmentSerializer
)


@extend_schema(tags=['Products & Categories'])
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().select_related('parent').prefetch_related('subcategories', 'products').order_by('display_order', 'name')
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['parent', 'is_active']
    ordering_fields = ['id', 'display_order', 'name', 'created_at']
    ordering = ['display_order', 'name']

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Root Categories with Nested Subcategories Tree'
    )
    @action(detail=False, methods=['get'], url_path='tree')
    def tree(self, request):
        roots = self.get_queryset().filter(parent__isnull=True)
        queryset = self.filter_queryset(roots)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema(tags=['Products & Categories'])
class AttributeViewSet(viewsets.ModelViewSet):
    queryset = Attribute.objects.all().prefetch_related('values').order_by('name')
    serializer_class = AttributeSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'name', 'created_at']
    ordering = ['name']


@extend_schema(tags=['Products & Categories'])
class AttributeValueViewSet(viewsets.ModelViewSet):
    queryset = AttributeValue.objects.all().select_related('attribute').order_by('attribute__name', 'value')
    serializer_class = AttributeValueSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['value', 'code', 'attribute__name']
    filterset_fields = ['attribute']
    ordering_fields = ['id', 'value', 'created_at']
    ordering = ['attribute__name', 'value']


@extend_schema(tags=['Products & Categories'])
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().select_related('category').prefetch_related(
        'product_attributes__attribute_value__attribute',
        'stock_levels'
    ).order_by('-id')
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'generic_name', 'unique_id', 'barcode', 'drug_registration_number', 'description']
    filterset_fields = ['category', 'unit', 'is_active', 'requires_prescription']
    ordering_fields = ['id', 'name', 'selling_price', 'purchase_price', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Low Stock Products'
    )
    @action(detail=False, methods=['get'], url_path='low-stock')
    def low_stock(self, request):
        low_stock_items = InventoryService.get_low_stock_products()
        results = []
        for item in low_stock_items:
            data = ProductSerializer(item['product']).data
            data['totalStock'] = item['total_stock']
            data['minStockLevel'] = item['min_stock_level']
            data['deficit'] = item['deficit']
            results.append(data)
        return Response({
            'count': len(results),
            'results': results
        }, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Products & Categories'],
        summary='Get Expiring Products / Batches'
    )
    @action(detail=False, methods=['get'], url_path='expiring')
    def expiring(self, request):
        days = int(request.query_params.get('days', 90))
        expiring_levels = InventoryService.get_expiring_batches(days=days)
        return Response({
            'daysThreshold': days,
            'count': expiring_levels.count(),
            'results': StockLevelSerializer(expiring_levels, many=True).data
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['Inventory & Stock Management'])
class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all().prefetch_related('stock_levels').order_by('name')
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code', 'address', 'contact_number']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'name', 'code', 'created_at']
    ordering = ['name']


@extend_schema(tags=['Inventory & Stock Management'])
class StockLevelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockLevel.objects.all().select_related('product', 'warehouse').order_by('expiry_date', 'batch_number')
    serializer_class = StockLevelSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['product__name', 'product__generic_name', 'product__unique_id', 'batch_number', 'warehouse__name']
    filterset_fields = ['product', 'warehouse', 'batch_number']
    ordering_fields = ['id', 'expiry_date', 'quantity', 'updated_at']
    ordering = ['expiry_date', 'batch_number']


@extend_schema(tags=['Inventory & Stock Management'])
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.all().select_related('product', 'warehouse', 'created_by').order_by('-created_at')
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['product__name', 'product__unique_id', 'batch_number', 'reference_no', 'notes']
    filterset_fields = ['product', 'warehouse', 'movement_type', 'batch_number']
    ordering_fields = ['id', 'created_at', 'quantity']
    ordering = ['-created_at']

    @extend_schema(
        tags=['Inventory & Stock Management'],
        summary='Record Stock Movement'
    )
    @action(detail=False, methods=['post'], url_path='record-movement')
    def record_movement(self, request):
        serializer = StockMovementCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            stock_level, movement = InventoryService.record_stock_movement(
                product=product,
                warehouse=warehouse,
                batch_number=data['batch_number'],
                movement_type=data['movement_type'],
                quantity=data['quantity'],
                mfg_date=data.get('mfg_date'),
                expiry_date=data.get('expiry_date'),
                rack_location=data.get('rack_location'),
                reference_no=data.get('reference_no', ''),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response({
                'message': f"Stock movement recorded successfully for {product.name}.",
                'movement': StockMovementSerializer(movement).data,
                'currentStock': StockLevelSerializer(stock_level).data
            }, status=status.HTTP_200_OK)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Warehouse not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Inventory & Stock Management'],
        summary='Adjust Stock Count'
    )
    @action(detail=False, methods=['post'], url_path='adjust')
    def adjust_stock(self, request):
        serializer = StockAdjustmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            stock_level, movement = InventoryService.adjust_stock(
                product=product,
                warehouse=warehouse,
                batch_number=data['batch_number'],
                new_quantity=data['new_quantity'],
                reference_no=data.get('reference_no', ''),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response({
                'message': f"Stock adjusted successfully for {product.name} to {data['new_quantity']}.",
                'movement': StockMovementSerializer(movement).data,
                'currentStock': StockLevelSerializer(stock_level).data
            }, status=status.HTTP_200_OK)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Warehouse not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
