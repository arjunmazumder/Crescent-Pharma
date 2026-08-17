import datetime
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from .models import Product, Warehouse, StockLevel, StockMovement


class InventoryService:
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
        user=None
    ):
        """
        Atomically records a stock transaction (IN, OUT, ADJUSTMENT, RETURN, DAMAGE)
        and updates or creates the corresponding StockLevel for the warehouse and batch.
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
                    'quantity': 0
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
                if quantity > stock_level.available_quantity:
                    raise ValueError(
                        f"Insufficient stock for {product.name} (Batch: {batch_number}) at {warehouse.name}. "
                        f"Requested: {quantity}, Available: {stock_level.available_quantity}."
                    )
                new_stock = previous_stock - quantity
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
