import datetime
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

from .models import (
    AccountHead, FiscalYear, AccountingPeriod,
    Voucher, JournalEntry, PaymentRecord,
    BankReconciliation, VoucherStatus, VoucherType,
    AccountType
)
from .serializers import (
    AccountHeadSerializer, AccountHeadTreeSerializer,
    FiscalYearSerializer, AccountingPeriodSerializer,
    VoucherSerializer, VoucherCreateSerializer, VoucherReverseSerializer,
    JournalEntrySerializer,
    PaymentRecordSerializer, PaymentRecordCreateSerializer,
    BankReconciliationSerializer, BankReconciliationCreateSerializer
)
from .services import (
    VoucherPostingService, AccountingIntegrationService,
    FinancialReportEngine
)


@extend_schema(tags=['Accounting / Chart of Accounts'])
class AccountHeadViewSet(viewsets.ModelViewSet):
    queryset = AccountHead.objects.all().select_related('parent').order_by('code')
    serializer_class = AccountHeadSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['code', 'name', 'description', 'bank_account_no']
    filterset_fields = ['account_type', 'is_group', 'is_reconciliation', 'is_active', 'is_system_locked', 'currency']
    ordering_fields = ['code', 'name', 'account_type', 'created_at']

    @extend_schema(
        summary='Get Hierarchical Chart of Accounts Tree',
        description='Returns complete nested tree structure of all root accounts and sub-accounts.'
    )
    @action(detail=False, methods=['get'])
    def tree(self, request):
        roots = AccountHead.objects.filter(parent__isnull=True, is_active=True).order_by('code')
        serializer = AccountHeadTreeSerializer(roots, many=True)
        return Response(serializer.data)


@extend_schema(tags=['Accounting / Fiscal Calendar'])
class FiscalYearViewSet(viewsets.ModelViewSet):
    queryset = FiscalYear.objects.all().prefetch_related('periods').order_by('-start_date')
    serializer_class = FiscalYearSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'code']
    filterset_fields = ['is_current', 'is_locked', 'is_closed']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        out_serializer = self.get_serializer(instance)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary='Lock Fiscal Year against back-dated entries', request=None)
    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        fy = self.get_object()
        fy.is_locked = True
        fy.locked_by = request.user
        fy.locked_at = timezone.now()
        fy.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
        return Response({'message': f"Fiscal Year '{fy.name}' locked successfully."})

    @extend_schema(summary='Unlock Fiscal Year', request=None)
    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        fy = self.get_object()
        fy.is_locked = False
        fy.locked_by = None
        fy.locked_at = None
        fy.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
        return Response({'message': f"Fiscal Year '{fy.name}' unlocked successfully."})


@extend_schema(tags=['Accounting / Fiscal Calendar'])
class AccountingPeriodViewSet(viewsets.ModelViewSet):
    queryset = AccountingPeriod.objects.all().select_related('fiscal_year').order_by('fiscal_year', 'period_number')
    serializer_class = AccountingPeriodSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['fiscal_year', 'is_current', 'is_locked', 'is_closed']

    @extend_schema(summary='Lock Accounting Period', request=None)
    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        period = self.get_object()
        period.is_locked = True
        period.locked_by = request.user
        period.locked_at = timezone.now()
        period.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
        return Response({'message': f"Accounting Period '{period.name}' locked successfully."})

    @extend_schema(summary='Unlock Accounting Period', request=None)
    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        period = self.get_object()
        period.is_locked = False
        period.locked_by = None
        period.locked_at = None
        period.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
        return Response({'message': f"Accounting Period '{period.name}' unlocked successfully."})


@extend_schema(tags=['Accounting / Vouchers'])
class VoucherViewSet(viewsets.ModelViewSet):
    queryset = Voucher.objects.all().prefetch_related('entries', 'entries__account').select_related('period', 'created_by', 'posted_by').order_by('-voucher_date', '-id')
    serializer_class = VoucherSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['voucher_number', 'reference_no', 'narration', 'cheque_number']
    filterset_fields = ['voucher_type', 'status', 'period', 'is_auto_generated', 'source_module', 'is_reversed']
    ordering_fields = ['voucher_date', 'id', 'total_debit', 'created_at']

    @extend_schema(
        summary='Create & Post Double-Entry Voucher',
        description='Creates a new double-entry voucher with balanced line items (sum(Debit) == sum(Credit)).',
        request=VoucherCreateSerializer,
        responses={201: VoucherSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = VoucherCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            voucher = VoucherPostingService.create_and_post_voucher(
                voucher_type=data['voucher_type'],
                voucher_date=data['voucher_date'],
                narration=data['narration'],
                entries_data=data['entries'],
                reference_no=data.get('reference_no', ''),
                attachment_url=data.get('attachment_url', ''),
                cheque_number=data.get('cheque_number', ''),
                cheque_date=data.get('cheque_date'),
                cheque_status=data.get('cheque_status'),
                user=request.user,
                auto_post=data.get('auto_post', True)
            )
            out_serializer = VoucherSerializer(voucher)
            return Response(out_serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary='Post/Approve Draft Voucher',
        description='Transitions a DRAFT or SUBMITTED voucher to POSTED.',
        request=None,
        responses={200: VoucherSerializer}
    )
    @action(detail=True, methods=['post'])
    def post_voucher(self, request, pk=None):
        voucher = self.get_object()
        if voucher.status == VoucherStatus.POSTED:
            return Response({'error': 'Voucher is already POSTED.'}, status=status.HTTP_400_BAD_REQUEST)
        if voucher.status == VoucherStatus.CANCELLED:
            return Response({'error': 'Cannot post a CANCELLED voucher.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate balance
        tot_dr = sum(e.debit_amount for e in voucher.entries.all())
        tot_cr = sum(e.credit_amount for e in voucher.entries.all())
        if tot_dr != tot_cr or tot_dr <= 0:
            return Response({'error': f'Voucher debit ({tot_dr}) and credit ({tot_cr}) must be balanced and > 0.'}, status=status.HTTP_400_BAD_REQUEST)

        VoucherPostingService.validate_period_and_fiscal_year(voucher.voucher_date)

        voucher.status = VoucherStatus.POSTED
        voucher.posted_by = request.user
        voucher.posted_at = timezone.now()
        voucher.save(update_fields=['status', 'posted_by', 'posted_at'])

        return Response(VoucherSerializer(voucher).data)

    @extend_schema(
        summary='Reverse Posted Voucher',
        description='Creates an automatic reverse journal entry reversing all debits and credits.',
        request=VoucherReverseSerializer
    )
    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        voucher = self.get_object()
        serializer = VoucherReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            rev_voucher = VoucherPostingService.reverse_voucher(
                voucher=voucher,
                reason=serializer.validated_data['reason'],
                user=request.user
            )
            return Response({
                'message': f"Voucher '{voucher.voucher_number}' reversed successfully.",
                'reversalVoucher': VoucherSerializer(rev_voucher).data
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary='Cancel Draft Voucher', request=None)
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        voucher = self.get_object()
        if voucher.status == VoucherStatus.POSTED:
            return Response({'error': 'Cannot cancel a POSTED voucher. Please use the reverse action.'}, status=status.HTTP_400_BAD_REQUEST)

        voucher.status = VoucherStatus.CANCELLED
        voucher.rejection_reason = request.data.get('reason', 'Cancelled by user')
        voucher.rejected_by = request.user
        voucher.save(update_fields=['status', 'rejection_reason', 'rejected_by'])
        return Response({'message': f"Voucher '{voucher.voucher_number}' cancelled."})


@extend_schema(tags=['Accounting / Payments & Collections'])
class PaymentRecordViewSet(viewsets.ModelViewSet):
    queryset = PaymentRecord.objects.all().select_related('deposit_to_account', 'voucher', 'order', 'created_by').order_by('-payment_date', '-id')
    serializer_class = PaymentRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['receipt_no', 'reference_no', 'notes']
    filterset_fields = ['payment_type', 'party_type', 'party_id', 'payment_method', 'order']
    ordering_fields = ['payment_date', 'amount', 'created_at']

    @extend_schema(
        summary='Record Customer Collection / Payment Receipt',
        description='Records customer money receipt, creates double-entry receipt voucher, and reconciles sales invoice balance.',
        request=PaymentRecordCreateSerializer,
        responses={201: PaymentRecordSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = PaymentRecordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from sales.models import CustomerOrder
        order = None
        if data.get('order_id'):
            order = CustomerOrder.objects.filter(id=data['order_id']).first()
            if not order:
                return Response({'error': f"Customer Order with ID {data['order_id']} not found."}, status=status.HTTP_404_NOT_FOUND)

        deposit_acc = AccountHead.objects.filter(id=data['deposit_to_account_id'], is_active=True).first()
        if not deposit_acc:
            return Response({'error': f"Deposit Account with ID {data['deposit_to_account_id']} not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            if order:
                rec, voucher = AccountingIntegrationService.post_customer_payment(
                    order=order,
                    amount=data['amount'],
                    payment_method=data['payment_method'],
                    deposit_account=deposit_acc,
                    reference_no=data.get('reference_no', ''),
                    notes=data.get('notes', ''),
                    user=request.user
                )
            else:
                # Direct collection / payment without specific order link
                rec = PaymentRecord.objects.create(
                    payment_type=data['payment_type'],
                    party_type=data['party_type'],
                    party_id=data['party_id'],
                    payment_date=data['payment_date'],
                    amount=data['amount'],
                    payment_method=data['payment_method'],
                    deposit_to_account=deposit_acc,
                    reference_no=data.get('reference_no', ''),
                    notes=data.get('notes', ''),
                    created_by=request.user
                )
            return Response(PaymentRecordSerializer(rec).data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Accounting / Bank Reconciliation'])
class BankReconciliationViewSet(viewsets.ModelViewSet):
    queryset = BankReconciliation.objects.all().select_related('account', 'reconciled_by').order_by('-statement_date', '-id')
    serializer_class = BankReconciliationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['account', 'status', 'statement_date']

    @extend_schema(
        summary='Execute Bank Reconciliation & Match Statement',
        description='Computes unpresented cheques, uncredited deposits, and balances variance.',
        request=BankReconciliationCreateSerializer,
        responses={201: BankReconciliationSerializer}
    )
    @action(detail=False, methods=['post'])
    def reconcile(self, request):
        acc_id = request.data.get('account_id') or request.data.get('accountId')
        stmt_date = parse_date(str(request.data.get('statement_date') or request.data.get('statementDate')))
        stmt_bal = Decimal(str(request.data.get('statement_balance') or request.data.get('statementBalance') or '0.00'))
        cleared_ids = request.data.get('cleared_entry_ids') or request.data.get('clearedEntryIds') or []

        account = get_object_or_404(AccountHead, id=acc_id)

        # Mark cleared entries
        if cleared_ids:
            JournalEntry.objects.filter(id__in=cleared_ids, account=account).update(
                is_reconciled=True,
                reconciled_at=timezone.now()
            )

        # Compute GL balance up to statement date
        gl_statement = FinancialReportEngine.get_general_ledger(account.id, end_date=stmt_date)
        gl_balance = Decimal(str(gl_statement['closingBalance']))

        # Compute unpresented cheques (issued credit lines where is_reconciled=False)
        unpresented = JournalEntry.objects.filter(
            account=account,
            credit_amount__gt=0,
            is_reconciled=False,
            voucher__status=VoucherStatus.POSTED,
            voucher__voucher_date__lte=stmt_date
        ).aggregate(tot=models.Sum('credit_amount'))['tot'] or Decimal('0.00')

        # Compute uncredited deposits (deposited debit lines where is_reconciled=False)
        uncredited = JournalEntry.objects.filter(
            account=account,
            debit_amount__gt=0,
            is_reconciled=False,
            voucher__status=VoucherStatus.POSTED,
            voucher__voucher_date__lte=stmt_date
        ).aggregate(tot=models.Sum('debit_amount'))['tot'] or Decimal('0.00')

        adjusted_bank_balance = stmt_bal + uncredited - unpresented
        difference = (gl_balance - adjusted_bank_balance).quantize(Decimal('0.01'))

        brs = BankReconciliation.objects.create(
            account=account,
            statement_date=stmt_date,
            statement_balance=stmt_bal,
            gl_balance=gl_balance,
            unpresented_cheques_total=unpresented,
            uncredited_deposits_total=uncredited,
            adjusted_balance=adjusted_bank_balance,
            difference=difference,
            status=ReconciliationStatus.RECONCILED if difference == Decimal('0.00') else ReconciliationStatus.DRAFT,
            attachment_url=request.data.get('attachment_url', ''),
            notes=request.data.get('notes', ''),
            reconciled_by=request.user
        )

        return Response(BankReconciliationSerializer(brs).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Accounting / Financial Reports'])
class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary='General Ledger Report',
        description='Returns line-by-line General Ledger with Opening, Running, and Closing Balances.',
        parameters=[
            OpenApiParameter('account_id', int, required=True, description='Account Head ID'),
            OpenApiParameter('start_date', str, required=False, description='Start Date (YYYY-MM-DD)'),
            OpenApiParameter('end_date', str, required=False, description='End Date (YYYY-MM-DD)'),
            OpenApiParameter('party_type', str, required=False, description='CUSTOMER / SUPPLIER / EMPLOYEE'),
            OpenApiParameter('party_id', int, required=False, description='Party ID for Sub-Ledger statement')
        ]
    )
    @action(detail=False, methods=['get'], url_path='general-ledger')
    def general_ledger(self, request):
        acc_id = request.query_params.get('account_id')
        if not acc_id:
            return Response({'error': 'account_id parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        start_date = parse_date(request.query_params.get('start_date', '')) if request.query_params.get('start_date') else None
        end_date = parse_date(request.query_params.get('end_date', '')) if request.query_params.get('end_date') else None
        party_type = request.query_params.get('party_type')
        party_id = request.query_params.get('party_id')

        try:
            report = FinancialReportEngine.get_general_ledger(
                account_id=acc_id,
                start_date=start_date,
                end_date=end_date,
                party_type=party_type,
                party_id=party_id
            )
            return Response(report)
        except AccountHead.DoesNotExist:
            return Response({'error': f'AccountHead with ID {acc_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        summary='Cash & Bank Book',
        description='Specialized report aggregating all liquid Cash in Hand and Bank Current/Savings accounts.',
        parameters=[
            OpenApiParameter('start_date', str, required=False),
            OpenApiParameter('end_date', str, required=False)
        ]
    )
    @action(detail=False, methods=['get'], url_path='cash-bank-book')
    def cash_and_bank_book(self, request):
        start_date = parse_date(request.query_params.get('start_date', '')) if request.query_params.get('start_date') else None
        end_date = parse_date(request.query_params.get('end_date', '')) if request.query_params.get('end_date') else None
        report = FinancialReportEngine.get_cash_and_bank_book(start_date, end_date)
        return Response(report)

    @extend_schema(
        summary='Trial Balance Report',
        description='Generates Trial Balance verifying sum(Debits) == sum(Credits) as of a specific date.',
        parameters=[
            OpenApiParameter('as_of_date', str, required=False, description='As of Date (YYYY-MM-DD)')
        ]
    )
    @action(detail=False, methods=['get'], url_path='trial-balance')
    def trial_balance(self, request):
        as_of_date = parse_date(request.query_params.get('as_of_date', '')) if request.query_params.get('as_of_date') else timezone.now().date()
        report = FinancialReportEngine.get_trial_balance(as_of_date)
        return Response(report)

    @extend_schema(
        summary='Profit & Loss (P&L) Statement',
        description='Generates Revenue, COGS, Gross Profit, Operating Expenses, and Net Profit for a date period.',
        parameters=[
            OpenApiParameter('start_date', str, required=False),
            OpenApiParameter('end_date', str, required=False)
        ]
    )
    @action(detail=False, methods=['get'], url_path='profit-loss')
    def profit_and_loss(self, request):
        start_date = parse_date(request.query_params.get('start_date', '')) if request.query_params.get('start_date') else None
        end_date = parse_date(request.query_params.get('end_date', '')) if request.query_params.get('end_date') else None
        report = FinancialReportEngine.get_profit_and_loss_statement(start_date, end_date)
        return Response(report)

    @extend_schema(
        summary='Balance Sheet Statement',
        description='Generates Balance Sheet: Total Assets == Total Liabilities + Total Equity (including Net Profit).',
        parameters=[
            OpenApiParameter('as_of_date', str, required=False)
        ]
    )
    @action(detail=False, methods=['get'], url_path='balance-sheet')
    def balance_sheet(self, request):
        as_of_date = parse_date(request.query_params.get('as_of_date', '')) if request.query_params.get('as_of_date') else timezone.now().date()
        report = FinancialReportEngine.get_balance_sheet(as_of_date)
        return Response(report)

    @extend_schema(
        summary='VAT & Tax Sub-ledger Report',
        description='Generates government Mushak compliance summary of Output VAT collected vs Input VAT paid.',
        parameters=[
            OpenApiParameter('start_date', str, required=False),
            OpenApiParameter('end_date', str, required=False)
        ]
    )
    @action(detail=False, methods=['get'], url_path='vat-tax-report')
    def vat_tax_report(self, request):
        start_date = parse_date(request.query_params.get('start_date', '')) if request.query_params.get('start_date') else None
        end_date = parse_date(request.query_params.get('end_date', '')) if request.query_params.get('end_date') else None
        report = FinancialReportEngine.get_vat_report(start_date, end_date)
        return Response(report)
