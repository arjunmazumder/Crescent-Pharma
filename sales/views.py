from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema
from sales.models import Customer, CustomerOrder, PaymentMethod
from sales.services import OrderService
from sales.serializers import (
    CustomerSerializer, CustomerOrderSerializer,
    CustomerOrderCreateSerializer, OrderCancelSerializer
)


@extend_schema(tags=['Customers & Sales Orders'])
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().prefetch_related('orders').order_by('-id')
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['name', 'customer_code', 'proprietor_name', 'phone', 'drug_license_no', 'trade_license_no', 'city']
    filterset_fields = ['customer_type', 'is_active', 'city']
    ordering_fields = ['id', 'name', 'customer_code', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Get Order History for a Specific Customer'
    )
    @action(detail=True, methods=['get'], url_path='orders')
    def orders(self, request, pk=None):
        customer = self.get_object()
        orders_qs = customer.orders.all().select_related('customer', 'created_by').prefetch_related('items__product', 'items__warehouse').order_by('-order_date', '-id')
        page = self.paginate_queryset(orders_qs)
        if page is not None:
            serializer = CustomerOrderSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CustomerOrderSerializer(orders_qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Get Customer Orders Summary & Lifetime Metrics'
    )
    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        customer = self.get_object()
        summary_data = OrderService.get_customer_summary(customer)
        return Response(summary_data, status=status.HTTP_200_OK)


@extend_schema(tags=['Customers & Sales Orders'])
class CustomerOrderViewSet(viewsets.ModelViewSet):
    queryset = CustomerOrder.objects.all().select_related('customer', 'created_by').prefetch_related('items__product', 'items__warehouse').order_by('-id')
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['order_number', 'customer__name', 'customer__customer_code', 'notes', 'shipping_address']
    filterset_fields = ['customer', 'status', 'payment_status', 'payment_method', 'order_date']
    ordering_fields = ['id', 'order_number', 'order_date', 'total_amount', 'created_at']
    ordering = ['-id']

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Create Customer Order (with multi-item products & automated billing)',
        description='Creates a customer sales order with multi-item products, automatic VAT & discount math, and compliance checks.',
        request=CustomerOrderCreateSerializer,
        responses={201: CustomerOrderSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = CustomerOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            customer = Customer.objects.get(id=data['customer_id'])
            order = OrderService.create_order(
                customer=customer,
                items_data=data['items'],
                user=request.user,
                order_date=data.get('order_date'),
                delivery_date=data.get('delivery_date'),
                discount_percentage=data.get('discount_percentage', 0),
                discount_flat=data.get('discount_flat', 0),
                payment_method=data.get('payment_method', PaymentMethod.CASH),
                shipping_address=data.get('shipping_address', ''),
                notes=data.get('notes', '')
            )
            return Response(CustomerOrderSerializer(order).data, status=status.HTTP_201_CREATED)
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Confirm Customer Order',
        description='Transitions order status from PENDING to CONFIRMED and reserves warehouse inventory stock.',
        request=None,
        responses={200: CustomerOrderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            updated_order = OrderService.confirm_order(order=order, user=request.user)
            return Response({
                'message': f"Order {order.order_number} confirmed successfully.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Deliver Customer Order',
        description='Marks order as DELIVERED, reduces physical stock from warehouse batches, and triggers sales commission.',
        request=None,
        responses={200: CustomerOrderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='deliver')
    def deliver(self, request, pk=None):
        order = self.get_object()
        try:
            updated_order = OrderService.deliver_order(order=order, user=request.user)
            return Response({
                'message': f"Order {order.order_number} marked as DELIVERED. Inventory stock deducted.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Customers & Sales Orders'],
        summary='Cancel Customer Order',
        description='Cancels the order, releases any reserved stock back to warehouse, and records cancellation reason.',
        request=OrderCancelSerializer,
        responses={200: CustomerOrderSerializer}
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        order = self.get_object()
        serializer = OrderCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reason = serializer.validated_data['cancellation_reason']
        try:
            updated_order = OrderService.cancel_order(order=order, reason=reason, user=request.user)
            return Response({
                'message': f"Order {order.order_number} cancelled successfully.",
                'data': CustomerOrderSerializer(updated_order).data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
