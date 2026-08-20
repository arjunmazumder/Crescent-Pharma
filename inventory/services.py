import datetime
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F, Q
from django.utils import timezone
from .models import Product, Warehouse, StockLevel, StockMovement


class InventoryService:
    @staticmethod
    def reserve_stock(product, warehouse, batch_number, quantity):
        """
        Atomically reserves stock for a pending/confirmed sales order.
        Increments reserved_quantity on the StockLevel.
        """
        if quantity <= 0:
            return None
        with transaction.atomic():
            stock_level, _ = StockLevel.objects.select_for_update().get_or_create(
                product=product,
                warehouse=warehouse,
                batch_number=batch_number,
                defaults={'quantity': 0, 'reserved_quantity': 0}
            )
            if quantity > stock_level.available_quantity:
                raise ValueError(
                    f"Insufficient available stock for {product.name} (Batch: {batch_number}) at {warehouse.name}. "
                    f"Requested: {quantity}, Available: {stock_level.available_quantity}."
                )
            stock_level.reserved_quantity += quantity
            stock_level.save()
            return stock_level

    @staticmethod
    def release_reserved_stock(product, warehouse, batch_number, quantity):
        """
        Atomically releases reserved stock (e.g. upon order cancellation).
        Decrements reserved_quantity on the StockLevel.
        """
        if quantity <= 0:
            return None
        with transaction.atomic():
            stock_level = StockLevel.objects.select_for_update().filter(
                product=product,
                warehouse=warehouse,
                batch_number=batch_number
            ).first()
            if stock_level:
                stock_level.reserved_quantity = max(0, stock_level.reserved_quantity - quantity)
                stock_level.save()
                return stock_level

    @staticmethod
    def record_stock_movement(
        product,
        warehouse,
        batch_number,
        movement_type,
        quantity,
        mfg_date=None,
        expiry_date=None,
        rack_location=None,
        reference_no="",
        notes="",
        user=None,
        is_reserved=False
    ):
        """
        Atomically records a stock transaction (IN, OUT, ADJUSTMENT, RETURN, DAMAGE)
        and updates or creates the corresponding StockLevel for the warehouse and batch.
        If is_reserved=True during OUT movement, also releases the reserved_quantity.
        """
        if quantity <= 0 and movement_type != 'ADJUSTMENT':
            raise ValueError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock_level, created = StockLevel.objects.select_for_update().get_or_create(
                product=product,
                warehouse=warehouse,
                batch_number=batch_number,
                defaults={
                    'mfg_date': mfg_date,
                    'expiry_date': expiry_date,
                    'rack_location': rack_location or '',
                    'quantity': 0,
                    'reserved_quantity': 0
                }
            )

            if mfg_date and not stock_level.mfg_date:
                stock_level.mfg_date = mfg_date
            if expiry_date and not stock_level.expiry_date:
                stock_level.expiry_date = expiry_date
            if rack_location:
                stock_level.rack_location = rack_location

            previous_stock = stock_level.quantity

            if movement_type in [StockMovement.MOVEMENT_TYPE_CHOICES['IN'], StockMovement.MOVEMENT_TYPE_CHOICES['RETURN'], 'IN', 'RETURN']:
                new_stock = previous_stock + quantity
            elif movement_type in [StockMovement.MOVEMENT_TYPE_CHOICES['OUT'], StockMovement.MOVEMENT_TYPE_CHOICES['DAMAGE'], 'OUT', 'DAMAGE']:
                if not is_reserved and quantity > stock_level.available_quantity:
                    raise ValueError(
                        f"Insufficient stock for {product.name} (Batch: {batch_number}) at {warehouse.name}. "
                        f"Requested: {quantity}, Available: {stock_level.available_quantity}."
                    )
                elif is_reserved and quantity > stock_level.quantity:
                    raise ValueError(
                        f"Insufficient physical stock for {product.name} (Batch: {batch_number}) at {warehouse.name}. "
                        f"Requested: {quantity}, Total In Warehouse: {stock_level.quantity}."
                    )
                new_stock = previous_stock - quantity
                if is_reserved:
                    stock_level.reserved_quantity = max(0, stock_level.reserved_quantity - quantity)
            elif movement_type in [StockMovement.MOVEMENT_TYPE_CHOICES['ADJUSTMENT'], 'ADJUSTMENT']:
                new_stock = quantity
                quantity = new_stock - previous_stock
            else:
                raise ValueError(f"Invalid movement type: {movement_type}")

            stock_level.quantity = new_stock
            stock_level.save()

            # Record movement log
            movement = StockMovement.objects.create(
                product=product,
                warehouse=warehouse,
                batch_number=batch_number,
                movement_type=movement_type,
                quantity=quantity,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reference_no=reference_no,
                notes=notes,
                created_by=user
            )

            return stock_level, movement

    @staticmethod
    def adjust_stock(product, warehouse, batch_number, new_quantity, reference_no="", notes="", user=None):
        """
        Reconciles physical inventory count with system records via Stock Adjustment.
        """
        return InventoryService.record_stock_movement(
            product=product,
            warehouse=warehouse,
            batch_number=batch_number,
            movement_type=StockMovement.MOVEMENT_TYPE_CHOICES['ADJUSTMENT'],
            quantity=new_quantity,
            reference_no=reference_no,
            notes=notes or "Physical stock audit reconciliation",
            user=user
        )

    @staticmethod
    def get_low_stock_products():
        """
        Returns products where total stock across all warehouses is less than or equal to min_stock_level.
        """
        products = Product.objects.filter(is_active=True).annotate(
            total_stock=Sum('stock_levels__quantity')
        )
        low_stock = []
        for p in products:
            current_total = p.total_stock or 0
            if current_total <= p.min_stock_level:
                low_stock.append({
                    'product': p,
                    'total_stock': current_total,
                    'min_stock_level': p.min_stock_level,
                    'deficit': p.min_stock_level - current_total
                })
        return low_stock

    @staticmethod
    def get_expiring_batches(days=90):
        """
        Returns stock batches that are expiring within the specified number of days.
        """
        today = timezone.now().date()
        cutoff_date = today + datetime.timedelta(days=days)
        return StockLevel.objects.filter(
            quantity__gt=0,
            expiry_date__isnull=False,
            expiry_date__lte=cutoff_date
        ).select_related('product', 'warehouse').order_by('expiry_date')

    @staticmethod
    def get_damage_and_loss_report(product_id=None, warehouse_id=None, start_date=None, end_date=None, incident_type=None):
        """
        Returns damaged and lost product records:
        1. Physical damages / write-offs (movement_type='DAMAGE')
        2. Audit shrinkage losses (movement_type='ADJUSTMENT' where new_stock < previous_stock or quantity < 0)
        with financial loss valuation, summaries, and breakdowns.
        """
        # Base query matching damage or negative adjustment
        damage_q = (
            Q(movement_type='DAMAGE') |
            Q(movement_type=StockMovement.MOVEMENT_TYPE_CHOICES['DAMAGE']) |
            Q(movement_type__icontains='damage') |
            Q(movement_type__icontains='expired')
        )
        shrinkage_q = (
            (
                Q(movement_type='ADJUSTMENT') |
                Q(movement_type=StockMovement.MOVEMENT_TYPE_CHOICES['ADJUSTMENT']) |
                Q(movement_type__icontains='adjustment')
            ) & (
                Q(quantity__lt=0) |
                Q(new_stock__lt=F('previous_stock'))
            )
        )

        if incident_type == 'DAMAGE':
            combined_q = damage_q
        elif incident_type == 'SHRINKAGE':
            combined_q = shrinkage_q
        else:
            combined_q = damage_q | shrinkage_q

        qs = StockMovement.objects.filter(combined_q).select_related('product', 'warehouse', 'created_by').order_by('-created_at')

        if product_id:
            qs = qs.filter(product_id=product_id)
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)

        total_damage_qty = 0
        total_shrinkage_qty = 0
        total_damage_loss = Decimal('0.00')
        total_shrinkage_loss = Decimal('0.00')

        damage_items = []
        warehouse_loss_map = {}

        for mov in qs:
            # Determine incident type
            is_damage = 'damage' in mov.movement_type.lower() or 'expired' in mov.movement_type.lower()
            inc_type = 'DAMAGE_WRITE_OFF' if is_damage else 'AUDIT_SHRINKAGE_LOSS'

            # Calculate units lost (always positive integer)
            if is_damage:
                lost_qty = abs(mov.quantity)
            else:
                if mov.previous_stock > mov.new_stock:
                    lost_qty = mov.previous_stock - mov.new_stock
                else:
                    lost_qty = abs(mov.quantity)

            cost_price = mov.product.purchase_price or mov.product.selling_price or Decimal('0.00')
            incident_loss = (Decimal(str(lost_qty)) * Decimal(str(cost_price))).quantize(Decimal('0.01'))

            if is_damage:
                total_damage_qty += lost_qty
                total_damage_loss += incident_loss
            else:
                total_shrinkage_qty += lost_qty
                total_shrinkage_loss += incident_loss

            wh_name = mov.warehouse.name if mov.warehouse else 'Unknown'
            if wh_name not in warehouse_loss_map:
                warehouse_loss_map[wh_name] = {
                    'warehouseId': mov.warehouse_id,
                    'warehouseName': wh_name,
                    'damagedQuantity': 0,
                    'shrinkageQuantity': 0,
                    'totalLostQuantity': 0,
                    'totalLossValue': Decimal('0.00')
                }
            if is_damage:
                warehouse_loss_map[wh_name]['damagedQuantity'] += lost_qty
            else:
                warehouse_loss_map[wh_name]['shrinkageQuantity'] += lost_qty
            warehouse_loss_map[wh_name]['totalLostQuantity'] += lost_qty
            warehouse_loss_map[wh_name]['totalLossValue'] += incident_loss

            damage_items.append({
                'id': mov.id,
                'incidentType': inc_type,
                'movementType': mov.movement_type,
                'productId': mov.product.id,
                'productName': mov.product.name,
                'genericName': mov.product.generic_name,
                'uniqueId': mov.product.unique_id,
                'unit': mov.product.unit,
                'warehouseId': mov.warehouse.id,
                'warehouseName': mov.warehouse.name,
                'batchNumber': mov.batch_number,
                'previousStock': mov.previous_stock,
                'newStock': mov.new_stock,
                'lostQuantity': lost_qty,
                'unitCostPrice': str(cost_price),
                'estimatedFinancialLoss': str(incident_loss),
                'referenceNo': mov.reference_no,
                'reasonNotes': mov.notes or ("Physical damage write-off" if is_damage else f"Audit physical count shrinkage (Prev: {mov.previous_stock}, Audited: {mov.new_stock})"),
                'reportedBy': mov.created_by.username if mov.created_by else None,
                'reportedAt': mov.created_at.isoformat()
            })

        warehouse_breakdown = [
            {
                'warehouseId': v['warehouseId'],
                'warehouseName': v['warehouseName'],
                'damagedQuantity': v['damagedQuantity'],
                'shrinkageQuantity': v['shrinkageQuantity'],
                'totalLostQuantity': v['totalLostQuantity'],
                'totalLossValue': str(v['totalLossValue'].quantize(Decimal('0.01')))
            }
            for v in warehouse_loss_map.values()
        ]

        total_loss = (total_damage_loss + total_shrinkage_loss).quantize(Decimal('0.01'))

        return {
            'totalDamageAndLossIncidents': len(damage_items),
            'totalDamagedQuantity': total_damage_qty,
            'totalShrinkageQuantity': total_shrinkage_qty,
            'totalLostQuantity': total_damage_qty + total_shrinkage_qty,
            'totalDamageLossValue': str(total_damage_loss.quantize(Decimal('0.01'))),
            'totalShrinkageLossValue': str(total_shrinkage_loss.quantize(Decimal('0.01'))),
            'totalEstimatedFinancialLoss': str(total_loss),
            'warehouseBreakdown': warehouse_breakdown,
            'damages': damage_items
        }
