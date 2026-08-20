from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter

from marketing.models import SalesTarget, ProductTargetItem, PeriodType, TargetType, TargetStatus
from marketing.services import TargetService
from marketing.serializers import (
    SalesTargetSerializer, SalesTargetCreateSerializer
)

User = get_user_model()


@extend_schema(tags=['Marketing & Sales Targets'])
class SalesTargetViewSet(viewsets.ModelViewSet):
    queryset = SalesTarget.objects.all().select_related('assigned_to', 'assigned_by').prefetch_related('product_items__product').order_by('-start_date', '-created_at')
    serializer_class = SalesTargetSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['title', 'target_code', 'assigned_to__username', 'assigned_to__employee_id', 'territory_name', 'notes']
    filterset_fields = ['assigned_to', 'period_type', 'target_type', 'status', 'start_date', 'end_date']
    ordering_fields = ['id', 'start_date', 'end_date', 'total_target_amount', 'created_at']
    ordering = ['-start_date', '-created_at']

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return self.queryset.all()
        return self.queryset.filter(assigned_to=self.request.user)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Create Smart Sales Target with Auto-Priced Product Items',
        description='Creates a smart sales target for an MPO across a date range. Product unit prices and line-item amounts are automatically snapshot from product catalog if not provided.',
        request=SalesTargetCreateSerializer,
        responses={201: SalesTargetSerializer}
    )
    def create(self, request, *args, **kwargs):
        from inventory.models import Product
        serializer = SalesTargetCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        assigned_to_id = data['assigned_to_id']

        try:
            assigned_user = User.objects.get(id=assigned_to_id)
        except User.DoesNotExist:
            return Response({'error': f'Assigned employee with ID {assigned_to_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        items_data = data.get('items', [])
        total_target_amt = data.get('total_target_amount', 0)

        with transaction.atomic():
            target = SalesTarget.objects.create(
                title=data['title'],
                assigned_to=assigned_user,
                assigned_by=request.user,
                period_type=data.get('period_type', PeriodType.MONTHLY),
                start_date=data['start_date'],
                end_date=data['end_date'],
                target_type=data.get('target_type', TargetType.HYBRID),
                total_target_amount=total_target_amt,
                status=data.get('status', TargetStatus.ACTIVE),
                territory_name=data.get('territory_name', ''),
                notes=data.get('notes', '')
            )

            computed_items_total = 0
            for item in items_data:
                product_id = item['product_id']
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    raise ValueError(f"Product with ID {product_id} not found.")

                target_item = ProductTargetItem.objects.create(
                    sales_target=target,
                    product=product,
                    target_quantity=item['target_quantity'],
                    unit_price=item.get('unit_price')
                )
                computed_items_total += target_item.target_amount

            # If total_target_amount was 0 or not provided and items were given, auto-set header amount
            if (not total_target_amt or total_target_amt == 0) and computed_items_total > 0:
                target.total_target_amount = computed_items_total
                target.save(update_fields=['total_target_amount'])

        return Response(SalesTargetSerializer(target).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Live Real-time Target Achievement Breakdown with Filters',
        description='Computes real-time target achievement, product-wise actual sales vs targets, shift attendance compliance, and incentive tier qualification. Supports filtering by date range, product ID, and order status.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional evaluation start date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional evaluation end date (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='product_id', type=int, location=OpenApiParameter.QUERY, description='Filter breakdown for a specific product ID', required=False),
            OpenApiParameter(name='order_status', type=str, location=OpenApiParameter.QUERY, description='Filter order status (e.g. DELIVERED, CONFIRMED)', required=False),
        ]
    )
    @action(detail=True, methods=['get'], url_path='achievement')
    def achievement(self, request, pk=None):
        target = get_object_or_404(self.get_queryset(), pk=pk)
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        product_id_param = request.query_params.get('product_id') or request.query_params.get('productId')
        order_status = request.query_params.get('order_status') or request.query_params.get('orderStatus')

        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None
        product_id = int(product_id_param) if product_id_param and str(product_id_param).isdigit() else None

        achievement_data = TargetService.calculate_target_achievement(
            target=target,
            start_date=start_date,
            end_date=end_date,
            product_id=product_id,
            order_status=order_status
        )
        return Response(achievement_data, status=status.HTTP_200_OK)


@extend_schema(tags=['Marketing & Sales Targets'])
class MarketingReportViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Logged-in MPO Live Achievement Scorecard',
        description='Returns the authenticated MPO performance scorecard across assigned targets with product breakdowns and shift compliance.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='my-achievement')
    def my_achievement(self, request):
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        scorecard = TargetService.get_mpo_scorecard(user=request.user, start_date=start_date, end_date=end_date)
        return Response(scorecard, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Specific MPO Performance Scorecard (Admin / Manager)',
        description='Returns comprehensive performance metrics, target achievement, and dual-shift attendance records for a specific MPO.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path=r'mpo/(?P<user_id>\d+)')
    def mpo_scorecard(self, request, user_id=None):
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': f'Employee with ID {user_id} not found.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.id != target_user.id and not (request.user.is_superuser or request.user.is_staff):
            return Response(
                {'error': 'Permission denied: Only managers or administrators can view other employees scorecards.'},
                status=status.HTTP_403_FORBIDDEN
            )

        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        scorecard = TargetService.get_mpo_scorecard(user=target_user, start_date=start_date, end_date=end_date)
        return Response(scorecard, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Marketing & Sales Targets'],
        summary='Get Consolidated Marketing Team Report & Leaderboard',
        description='Returns company-wide consolidated sales target report ranking all MPOs by achievement percentage, team revenue totals, and territory metrics.',
        parameters=[
            OpenApiParameter(name='start_date', type=str, location=OpenApiParameter.QUERY, description='Optional start date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='end_date', type=str, location=OpenApiParameter.QUERY, description='Optional end date filter (YYYY-MM-DD)', required=False),
            OpenApiParameter(name='period_type', type=str, location=OpenApiParameter.QUERY, description='Optional period filter (MONTHLY, QUARTERLY, CAMPAIGN, etc.)', required=False),
        ]
    )
    @action(detail=False, methods=['get'], url_path='consolidated')
    def consolidated(self, request):
        start_date_str = request.query_params.get('start_date') or request.query_params.get('startDate')
        end_date_str = request.query_params.get('end_date') or request.query_params.get('endDate')
        period_type = request.query_params.get('period_type') or request.query_params.get('periodType')
        start_date = parse_date(str(start_date_str).strip()) if start_date_str else None
        end_date = parse_date(str(end_date_str).strip()) if end_date_str else None

        report = TargetService.get_consolidated_team_report(start_date=start_date, end_date=end_date, period_type=period_type)
        return Response(report, status=status.HTTP_200_OK)

