from decimal import Decimal
from django.utils.dateparse import parse_date
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter
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
        summary='Record Stock Movement (Inflow, Outflow, Return, Damage)',
        description='Atomically records stock movement (IN, OUT, ADJUSTMENT, RETURN, DAMAGE) and updates the physical stock level in the warehouse. Inflow (IN) requires mfgDate and expiryDate.',
        request=StockMovementCreateSerializer,
        responses={200: StockMovementSerializer}
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
        summary='Adjust Stock Count (Physical Inventory Audit Reconciliation)',
        description='Sets the new physical stock quantity for a batch in a warehouse and logs an adjustment movement.',
        request=StockAdjustmentSerializer,
        responses={200: StockMovementSerializer}
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
            variance = movement.new_stock - movement.previous_stock
            unit_cost = product.purchase_price or product.selling_price or Decimal('0.00')
            shrinkage_loss = (Decimal(str(abs(variance))) * Decimal(str(unit_cost))).quantize(Decimal('0.01')) if variance < 0 else Decimal('0.00')

            return Response({
                'message': f"Stock adjusted successfully for {product.name} from {movement.previous_stock} to {data['new_quantity']}.",
                'previousStock': movement.previous_stock,
                'newStock': movement.new_stock,
                'variance': variance,
                'varianceStatus': 'SHRINKAGE_LOSS' if variance < 0 else ('SURPLUS_GAIN' if variance > 0 else 'EXACT_MATCH'),
                'estimatedFinancialLoss': str(shrinkage_loss) if variance < 0 else '0.00',
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
        summary='Get Damaged & Lost Products and Financial Loss Report',
        description='Returns comprehensive report of damaged write-offs and audit shrinkage discrepancies with monetary loss valuation in BDT and warehouse breakdowns.',
        parameters=[
            OpenApiParameter(name='product_id', type=int, location=OpenApiParameter.QUERY, description='Filter by Product ID', required=False),
            OpenApiParameter(name='warehouse_id', type=int, location=OpenApiParameter.QUERY, description='Filter by Warehouse ID', required=False),
            OpenApiParameter(name='incident_type', type=str, location=OpenApiParameter.QUERY, description='Filter by Incident Type (ALL, DAMAGE, SHRINKAGE)', required=False),
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Start date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='End date (YYYY-MM-DD)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='damages')
    def damages(self, request):
        product_id_param = request.query_params.get('product_id') or request.query_params.get('productId')
        warehouse_id_param = request.query_params.get('warehouse_id') or request.query_params.get('warehouseId')
        incident_type = (request.query_params.get('incident_type') or request.query_params.get('incidentType') or '').strip().upper() or None
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')

        product_id = int(product_id_param) if product_id_param and str(product_id_param).isdigit() else None
        warehouse_id = int(warehouse_id_param) if warehouse_id_param and str(warehouse_id_param).isdigit() else None
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        report = InventoryService.get_damage_and_loss_report(
            product_id=product_id,
            warehouse_id=warehouse_id,
            start_date=start_date,
            end_date=end_date,
            incident_type=incident_type
        )
        return Response(report, status=status.HTTP_200_OK)
