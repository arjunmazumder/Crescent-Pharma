from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from purchases.models import (
    Supplier, SupplierType, SupplyCategory, AuditStatus,
    PurchaseOrder, PurchaseOrderItem, OrderStatus,
    LetterOfCredit, LetterOfCreditStatus, LCDocument,
    LCLandingCost, GoodsReceivedNote, GoodsReceivedNoteStatus
)
from purchases.serializers import (
    SupplierSerializer, SimpleSupplierSerializer,
    PurchaseOrderSerializer, PurchaseOrderCreateSerializer, PurchaseOrderCancelSerializer,
    PurchaseOrderItemSerializer,
    LetterOfCreditSerializer, LetterOfCreditCreateSerializer, LCStageAdvanceSerializer,
    LCDocumentSerializer, LCLandingCostSerializer,
    GoodsReceivedNoteSerializer, GoodsReceivedNoteCreateSerializer
)
from purchases.services import (
    PurchaseOrderService, LCManagementService, LandedCostService, GoodsReceiptService
)
from inventory.models import Warehouse, Product
from accounting.models import AccountHead


# -----------------------------------------------------------------------------
# 1. Supplier ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['Purchases / Suppliers'])
class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by('-id')
    serializer_class = SupplierSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        supplier_type = self.request.query_params.get('supplier_type')
        supply_category = self.request.query_params.get('supply_category')
        audit_status = self.request.query_params.get('audit_status')
        is_active = self.request.query_params.get('is_active')
        search = self.request.query_params.get('search')

        if supplier_type:
            qs = qs.filter(supplier_type=supplier_type)
        if supply_category:
            qs = qs.filter(supply_category=supply_category)
        if audit_status:
            qs = qs.filter(audit_status=audit_status)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ['true', '1'])
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search) |
                Q(supplier_code__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(email_address__icontains=search) |
                Q(contact_person_name__icontains=search) |
                Q(drug_license_number__icontains=search)
            )
        return qs


# -----------------------------------------------------------------------------
# 2. Purchase Order ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['Purchases / Purchase Orders'])
class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().select_related('supplier', 'delivery_warehouse', 'created_by', 'approved_by').prefetch_related('items__product').order_by('-order_date', '-id')
    serializer_class = PurchaseOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        supplier_id = self.request.query_params.get('supplier_id')
        status_param = self.request.query_params.get('status')
        order_type = self.request.query_params.get('order_type')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        search = self.request.query_params.get('search')

        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if status_param:
            qs = qs.filter(status=status_param)
        if order_type:
            qs = qs.filter(order_type=order_type)
        if start_date:
            qs = qs.filter(order_date__gte=start_date)
        if end_date:
            qs = qs.filter(order_date__lte=end_date)
        if search:
            qs = qs.filter(
                Q(purchase_order_number__icontains=search) |
                Q(supplier__company_name__icontains=search) |
                Q(proforma_invoice_number__icontains=search) |
                Q(dgda_blocklist_number__icontains=search)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = PurchaseOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            supplier = Supplier.objects.get(id=data['supplier_id'])
        except Supplier.DoesNotExist:
            return Response({'error': f"Supplier with ID {data['supplier_id']} not found."}, status=status.HTTP_400_BAD_REQUEST)

        delivery_warehouse = None
        if data.get('delivery_warehouse_id'):
            delivery_warehouse = Warehouse.objects.filter(id=data['delivery_warehouse_id']).first()

        try:
            po = PurchaseOrderService.create_order(
                supplier=supplier,
                items_data=data['items'],
                user=request.user if request.user.is_authenticated else None,
                order_date=data.get('order_date'),
                expected_delivery_date=data.get('expected_delivery_date'),
                delivery_warehouse=delivery_warehouse,
                order_type=data.get('order_type', 'RAW_MATERIAL'),
                currency=data.get('currency', 'BDT'),
                exchange_rate=data.get('exchange_rate', Decimal('1.0000')),
                payment_terms=data.get('payment_terms', ''),
                proforma_invoice_number=data.get('proforma_invoice_number', ''),
                proforma_invoice_date=data.get('proforma_invoice_date'),
                dgda_blocklist_number=data.get('dgda_blocklist_number', ''),
                incoterm=data.get('incoterm', ''),
                special_notes=data.get('special_notes', '')
            )
            return Response(PurchaseOrderSerializer(po).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        po = self.get_object()
        try:
            approved_po = PurchaseOrderService.approve_order(
                purchase_order=po,
                user=request.user if request.user.is_authenticated else None
            )
            return Response({
                'message': f"Purchase Order '{po.purchase_order_number}' approved successfully.",
                'data': PurchaseOrderSerializer(approved_po).data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        po = self.get_object()
        serializer = PurchaseOrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        try:
            cancelled_po = PurchaseOrderService.cancel_order(
                purchase_order=po,
                reason=reason,
                user=request.user if request.user.is_authenticated else None
            )
            return Response({
                'message': f"Purchase Order '{po.purchase_order_number}' cancelled.",
                'data': PurchaseOrderSerializer(cancelled_po).data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# -----------------------------------------------------------------------------
# 3. Letter of Credit (LC) ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['Purchases / Letters of Credit (LC)'])
class LetterOfCreditViewSet(viewsets.ModelViewSet):
    queryset = LetterOfCredit.objects.all().select_related('supplier', 'purchase_order', 'issuing_bank_account', 'margin_voucher', 'created_by').prefetch_related('documents').order_by('-lc_opening_date', '-id')
    serializer_class = LetterOfCreditSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        supplier_id = self.request.query_params.get('supplier_id')
        status_param = self.request.query_params.get('status')
        lc_type = self.request.query_params.get('letter_of_credit_type')
        search = self.request.query_params.get('search')

        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if status_param:
            qs = qs.filter(status=status_param)
        if lc_type:
            qs = qs.filter(letter_of_credit_type=lc_type)
        if search:
            qs = qs.filter(
                Q(letter_of_credit_number__icontains=search) |
                Q(supplier__company_name__icontains=search) |
                Q(harmonized_system_code__icontains=search) |
                Q(insurance_cover_note_number__icontains=search)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = LetterOfCreditCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            supplier = Supplier.objects.get(id=data['supplier_id'])
        except Supplier.DoesNotExist:
            return Response({'error': f"Supplier with ID {data['supplier_id']} not found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            bank_account = AccountHead.objects.get(id=data['issuing_bank_account_id'])
        except AccountHead.DoesNotExist:
            return Response({'error': f"Bank AccountHead with ID {data['issuing_bank_account_id']} not found."}, status=status.HTTP_400_BAD_REQUEST)

        po = None
        if data.get('purchase_order_id'):
            po = PurchaseOrder.objects.filter(id=data['purchase_order_id']).first()

        try:
            lc = LCManagementService.create_letter_of_credit(
                supplier=supplier,
                purchase_order=po,
                issuing_bank_account=bank_account,
                issuing_branch_name=data['issuing_branch_name'],
                lc_opening_date=data['lc_opening_date'],
                lc_expiry_date=data['lc_expiry_date'],
                total_amount_in_foreign_currency=data['total_amount_in_foreign_currency'],
                exchange_rate_to_bdt=data['exchange_rate_to_bdt'],
                bank_margin_percentage=data.get('bank_margin_percentage', Decimal('0.00')),
                currency=data.get('currency', 'USD'),
                letter_of_credit_type=data.get('letter_of_credit_type', 'SIGHT'),
                incoterm=data.get('incoterm', 'CFR'),
                latest_shipment_date=data.get('latest_shipment_date'),
                harmonized_system_code=data.get('harmonized_system_code', ''),
                port_of_loading=data.get('port_of_loading', ''),
                port_of_discharge=data.get('port_of_discharge', 'Chattogram Sea Port / Dhaka Airport'),
                clearing_and_forwarding_agent_name=data.get('clearing_and_forwarding_agent_name', ''),
                insurance_company_name=data.get('insurance_company_name', ''),
                insurance_cover_note_number=data.get('insurance_cover_note_number', ''),
                special_notes=data.get('special_notes', ''),
                post_margin_voucher=data.get('post_margin_voucher', True),
                user=request.user if request.user.is_authenticated else None
            )
            return Response(LetterOfCreditSerializer(lc).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='advance-stage')
    def advance_stage(self, request, pk=None):
        lc = self.get_object()
        serializer = LCStageAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        next_status = serializer.validated_data['next_status']

        try:
            updated_lc = LCManagementService.advance_lc_stage(
                letter_of_credit=lc,
                next_status=next_status,
                user=request.user if request.user.is_authenticated else None
            )
            return Response({
                'message': f"LC '{lc.letter_of_credit_number}' advanced to '{next_status}'.",
                'data': LetterOfCreditSerializer(updated_lc).data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='add-document')
    def add_document(self, request, pk=None):
        lc = self.get_object()
        doc_type = request.data.get('document_type')
        title = request.data.get('document_title') or request.data.get('title')
        file_url = request.data.get('document_file_url') or request.data.get('file_url')

        if not title or not file_url:
            return Response({'error': "document_title and document_file_url are required."}, status=status.HTTP_400_BAD_REQUEST)

        doc = LCManagementService.add_lc_document(
            letter_of_credit=lc,
            document_type=doc_type or 'OTHER',
            document_title=title,
            document_file_url=file_url,
            user=request.user if request.user.is_authenticated else None
        )
        return Response(LCDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='landed-cost')
    def landed_cost(self, request, pk=None):
        lc = self.get_object()
        if request.method == 'GET':
            landing_cost, _ = LCLandingCost.objects.get_or_create(letter_of_credit=lc)
            allocations = LandedCostService.get_allocated_landed_costs(lc)
            return Response({
                'landing_cost': LCLandingCostSerializer(landing_cost).data,
                'item_allocations': allocations
            }, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            finalize = request.data.get('finalize', False)
            landing_cost = LandedCostService.calculate_and_save_landed_cost(
                letter_of_credit=lc,
                cost_data=request.data,
                user=request.user if request.user.is_authenticated else None,
                finalize=finalize
            )
            allocations = LandedCostService.get_allocated_landed_costs(lc)
            return Response({
                'message': "Landed cost saved successfully.",
                'landing_cost': LCLandingCostSerializer(landing_cost).data,
                'item_allocations': allocations
            }, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# 4. Goods Received Note (GRN) ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['Purchases / Goods Received Notes (GRN)'])
class GoodsReceivedNoteViewSet(viewsets.ModelViewSet):
    queryset = GoodsReceivedNote.objects.all().select_related('purchase_order', 'letter_of_credit', 'receiving_warehouse', 'accounting_voucher', 'created_by', 'approved_by').prefetch_related('items__product').order_by('-received_date', '-id')
    serializer_class = GoodsReceivedNoteSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        warehouse_id = self.request.query_params.get('warehouse_id')
        status_param = self.request.query_params.get('status')
        po_id = self.request.query_params.get('purchase_order_id')
        lc_id = self.request.query_params.get('letter_of_credit_id')
        search = self.request.query_params.get('search')

        if warehouse_id:
            qs = qs.filter(receiving_warehouse_id=warehouse_id)
        if status_param:
            qs = qs.filter(status=status_param)
        if po_id:
            qs = qs.filter(purchase_order_id=po_id)
        if lc_id:
            qs = qs.filter(letter_of_credit_id=lc_id)
        if search:
            qs = qs.filter(
                Q(goods_received_note_number__icontains=search) |
                Q(bill_of_entry_number__icontains=search) |
                Q(challan_number__icontains=search) |
                Q(purchase_order__purchase_order_number__icontains=search)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = GoodsReceivedNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            warehouse = Warehouse.objects.get(id=data['receiving_warehouse_id'], is_active=True)
        except Warehouse.DoesNotExist:
            return Response({'error': f"Warehouse with ID {data['receiving_warehouse_id']} not found or is inactive."}, status=status.HTTP_400_BAD_REQUEST)

        po = None
        if data.get('purchase_order_id'):
            po = PurchaseOrder.objects.filter(id=data['purchase_order_id']).first()

        lc = None
        if data.get('letter_of_credit_id'):
            lc = LetterOfCredit.objects.filter(id=data['letter_of_credit_id']).first()

        try:
            grn = GoodsReceiptService.create_grn(
                receiving_warehouse=warehouse,
                items_data=data['items'],
                purchase_order=po,
                letter_of_credit=lc,
                received_date=data.get('received_date'),
                bill_of_entry_number=data.get('bill_of_entry_number', ''),
                challan_number=data.get('challan_number', ''),
                special_notes=data.get('special_notes', ''),
                user=request.user if request.user.is_authenticated else None
            )
            return Response(GoodsReceivedNoteSerializer(grn).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='approve-and-receive')
    def approve_and_receive(self, request, pk=None):
        grn = self.get_object()
        try:
            approved_grn = GoodsReceiptService.approve_and_receive_grn(
                grn=grn,
                user=request.user if request.user.is_authenticated else None
            )
            return Response({
                'message': f"GRN '{approved_grn.goods_received_note_number}' approved. Inventory stock inflow recorded and accounting purchase voucher posted.",
                'data': GoodsReceivedNoteSerializer(approved_grn).data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# -----------------------------------------------------------------------------
# 5. Purchase Reports & Analytics ViewSet
# -----------------------------------------------------------------------------

@extend_schema(tags=['Purchases / Reports & Dashboard'])
class PurchaseReportViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """
        Returns high-level procurement KPIs and metrics.
        """
        total_suppliers = Supplier.objects.filter(is_active=True).count()
        total_local_suppliers = Supplier.objects.filter(is_active=True, supplier_type=SupplierType.LOCAL).count()
        total_overseas_suppliers = Supplier.objects.filter(is_active=True, supplier_type=SupplierType.OVERSEAS).count()

        active_lcs = LetterOfCredit.objects.exclude(status__in=[LetterOfCreditStatus.CLOSED, LetterOfCreditStatus.CANCELLED])
        active_lcs_count = active_lcs.count()
        active_lcs_foreign_val = active_lcs.aggregate(total=Sum('total_amount_in_foreign_currency'))['total'] or Decimal('0.00')
        active_lcs_bdt_val = active_lcs.aggregate(total=Sum('total_amount_in_bdt'))['total'] or Decimal('0.00')

        pos = PurchaseOrder.objects.all()
        po_counts = {
            'draft': pos.filter(status=OrderStatus.DRAFT).count(),
            'approved': pos.filter(status=OrderStatus.APPROVED).count(),
            'partially_received': pos.filter(status=OrderStatus.PARTIALLY_RECEIVED).count(),
            'completed': pos.filter(status=OrderStatus.COMPLETED).count(),
            'total': pos.count()
        }

        total_procurement_bdt = pos.filter(status__in=[OrderStatus.APPROVED, OrderStatus.PARTIALLY_RECEIVED, OrderStatus.COMPLETED]).aggregate(total=Sum('total_amount_in_bdt'))['total'] or Decimal('0.00')

        recent_pos = PurchaseOrderSerializer(pos.order_by('-id')[:5], many=True).data
        recent_lcs = LetterOfCreditSerializer(active_lcs.order_by('-id')[:5], many=True).data

        return Response({
            'supplier_metrics': {
                'total_active_suppliers': total_suppliers,
                'local_suppliers': total_local_suppliers,
                'overseas_suppliers': total_overseas_suppliers,
            },
            'lc_metrics': {
                'active_lcs_count': active_lcs_count,
                'active_lcs_foreign_currency_value': str(active_lcs_foreign_val),
                'active_lcs_bdt_value': str(active_lcs_bdt_val),
            },
            'po_metrics': {
                'counts': po_counts,
                'total_approved_procurement_bdt': str(total_procurement_bdt),
            },
            'recent_orders': recent_pos,
            'active_letters_of_credit': recent_lcs
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='lc-pipeline')
    def lc_pipeline(self, request):
        """
        Returns count of LCs grouped by their stage in the shipment pipeline.
        """
        pipeline = {}
        for choice, label in LetterOfCreditStatus.choices:
            count = LetterOfCredit.objects.filter(status=choice).count()
            val = LetterOfCredit.objects.filter(status=choice).aggregate(total=Sum('total_amount_in_bdt'))['total'] or Decimal('0.00')
            pipeline[choice] = {
                'stage_label': label,
                'count': count,
                'total_bdt_value': str(val)
            }
        return Response(pipeline, status=status.HTTP_200_OK)
