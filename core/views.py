import calendar
import datetime
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, Q, Sum, When
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.contrib.auth.models import Permission

from core.models import Lookup, Role, CompanyProfile
from core.serializers import LookupSerializer, RoleSerializer, CompanyProfileSerializer
from users.serializers import PermissionSerializer

from accounting.models import JournalEntry, AccountType, VoucherStatus, PaymentRecord
from sales.models import Customer, CustomerOrder, OrderStatus as SalesOrderStatus


@extend_schema(tags=['Core / Lookups'])
class LookupViewSet(viewsets.ModelViewSet):
    queryset = Lookup.objects.all().order_by('name', 'value')
    serializer_class = LookupSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'value']
    filterset_fields = ['name', 'is_active']
    ordering_fields = ['id', 'name', 'value', 'created_at']
    ordering = ['name', 'value']


@extend_schema(tags=['Core / Roles & Permissions'])
class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().prefetch_related(
        'permissions__content_type'
    ).order_by('role_name')
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['role_name']
    filterset_fields = ['is_active']
    ordering_fields = ['id', 'role_name', 'created_at']
    ordering = ['role_name']


@extend_schema(tags=['Core / Roles & Permissions'])
class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all().select_related('content_type').order_by('content_type__app_label', 'codename')
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'codename', 'content_type__app_label', 'content_type__model']
    filterset_fields = ['content_type__app_label', 'content_type__model']
    ordering_fields = ['id', 'name', 'codename', 'content_type__app_label']
    ordering = ['content_type__app_label', 'codename']


# -----------------------------------------------------------------------------
# Company Profile & Dashboard
# -----------------------------------------------------------------------------

@extend_schema(tags=['Core / Company Profile'])
class CompanyProfileViewSet(viewsets.ModelViewSet):
    """
    The selling entity's own details, printed on every invoice and report.
    Effectively a singleton: saving a profile as active deactivates the others.
    """
    queryset = CompanyProfile.objects.all().order_by('-is_active', '-id')
    serializer_class = CompanyProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'legal_name', 'business_identification_number',
                     'tax_identification_number', 'drug_license_number']
    filterset_fields = ['is_active', 'city', 'country']

    @extend_schema(
        summary='Get the Active Company Profile',
        description='Returns the profile documents should print. 404 when none has been set up yet.',
        responses={200: CompanyProfileSerializer}
    )
    @action(detail=False, methods=['get'], url_path='active')
    def active(self, request):
        profile = CompanyProfile.get_active()
        if not profile:
            return Response(
                {'error': 'No company profile has been set up yet. Create one before printing documents.'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(CompanyProfileSerializer(profile).data)


@extend_schema(tags=['Core / Dashboard'])
class DashboardViewSet(viewsets.ViewSet):
    """
    Company-wide figures for the landing screen.

    Income is money actually collected (PaymentRecord), not invoiced value —
    those differ whenever an order is delivered on credit, and the dashboard
    should show cash that arrived. Sales value is reported alongside it so the
    gap is visible rather than hidden.

    Expense comes from the general ledger rather than any single module, so it
    counts every posted cost: purchases, payroll, allowances, damage write-offs.
    """
    permission_classes = [permissions.IsAuthenticated]

    EXPENSE_PREFIXES = ('5', '6')

    @staticmethod
    def _collected_between(start, end):
        total = PaymentRecord.objects.filter(
            payment_type='RECEIPT', payment_date__gte=start, payment_date__lte=end
        ).aggregate(total=Sum('amount'))['total']
        return (total or Decimal('0.00')).quantize(Decimal('0.01'))

    @staticmethod
    def _sales_between(start, end):
        agg = CustomerOrder.objects.filter(
            order_date__gte=start, order_date__lte=end
        ).exclude(status=SalesOrderStatus.CANCELLED).aggregate(
            total=Sum('total_amount'), orders=Count('id')
        )
        total = (agg['total'] or Decimal('0.00')).quantize(Decimal('0.01'))
        return total, agg['orders'] or 0

    @staticmethod
    def _expense_between(start, end):
        """
        Net debits on expense accounts for the period. Credits are subtracted so
        a reversal cancels the original rather than inflating the figure.
        """
        entries = JournalEntry.objects.filter(
            account__account_type=AccountType.EXPENSE,
            voucher__status=VoucherStatus.POSTED,
            voucher__voucher_date__gte=start,
            voucher__voucher_date__lte=end,
        )
        agg = entries.aggregate(dr=Sum('debit_amount'), cr=Sum('credit_amount'))
        total = (agg['dr'] or Decimal('0.00')) - (agg['cr'] or Decimal('0.00'))
        return total.quantize(Decimal('0.01'))

    @extend_schema(
        summary='Dashboard Summary (today and this month)',
        description='Today\'s customers, income, expense, plus the running month-to-date figures.',
        parameters=[
            OpenApiParameter('date', str, required=False,
                             description='Treat this date as "today" (YYYY-MM-DD). Defaults to today.'),
        ]
    )
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        date_param = request.query_params.get('date')
        today = parse_date(date_param) if date_param else timezone.now().date()
        if not today:
            return Response({'error': 'Invalid date. Use YYYY-MM-DD.'},
                            status=status.HTTP_400_BAD_REQUEST)

        month_start = today.replace(day=1)

        # Today falls inside the month-to-date window, so each figure is taken
        # from one pass over that window with a conditional sum for the "today"
        # slice. Querying the two ranges separately doubled the round trips.
        zero = Decimal('0.00')
        money = DecimalField(max_digits=18, decimal_places=2)

        def today_only(field, when):
            return Sum(Case(When(when, then=field), default=zero, output_field=money))

        sales_agg = CustomerOrder.objects.filter(
            order_date__gte=month_start, order_date__lte=today
        ).exclude(status=SalesOrderStatus.CANCELLED).aggregate(
            month_total=Sum('total_amount'),
            month_orders=Count('id'),
            today_total=today_only('total_amount', Q(order_date=today)),
            today_orders=Count('id', filter=Q(order_date=today)),
        )

        income_agg = PaymentRecord.objects.filter(
            payment_type='RECEIPT', payment_date__gte=month_start, payment_date__lte=today
        ).aggregate(
            month_total=Sum('amount'),
            today_total=today_only('amount', Q(payment_date=today)),
        )

        expense_agg = JournalEntry.objects.filter(
            account__account_type=AccountType.EXPENSE,
            voucher__status=VoucherStatus.POSTED,
            voucher__voucher_date__gte=month_start,
            voucher__voucher_date__lte=today,
        ).aggregate(
            month_dr=Sum('debit_amount'), month_cr=Sum('credit_amount'),
            today_dr=today_only('debit_amount', Q(voucher__voucher_date=today)),
            today_cr=today_only('credit_amount', Q(voucher__voucher_date=today)),
        )

        def q(value):
            return (value or zero).quantize(zero)

        today_sales = q(sales_agg['today_total'])
        month_sales = q(sales_agg['month_total'])
        today_order_count = sales_agg['today_orders'] or 0
        month_order_count = sales_agg['month_orders'] or 0

        today_income = q(income_agg['today_total'])
        month_income = q(income_agg['month_total'])

        # Credits are subtracted so a reversal cancels the original entry.
        today_expense = q((expense_agg['today_dr'] or zero) - (expense_agg['today_cr'] or zero))
        month_expense = q((expense_agg['month_dr'] or zero) - (expense_agg['month_cr'] or zero))

        # Two different questions get asked of "today's customers": how many
        # bought, and how many joined. Both are returned rather than guessed at.
        customers_ordered_today = CustomerOrder.objects.filter(
            order_date=today
        ).exclude(status=SalesOrderStatus.CANCELLED).values('customer_id').distinct().count()
        new_customers_today = Customer.objects.filter(created_at__date=today).count()

        return Response({
            'date': str(today),
            'today': {
                'customersOrdered': customers_ordered_today,
                'newCustomers': new_customers_today,
                'ordersCount': today_order_count,
                'salesValue': str(today_sales),
                'incomeCollected': str(today_income),
                'expense': str(today_expense),
                'netCashFlow': str((today_income - today_expense).quantize(Decimal('0.01'))),
            },
            'month': {
                'monthStart': str(month_start),
                'ordersCount': month_order_count,
                'salesValue': str(month_sales),
                'incomeCollected': str(month_income),
                'expense': str(month_expense),
                'netCashFlow': str((month_income - month_expense).quantize(Decimal('0.01'))),
                'outstanding': str((month_sales - month_income).quantize(Decimal('0.01'))),
            },
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Sales vs Expense Series (for the chart)',
        description='One point per month, oldest first, ending with the current month.',
        parameters=[
            OpenApiParameter('months', int, required=False,
                             description='How many months to return, 1-36. Defaults to 12.'),
        ]
    )
    @action(detail=False, methods=['get'], url_path='sales-vs-expense')
    def sales_vs_expense(self, request):
        raw = request.query_params.get('months', 12)
        try:
            months = max(1, min(36, int(raw)))
        except (TypeError, ValueError):
            return Response({'error': 'months must be a whole number between 1 and 36.'},
                            status=status.HTTP_400_BAD_REQUEST)

        today = timezone.now().date()

        # Build the month list first, then fetch the whole window in three
        # grouped queries. Asking per month meant months x 4 round trips, which
        # against a remote database dominated the response time.
        window = []
        for offset in range(months - 1, -1, -1):
            year, month = today.year, today.month - offset
            while month <= 0:
                month += 12
                year -= 1
            window.append((year, month))

        first_year, first_month = window[0]
        last_year, last_month = window[-1]
        range_start = datetime.date(first_year, first_month, 1)
        range_end = datetime.date(
            last_year, last_month, calendar.monthrange(last_year, last_month)[1]
        )

        def by_month(rows):
            """Index grouped rows as {(year, month): row} for O(1) lookup."""
            return {(r['bucket'].year, r['bucket'].month): r for r in rows}

        sales_rows = by_month(
            CustomerOrder.objects
            .filter(order_date__gte=range_start, order_date__lte=range_end)
            .exclude(status=SalesOrderStatus.CANCELLED)
            .annotate(bucket=TruncMonth('order_date'))
            .values('bucket')
            .annotate(total=Sum('total_amount'), orders=Count('id'))
        )

        income_rows = by_month(
            PaymentRecord.objects
            .filter(payment_type='RECEIPT',
                    payment_date__gte=range_start, payment_date__lte=range_end)
            .annotate(bucket=TruncMonth('payment_date'))
            .values('bucket')
            .annotate(total=Sum('amount'))
        )

        expense_rows = by_month(
            JournalEntry.objects
            .filter(account__account_type=AccountType.EXPENSE,
                    voucher__status=VoucherStatus.POSTED,
                    voucher__voucher_date__gte=range_start,
                    voucher__voucher_date__lte=range_end)
            .annotate(bucket=TruncMonth('voucher__voucher_date'))
            .values('bucket')
            .annotate(dr=Sum('debit_amount'), cr=Sum('credit_amount'))
        )

        zero = Decimal('0.00')
        points = []
        for year, month in window:
            key = (year, month)
            srow = sales_rows.get(key) or {}
            irow = income_rows.get(key) or {}
            erow = expense_rows.get(key) or {}

            sales = (srow.get('total') or zero).quantize(zero)
            income = (irow.get('total') or zero).quantize(zero)
            # Credits are subtracted so a reversal cancels the original entry
            # rather than inflating the figure.
            expense = ((erow.get('dr') or zero) - (erow.get('cr') or zero)).quantize(zero)

            points.append({
                'year': year,
                'month': month,
                'label': datetime.date(year, month, 1).strftime('%b %Y'),
                'salesValue': str(sales),
                'incomeCollected': str(income),
                'expense': str(expense),
                'profit': str((sales - expense).quantize(zero)),
                'ordersCount': srow.get('orders') or 0,
            })

        profile = CompanyProfile.get_active()
        return Response({
            'months': months,
            'currency': profile.default_currency if profile else 'BDT',
            'series': points,
        }, status=status.HTTP_200_OK)
