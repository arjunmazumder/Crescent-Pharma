from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes

from inventory.models import Warehouse, Product
from .models import (
    BOMHeader, BOMItem, ProductionLine, ProductionPlan,
    ProductionBatch, MaterialIssueSlip, MaterialIssueItem,
    ProductionStageLog, FinishedGoodsTransfer
)
from .serializers import (
    BOMHeaderSerializer, BOMCreateSerializer, BOMItemSerializer,
    ProductionLineSerializer, ProductionPlanSerializer,
    ProductionBatchListSerializer, ProductionBatchDetailSerializer, ProductionBatchCreateSerializer,
    MaterialIssueSlipSerializer, ProductionStageLogSerializer, FinishedGoodsTransferSerializer,
    BatchIssueMaterialsSerializer, BatchAdvanceStageSerializer,
    BatchRecordQCSerializer, BatchCompleteTransferSerializer, BatchReconcileReturnSerializer
)
from .services import BOMService, ProductionBatchService, ProductionReportService


# -----------------------------------------------------------------------------
# 1. BOMViewSet
# -----------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="List all Master Formula BOMs"),
    retrieve=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="Retrieve BOM details with ingredients"),
    create=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="Create a new Master Formula BOM with nested items"),
    update=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="Update BOM"),
    partial_update=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="Partial update BOM"),
    destroy=extend_schema(tags=['Production / Bill of Materials (BOM)'], summary="Delete BOM"),
)
class BOMViewSet(viewsets.ModelViewSet):
    queryset = BOMHeader.objects.select_related('finished_product', 'approved_by', 'created_by').prefetch_related('items__material').all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'is_approved', 'finished_product']
    search_fields = ['bom_code', 'mfr_number', 'finished_product__name', 'finished_product__unique_id']
    ordering_fields = ['id', 'created_at', 'standard_batch_size']
    ordering = ['-id']

    def get_serializer_class(self):
        if self.action == 'create':
            return BOMCreateSerializer
        return BOMHeaderSerializer

    @extend_schema(
        tags=['Production / Bill of Materials (BOM)'],
        summary="Approve BOM for factory production",
        request=None,
        responses={200: BOMHeaderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        bom = self.get_object()
        remarks = request.data.get('remarks', '')
        user = request.user if request.user.is_authenticated else None
        try:
            approved_bom = BOMService.approve_bom(bom=bom, user=user, remarks=remarks)
            return Response(BOMHeaderSerializer(approved_bom).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Bill of Materials (BOM)'],
        summary="Create a new version (e.g. v2.0) from existing BOM",
        request={'application/json': {'type': 'object', 'properties': {'new_version': {'type': 'string', 'example': 'v2.0'}}}},
        responses={201: BOMHeaderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='new-version')
    def new_version(self, request, pk=None):
        bom = self.get_object()
        new_version_str = request.data.get('new_version')
        if not new_version_str:
            return Response({'error': "Field 'new_version' (e.g. 'v2.0') is required."}, status=status.HTTP_400_BAD_REQUEST)
        user = request.user if request.user.is_authenticated else None
        try:
            new_bom = BOMService.create_new_version(bom=bom, new_version_str=new_version_str, user=user)
            return Response(BOMHeaderSerializer(new_bom).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Bill of Materials (BOM)'],
        summary="Estimate raw & packing materials required for custom batch size",
        parameters=[
            OpenApiParameter(name='batch_size', type=OpenApiTypes.DECIMAL, location=OpenApiParameter.QUERY, required=True, description="Custom target batch size (e.g. 50000)"),
            OpenApiParameter(name='warehouse_id', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False, description="Source raw material store ID to check available stock"),
        ]
    )
    @action(detail=True, methods=['get'], url_path='estimate-materials')
    def estimate_materials(self, request, pk=None):
        bom = self.get_object()
        batch_size_str = request.query_params.get('batch_size')
        if not batch_size_str:
            return Response({'error': "Query parameter 'batch_size' is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            batch_size = Decimal(batch_size_str)
        except Exception:
            return Response({'error': "Invalid 'batch_size' decimal value."}, status=status.HTTP_400_BAD_REQUEST)

        warehouse = None
        warehouse_id = request.query_params.get('warehouse_id')
        if warehouse_id:
            try:
                warehouse = Warehouse.objects.get(id=warehouse_id)
            except Warehouse.DoesNotExist:
                return Response({'error': f"Warehouse ID {warehouse_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            estimation = BOMService.estimate_materials(bom=bom, batch_target_quantity=batch_size, source_warehouse=warehouse)
            return Response(estimation, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# -----------------------------------------------------------------------------
# 2. ProductionLineViewSet
# -----------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List all manufacturing lines & cleanrooms"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get manufacturing line details"),
    create=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Create a new manufacturing line"),
    update=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Update line"),
    destroy=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Delete line"),
)
class ProductionLineViewSet(viewsets.ModelViewSet):
    queryset = ProductionLine.objects.all()
    serializer_class = ProductionLineSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'cleanroom_classification']
    search_fields = ['line_code', 'line_name']
    ordering_fields = ['line_code', 'daily_capacity', 'created_at']
    ordering = ['line_code']


# -----------------------------------------------------------------------------
# 3. ProductionPlanViewSet
# -----------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List all master production plans"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get master production plan details"),
    create=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Create a new production schedule plan"),
    update=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Update plan"),
    destroy=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Delete plan"),
)
class ProductionPlanViewSet(viewsets.ModelViewSet):
    queryset = ProductionPlan.objects.select_related('created_by', 'approved_by').prefetch_related('batches').all()
    serializer_class = ProductionPlanSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['plan_type', 'status']
    search_fields = ['plan_code', 'title']
    ordering_fields = ['start_date', 'created_at', 'total_target_batches']
    ordering = ['-start_date', '-id']

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Approve production plan",
        request=None,
        responses={200: ProductionPlanSerializer}
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        plan = self.get_object()
        user = request.user if request.user.is_authenticated else None
        plan.status = ProductionPlan.PlanStatus.APPROVED
        plan.approved_by = user
        plan.approved_at = timezone.now()
        plan.save()
        return Response(ProductionPlanSerializer(plan).data, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# 4. ProductionBatchViewSet (Core Manufacturing Lifecycle)
# -----------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List all manufacturing batches"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get complete batch manufacturing record (BMR) with stages and issue slips"),
    create=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Schedule a new pharmaceutical manufacturing batch"),
    update=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Update batch"),
    destroy=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Delete batch"),
)
class ProductionBatchViewSet(viewsets.ModelViewSet):
    queryset = ProductionBatch.objects.select_related(
        'production_plan', 'bom', 'finished_product', 'production_line',
        'source_warehouse', 'destination_warehouse', 'assigned_supervisor', 'created_by'
    ).prefetch_related(
        'assigned_operators',
        'material_issue_slips__items__material',
        'stage_logs__operator',
        'finished_goods_transfers__destination_warehouse'
    ).all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'current_stage', 'production_line', 'source_warehouse', 'destination_warehouse', 'finished_product']
    search_fields = ['batch_number', 'finished_product__name', 'finished_product__unique_id', 'bom__bom_code', 'bom__mfr_number']
    ordering_fields = ['manufacturing_date', 'expiry_date', 'planned_quantity', 'actual_produced_quantity', 'created_at']
    ordering = ['-manufacturing_date', '-id']

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductionBatchCreateSerializer
        elif self.action == 'retrieve':
            return ProductionBatchDetailSerializer
        return ProductionBatchListSerializer

    def create(self, request, *args, **kwargs):
        serializer = ProductionBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user if request.user.is_authenticated else None
        try:
            batch = ProductionBatchService.schedule_batch(
                bom=data['bom'],
                planned_quantity=data['planned_quantity'],
                production_line=data['production_line'],
                source_warehouse=data['source_warehouse'],
                destination_warehouse=data['destination_warehouse'],
                manufacturing_date=data['manufacturing_date'],
                expiry_date=data['expiry_date'],
                batch_number=data.get('batch_number'),
                production_plan=data.get('production_plan'),
                assigned_supervisor=data.get('assigned_supervisor'),
                assigned_operators=data.get('assigned_operators'),
                notes=data.get('notes', ''),
                user=user
            )
            return Response(ProductionBatchDetailSerializer(batch).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Issue raw & packing materials from warehouse to factory floor (Automated stock deduction)",
        request=BatchIssueMaterialsSerializer,
        responses={200: MaterialIssueSlipSerializer}
    )
    @action(detail=True, methods=['post'], url_path='issue-materials')
    def issue_materials(self, request, pk=None):
        batch = self.get_object()
        serializer = BatchIssueMaterialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        warehouse = batch.source_warehouse
        if data.get('warehouse_id'):
            try:
                warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            except Warehouse.DoesNotExist:
                return Response({'error': f"Warehouse {data['warehouse_id']} not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user if request.user.is_authenticated else None
        try:
            slip = ProductionBatchService.issue_materials(
                batch=batch,
                warehouse=warehouse,
                items_data=data['items'],
                user=user,
                notes=data.get('notes', '')
            )
            return Response(MaterialIssueSlipSerializer(slip).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Reconcile materials and return excess unused stock back to store",
        request=BatchReconcileReturnSerializer,
        responses={200: {'type': 'object', 'properties': {'success': {'type': 'boolean'}}}}
    )
    @action(detail=True, methods=['post'], url_path='reconcile-materials')
    def reconcile_materials(self, request, pk=None):
        batch = self.get_object()
        serializer = BatchReconcileReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user if request.user.is_authenticated else None
        try:
            ProductionBatchService.reconcile_and_return_materials(
                batch=batch,
                return_items_data=data['items'],
                user=user,
                notes=data.get('notes', '')
            )
            return Response({'success': True, 'message': "Materials successfully reconciled and returned to warehouse."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Advance batch manufacturing stage (MIXING -> PROCESSING -> FILLING -> PACKAGING -> QC)",
        request=BatchAdvanceStageSerializer,
        responses={200: ProductionBatchDetailSerializer}
    )
    @action(detail=True, methods=['post'], url_path='advance-stage')
    def advance_stage(self, request, pk=None):
        batch = self.get_object()
        serializer = BatchAdvanceStageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user if request.user.is_authenticated else None
        try:
            updated_batch = ProductionBatchService.advance_stage(
                batch=batch,
                next_stage=data['next_stage'],
                user=user,
                notes=data.get('notes')
            )
            return Response(ProductionBatchDetailSerializer(updated_batch).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Record In-Process Quality Control (IPQC) test parameters and room condition logs",
        request=BatchRecordQCSerializer,
        responses={201: ProductionStageLogSerializer}
    )
    @action(detail=True, methods=['post'], url_path='record-stage-qc')
    def record_stage_qc(self, request, pk=None):
        batch = self.get_object()
        serializer = BatchRecordQCSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user if request.user.is_authenticated else None
        try:
            log = ProductionBatchService.record_stage_qc(
                batch=batch,
                stage=data['stage'],
                status=data['status'],
                operator=user,
                machine_equipment_name=data.get('machine_equipment_name'),
                temperature_celsius=data.get('temperature_celsius'),
                humidity_percentage=data.get('humidity_percentage'),
                qc_parameters_json=data.get('qc_parameters_json'),
                remarks=data.get('remarks'),
                completed=data.get('completed', True)
            )
            return Response(ProductionStageLogSerializer(log).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Complete batch, transfer finished medicine to warehouse, and auto-post double-entry accounting JV",
        request=BatchCompleteTransferSerializer,
        responses={200: FinishedGoodsTransferSerializer}
    )
    @action(detail=True, methods=['post'], url_path='complete-and-transfer')
    def complete_and_transfer(self, request, pk=None):
        batch = self.get_object()
        serializer = BatchCompleteTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        dest_warehouse = None
        if data.get('destination_warehouse_id'):
            try:
                dest_warehouse = Warehouse.objects.get(id=data['destination_warehouse_id'])
            except Warehouse.DoesNotExist:
                return Response({'error': f"Destination warehouse {data['destination_warehouse_id']} not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user if request.user.is_authenticated else None
        try:
            transfer = ProductionBatchService.complete_and_transfer(
                batch=batch,
                actual_produced_quantity=data['actual_produced_quantity'],
                rejected_quantity=data.get('rejected_quantity', Decimal('0.000')),
                qc_release_certificate_number=data['qc_release_certificate_number'],
                destination_warehouse=dest_warehouse,
                user=user,
                notes=data.get('notes', '')
            )
            return Response(FinishedGoodsTransferSerializer(transfer).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# -----------------------------------------------------------------------------
# 5. Read-Only Supporting ViewSets
# -----------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List material issue slips"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get material issue slip details"),
)
class MaterialIssueSlipViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MaterialIssueSlip.objects.select_related('batch', 'warehouse', 'issued_by', 'received_by').prefetch_related('items__material').all()
    serializer_class = MaterialIssueSlipSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch', 'warehouse', 'status']
    search_fields = ['issue_number', 'batch__batch_number']
    ordering_fields = ['issued_date', 'created_at']
    ordering = ['-issued_date', '-id']


@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List IPQC stage logs"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get IPQC stage log details"),
)
class ProductionStageLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductionStageLog.objects.select_related('batch', 'operator').all()
    serializer_class = ProductionStageLogSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch', 'stage', 'status']
    search_fields = ['batch__batch_number', 'machine_equipment_name']
    ordering_fields = ['started_at', 'created_at']
    ordering = ['-started_at']


@extend_schema_view(
    list=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="List finished goods transfers"),
    retrieve=extend_schema(tags=['Production / Manufacturing Batches & WIP'], summary="Get finished goods transfer details"),
)
class FinishedGoodsTransferViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FinishedGoodsTransfer.objects.select_related(
        'batch', 'finished_product', 'destination_warehouse', 'received_by', 'created_by', 'accounting_voucher'
    ).all()
    serializer_class = FinishedGoodsTransferSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch', 'destination_warehouse', 'is_received']
    search_fields = ['transfer_code', 'batch__batch_number', 'qc_release_certificate_number']
    ordering_fields = ['transfer_date', 'created_at', 'transfer_quantity']
    ordering = ['-transfer_date', '-id']


# -----------------------------------------------------------------------------
# 6. ProductionReportViewSet (Dashboard & 360° Traceability)
# -----------------------------------------------------------------------------

class ProductionReportViewSet(viewsets.ViewSet):
    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Production plant dashboard metrics & statistics"
    )
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        try:
            data = ProductionReportService.get_production_dashboard()
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Production / Manufacturing Batches & WIP'],
        summary="Complete 360° batch genealogy and traceability audit report",
        parameters=[
            OpenApiParameter(name='batch_number', type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True, description="Pharmaceutical Batch Number (e.g. BATCH-2026-0101)")
        ]
    )
    @action(detail=False, methods=['get'], url_path=r'batch-traceability/(?P<batch_number>[^/.]+)')
    def batch_traceability(self, request, batch_number=None):
        if not batch_number:
            return Response({'error': "Batch number path parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            report = ProductionReportService.get_batch_traceability(batch_number=batch_number)
            return Response(report, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
