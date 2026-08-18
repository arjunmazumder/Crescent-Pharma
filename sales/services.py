from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from .models import Customer, CustomerOrder, CustomerOrderItem, OrderStatus, PaymentStatus, PaymentMethod
from inventory.models import Product, Warehouse, StockLevel
from inventory.services import InventoryService


class OrderService:
    @staticmethod
    def create_order(
        customer,
        items_data,
        user=None,
        order_date=None,
        delivery_date=None,
        discount_percentage=Decimal('0.00'),
        discount_flat=Decimal('0.00'),
        payment_method=PaymentMethod.CASH,
        shipping_address="",
        notes=""
    ):
        """
        Creates a new CustomerOrder with nested CustomerOrderItems, performing
        compliance checks, drug license validation, and financial calculations.
        """
        # 1. Customer active check
        if not customer.is_active:
            raise ValueError(f"Cannot create order: Customer '{customer.name}' is inactive.")

        # 2. Drug license expiry compliance check
        today = timezone.now().date()
        if customer.drug_license_expiry_date and customer.drug_license_expiry_date < today:
            raise ValueError(
                f"Cannot create order: Customer's Drug License expired on {customer.drug_license_expiry_date}. "
                "Please renew DGDA license before placing new orders."
            )

        if not items_data:
            raise ValueError("An order must contain at least one product item.")

        discount_percentage = Decimal(str(discount_percentage or 0))
        discount_flat = Decimal(str(discount_flat or 0))

        with transaction.atomic():
            order = CustomerOrder(
                customer=customer,
                order_date=order_date or today,
                delivery_date=delivery_date,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.UNPAID,
                payment_method=payment_method,
                discount_percentage=discount_percentage,
                discount_flat=discount_flat,
                shipping_address=shipping_address or customer.address or "",
                notes=notes or "",
                created_by=user
            )
            order.save()

            total_subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')

            for item_dict in items_data:
                product_id = item_dict.get('product_id') or item_dict.get('productId')
                try:
                    product = Product.objects.get(id=product_id, is_active=True)
                except Product.DoesNotExist:
                    raise ValueError(f"Product with ID {product_id} not found or inactive.")

                warehouse_id = item_dict.get('warehouse_id') or item_dict.get('warehouseId')
                warehouse = None
                if warehouse_id:
                    try:
                        warehouse = Warehouse.objects.get(id=warehouse_id, is_active=True)
                    except Warehouse.DoesNotExist:
                        raise ValueError(f"Warehouse with ID {warehouse_id} not found or inactive.")

                batch_number = item_dict.get('batch_number') or item_dict.get('batchNumber') or ''
                quantity = int(item_dict.get('quantity', 1))
                if quantity <= 0:
                    raise ValueError("Item quantity must be greater than zero.")

                # Atomically reserve stock if warehouse and batch are provided
                if warehouse and batch_number:
                    InventoryService.reserve_stock(
                        product=product,
                        warehouse=warehouse,
                        batch_number=batch_number,
                        quantity=quantity
                    )

                unit_price = Decimal(str(item_dict.get('unit_price') or item_dict.get('unitPrice') or product.selling_price))
                vat_pct = Decimal(str(item_dict.get('vat_percentage') if item_dict.get('vat_percentage') is not None else item_dict.get('vatPercentage') if item_dict.get('vatPercentage') is not None else product.vat_percentage))
                item_discount_pct = Decimal(str(item_dict.get('discount_percentage') or item_dict.get('discountPercentage') or 0))

                line_subtotal = (Decimal(quantity) * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                line_discount = (line_subtotal * item_discount_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                taxable_amount = line_subtotal - line_discount
                line_vat = (taxable_amount * vat_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                line_total = (taxable_amount + line_vat).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                CustomerOrderItem.objects.create(
                    order=order,
                    product=product,
                    warehouse=warehouse,
                    batch_number=batch_number,
                    quantity=quantity,
                    unit_price=unit_price,
                    vat_percentage=vat_pct,
                    discount_percentage=item_discount_pct,
                    total_price=line_total
                )

                total_subtotal += line_subtotal
                total_tax += line_vat

            # Calculate order-level discount
            order_pct_discount = (total_subtotal * discount_percentage / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            overall_discount = order_pct_discount + discount_flat
            net_total = max(Decimal('0.00'), total_subtotal - overall_discount + total_tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            order.subtotal = total_subtotal
            order.tax_amount = total_tax
            order.total_amount = net_total
            order.save()

            return order

    @staticmethod
    def confirm_order(order, user=None):
        """
        Marks the order as CONFIRMED.
        """
        if order.status not in [OrderStatus.DRAFT, OrderStatus.PENDING]:
            raise ValueError(f"Cannot confirm order with current status '{order.status}'.")

        order.status = OrderStatus.CONFIRMED
        order.save()
        return order

    @staticmethod
    def deliver_order(order, user=None):
        """
        Marks the order as DELIVERED and atomically deducts physical stock
        and releases reservation via InventoryService.record_stock_movement ('OUT').
        """
        if order.status == OrderStatus.DELIVERED:
            raise ValueError("Order is already marked as DELIVERED.")
        if order.status == OrderStatus.CANCELLED:
            raise ValueError("Cannot deliver a CANCELLED order.")

        with transaction.atomic():
            for item in order.items.all():
                if item.warehouse:
                    batch = item.batch_number or "DEFAULT"
                    InventoryService.record_stock_movement(
                        product=item.product,
                        warehouse=item.warehouse,
                        batch_number=batch,
                        movement_type='OUT',
                        quantity=item.quantity,
                        reference_no=order.order_number,
                        notes=f"Sales fulfillment for {order.customer.name} (Order: {order.order_number})",
                        user=user,
                        is_reserved=True
                    )

            order.status = OrderStatus.DELIVERED
            if not order.delivery_date:
                order.delivery_date = timezone.now().date()
            order.save()

            return order

    @staticmethod
    def cancel_order(order, reason, user=None):
        """
        Cancels the order with a mandatory reason. If previously DELIVERED,
        automatically restores deducted inventory via 'RETURN' movement.
        If pending or confirmed, releases reserved stock.
        """
        if not reason or not str(reason).strip():
            raise ValueError("Cancellation reason is mandatory when cancelling an order.")

        if order.status == OrderStatus.CANCELLED:
            raise ValueError("Order is already CANCELLED.")

        with transaction.atomic():
            # If the order was already fulfilled/delivered, rollback the physical inventory
            if order.status == OrderStatus.DELIVERED:
                for item in order.items.all():
                    if item.warehouse:
                        batch = item.batch_number or "DEFAULT"
                        InventoryService.record_stock_movement(
                            product=item.product,
                            warehouse=item.warehouse,
                            batch_number=batch,
                            movement_type='RETURN',
                            quantity=item.quantity,
                            reference_no=order.order_number,
                            notes=f"Order Cancelled rollback: {reason}",
                            user=user
                        )
            else:
                # If the order was pending / confirmed, release the reserved stock
                for item in order.items.all():
                    if item.warehouse and item.batch_number:
                        InventoryService.release_reserved_stock(
                            product=item.product,
                            warehouse=item.warehouse,
                            batch_number=item.batch_number,
                            quantity=item.quantity
                        )

            order.status = OrderStatus.CANCELLED
            order.cancellation_reason = reason
            order.save()

            return order

    @staticmethod
    def get_customer_summary(customer):
        """
        Computes customer ordering analytics and statistics.
        """
        orders = customer.orders.all()
        total_orders = orders.count()
        delivered_orders = orders.filter(status=OrderStatus.DELIVERED)
        pending_orders = orders.filter(status__in=[OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.SHIPPED]).count()
        cancelled_orders = orders.filter(status=OrderStatus.CANCELLED).count()

        total_spent = sum(Decimal(str(o.total_amount)) for o in delivered_orders)
        last_order = orders.order_by('-order_date').first()

        return {
            'customer_id': customer.id,
            'customer_code': customer.customer_code,
            'customer_name': customer.name,
            'total_orders': total_orders,
            'delivered_orders': delivered_orders.count(),
            'pending_orders': pending_orders,
            'cancelled_orders': cancelled_orders,
            'total_spent': total_spent.quantize(Decimal('0.01')),
            'last_order_date': last_order.order_date if last_order else None
        }
