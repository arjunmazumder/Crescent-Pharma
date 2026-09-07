import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from .models import Customer, CustomerOrder, CustomerOrderItem, OrderStatus, PaymentStatus, PaymentMethod
from inventory.models import Product, Warehouse, StockLevel
from inventory.services import InventoryService

logger = logging.getLogger(__name__)


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
        is_branch_booking=False,
        delivery_branch=None,
        booking_notes="",
        notes="",
        as_draft=False
    ):
        """
        Creates a new CustomerOrder with nested CustomerOrderItems, performing
        compliance checks, drug license validation, inter-branch booking routing, and financial calculations.

        as_draft saves an in-progress bill the field officer can come back to.
        A draft deliberately reserves no stock: a bill left open mid-negotiation
        must not hold inventory that another customer could have bought.
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
                status=OrderStatus.DRAFT if as_draft else OrderStatus.PENDING,
                payment_status=PaymentStatus.UNPAID,
                payment_method=payment_method,
                discount_percentage=discount_percentage,
                discount_flat=discount_flat,
                shipping_address=shipping_address or customer.address or "",
                is_branch_booking=is_branch_booking,
                delivery_branch=delivery_branch,
                booking_notes=booking_notes or "",
                notes=notes or "",
                created_by=user
            )
            order.save()

            OrderService._build_items(
                order, items_data,
                reserve=not as_draft,
                fallback_warehouse=delivery_branch if is_branch_booking else None
            )
            OrderService._recalculate_totals(order)
            order.save()

            return order

    @staticmethod
    def _build_items(order, items_data, reserve=True, fallback_warehouse=None):
        """
        Creates the order's line items and prices each one.

        Shared by order creation and draft editing so the two can never drift
        into pricing the same basket differently.
        """
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
            elif fallback_warehouse:
                warehouse = fallback_warehouse

            batch_number = item_dict.get('batch_number') or item_dict.get('batchNumber') or ''
            quantity = int(item_dict.get('quantity', 1))
            if quantity <= 0:
                raise ValueError("Item quantity must be greater than zero.")

            if reserve and warehouse and batch_number:
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

    @staticmethod
    def _recalculate_totals(order):
        """Recomputes subtotal, VAT and net total from whatever lines exist now."""
        total_subtotal = Decimal('0.00')
        total_tax = Decimal('0.00')

        for item in order.items.all():
            line_subtotal = (Decimal(item.quantity) * Decimal(str(item.unit_price))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            line_discount = (line_subtotal * Decimal(str(item.discount_percentage)) / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            taxable = line_subtotal - line_discount
            line_vat = (taxable * Decimal(str(item.vat_percentage)) / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            total_subtotal += line_subtotal
            total_tax += line_vat

        order_pct_discount = (
            total_subtotal * Decimal(str(order.discount_percentage)) / Decimal('100')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        overall_discount = order_pct_discount + Decimal(str(order.discount_flat))

        order.subtotal = total_subtotal
        order.tax_amount = total_tax
        order.total_amount = max(
            Decimal('0.00'), total_subtotal - overall_discount + total_tax
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return order

    @staticmethod
    def confirm_order(order, user=None):
        """
        Marks the order as CONFIRMED.

        A draft reserved nothing when it was saved, so its stock is reserved
        here. Without this a finalised draft would ship goods it never held,
        and two drafts could promise the same batch.
        """
        if order.status not in [OrderStatus.DRAFT, OrderStatus.PENDING]:
            raise ValueError(f"Cannot confirm order with current status '{order.status}'.")

        was_draft = order.status == OrderStatus.DRAFT

        with transaction.atomic():
            if was_draft:
                for item in order.items.select_related('product', 'warehouse'):
                    if item.warehouse and item.batch_number:
                        InventoryService.reserve_stock(
                            product=item.product,
                            warehouse=item.warehouse,
                            batch_number=item.batch_number,
                            quantity=item.quantity
                        )

            order.status = OrderStatus.CONFIRMED
            order.save()

        return order

    @staticmethod
    def update_draft(
        order,
        items_data=None,
        discount_percentage=None,
        discount_flat=None,
        payment_method=None,
        shipping_address=None,
        notes=None,
        delivery_date=None
    ):
        """
        Edits a saved draft and recomputes its totals.

        Only drafts can be edited: once an order is confirmed its stock is
        reserved and its figures may already be quoted to the customer.
        """
        if order.status != OrderStatus.DRAFT:
            raise ValueError(
                f"Only DRAFT orders can be edited. Order {order.order_number} is {order.status}."
            )

        with transaction.atomic():
            if discount_percentage is not None:
                order.discount_percentage = Decimal(str(discount_percentage))
            if discount_flat is not None:
                order.discount_flat = Decimal(str(discount_flat))
            if payment_method is not None:
                order.payment_method = payment_method
            if shipping_address is not None:
                order.shipping_address = shipping_address
            if notes is not None:
                order.notes = notes
            if delivery_date is not None:
                order.delivery_date = delivery_date

            if items_data is not None:
                if not items_data:
                    raise ValueError("A draft must keep at least one product item.")
                # Rebuilt rather than patched, so a removed line cannot linger.
                order.items.all().delete()
                OrderService._build_items(order, items_data)

            OrderService._recalculate_totals(order)
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

            # Auto-post to Accounting General Ledger.
            # Tolerated so delivery still succeeds when fiscal periods are
            # unseeded, but never silently: an unposted sale must be findable.
            try:
                from accounting.services import AccountingIntegrationService
                AccountingIntegrationService.post_sales_order_delivery(order=order, user=user)
            except ValueError:
                logger.exception(
                    "Failed to post sales voucher for order %s. "
                    "The delivery was recorded but the General Ledger was not updated.",
                    order.order_number
                )

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
