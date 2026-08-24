from decimal import Decimal, ROUND_HALF_UP
import datetime
from django.db.models import Sum, Count, Q
from django.contrib.auth import get_user_model
from marketing.models import SalesTarget, ProductTargetItem, TargetStatus
from sales.models import CustomerOrder, CustomerOrderItem, OrderStatus
from hr.models import Attendance

User = get_user_model()


class TargetService:
    @staticmethod
    def get_incentive_config():
        """
        Loads dynamic incentive tier thresholds and commission rates from Lookup table
        with fallback defaults.
        Lookup Keys:
        - INCENTIVE_TIER_SUPER_THRESHOLD (default: 120.00)
        - INCENTIVE_TIER_SUPER_RATE (default: 5.00)
        - INCENTIVE_TIER_TARGET_THRESHOLD (default: 100.00)
        - INCENTIVE_TIER_TARGET_RATE (default: 3.00)
        - INCENTIVE_TIER_NEAR_THRESHOLD (default: 80.00)
        - INCENTIVE_TIER_NEAR_RATE (default: 1.00)
        """
        from core.models import Lookup

        def get_lookup_decimal(name, default_val):
            item = Lookup.objects.filter(name=name, is_active=True).first()
            if item and item.value:
                try:
                    return Decimal(str(item.value).strip())
                except Exception:
                    pass
            return Decimal(str(default_val))

        return {
            'super_threshold': get_lookup_decimal('INCENTIVE_TIER_SUPER_THRESHOLD', '120.00'),
            'super_rate': get_lookup_decimal('INCENTIVE_TIER_SUPER_RATE', '5.00'),
            'target_threshold': get_lookup_decimal('INCENTIVE_TIER_TARGET_THRESHOLD', '100.00'),
            'target_rate': get_lookup_decimal('INCENTIVE_TIER_TARGET_RATE', '3.00'),
            'near_threshold': get_lookup_decimal('INCENTIVE_TIER_NEAR_THRESHOLD', '80.00'),
            'near_rate': get_lookup_decimal('INCENTIVE_TIER_NEAR_RATE', '1.00'),
        }

    @staticmethod
    def calculate_target_achievement(target, start_date=None, end_date=None, product_id=None, order_status=None):
        """
        Calculates real-time achievement for a SalesTarget instance with optional filters.
        - start_date & end_date: custom evaluation date range (defaults to target.start_date and target.end_date)
        - product_id: filter product breakdown for a specific product
        - order_status: filter order status ('DELIVERED', 'CONFIRMED', or None for both)
        """
        if isinstance(target, (int, str)):
            target = SalesTarget.objects.get(id=int(target))

        eval_start = start_date or target.start_date
        eval_end = end_date or target.end_date

        allowed_statuses = [OrderStatus.CONFIRMED, OrderStatus.DELIVERED]
        if order_status:
            status_upper = str(order_status).strip().upper()
            if status_upper in [OrderStatus.CONFIRMED, OrderStatus.DELIVERED, 'CONFIRMED', 'DELIVERED']:
                allowed_statuses = [status_upper]

        # 1. Fetch relevant orders
        orders = CustomerOrder.objects.filter(
            created_by=target.assigned_to,
            order_date__gte=eval_start,
            order_date__lte=eval_end,
            status__in=allowed_statuses
        )

        total_orders_count = orders.count()
        total_achieved_amount = Decimal('0.00')
        for order in orders:
            total_achieved_amount += Decimal(str(order.total_amount))
        total_achieved_amount = total_achieved_amount.quantize(Decimal('0.01'))

        total_target_amount = Decimal(str(target.total_target_amount or '0.00'))
        if total_target_amount > Decimal('0.00'):
            amount_achievement_percentage = ((total_achieved_amount / total_target_amount) * Decimal('100.0')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            amount_achievement_percentage = Decimal('100.00') if total_achieved_amount > Decimal('0.00') else Decimal('0.00')

        amount_variance = (total_achieved_amount - total_target_amount).quantize(Decimal('0.01'))

        # 2. Product-wise Target Breakdown
        product_breakdown = []
        target_items = target.product_items.select_related('product').all()
        if product_id:
            target_items = target_items.filter(product_id=product_id)

        for item in target_items:
            order_items = CustomerOrderItem.objects.filter(
                order__in=orders,
                product=item.product
            )
            achieved_qty = sum(oi.quantity for oi in order_items)
            achieved_amt = Decimal('0.00')
            for oi in order_items:
                achieved_amt += Decimal(str(oi.total_price))
            achieved_amt = achieved_amt.quantize(Decimal('0.01'))

            tgt_qty = item.target_quantity
            tgt_amt = Decimal(str(item.target_amount))

            qty_pct = Decimal('0.00')
            if tgt_qty > 0:
                qty_pct = ((Decimal(achieved_qty) / Decimal(tgt_qty)) * Decimal('100.0')).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )

            qty_variance = achieved_qty - tgt_qty
            amt_variance = (achieved_amt - tgt_amt).quantize(Decimal('0.01'))

            product_breakdown.append({
                'productId': item.product.id,
                'productName': item.product.name,
                'productUniqueId': item.product.unique_id,
                'unit': item.product.unit,
                'targetQuantity': tgt_qty,
                'achievedQuantity': achieved_qty,
                'quantityAchievementPercentage': float(qty_pct),
                'quantityVariance': qty_variance,
                'unitPrice': str(item.unit_price),
                'targetAmount': str(tgt_amt),
                'achievedAmount': str(achieved_amt),
                'amountVariance': str(amt_variance),
                'isAchieved': achieved_qty >= tgt_qty
            })

        # 3. Attendance & Dual-Shift Performance
        attendances = Attendance.objects.filter(
            user=target.assigned_to,
            date__gte=eval_start,
            date__lte=eval_end
        )

        shift_1_count = attendances.filter(
            shift=1,
            status__in=[Attendance.STATUS_CHOICES['PRESENT'], Attendance.STATUS_CHOICES['LATE']]
        ).count()

        shift_2_count = attendances.filter(
            shift=2,
            status__in=[Attendance.STATUS_CHOICES['PRESENT'], Attendance.STATUS_CHOICES['LATE']]
        ).count()

        total_attended_days = attendances.filter(
            status__in=[Attendance.STATUS_CHOICES['PRESENT'], Attendance.STATUS_CHOICES['LATE']]
        ).values('date').distinct().count()

        late_days_count = attendances.filter(
            status=Attendance.STATUS_CHOICES['LATE']
        ).values('date').distinct().count()

        # 4. Incentive Tier Evaluation (Dynamic from Lookup configuration)
        cfg = TargetService.get_incentive_config()
        is_target_achieved = total_achieved_amount >= total_target_amount and (total_target_amount > Decimal('0.00'))

        super_th = cfg['super_threshold']
        target_th = cfg['target_threshold']
        near_th = cfg['near_threshold']

        if amount_achievement_percentage >= super_th:
            incentive_tier = f"Super Achiever ({super_th:.0f}%+)"
            commission_rate = cfg['super_rate']
        elif amount_achievement_percentage >= target_th:
            incentive_tier = f"Target Achiever ({target_th:.0f}%+)"
            commission_rate = cfg['target_rate']
        elif amount_achievement_percentage >= near_th:
            incentive_tier = f"Near Target ({near_th:.0f}-{target_th - 1:.0f}%)" if target_th > near_th else f"Near Target ({near_th:.0f}%+)"
            commission_rate = cfg['near_rate']
        else:
            incentive_tier = f"Below Target (<{near_th:.0f}%)"
            commission_rate = Decimal('0.00')

        potential_commission = (total_achieved_amount * (commission_rate / Decimal('100.0'))).quantize(Decimal('0.01'))

        # Auto-update status if target end_date has passed or achieved
        if is_target_achieved and target.status == TargetStatus.ACTIVE:
            target.status = TargetStatus.ACHIEVED
            target.save(update_fields=['status'])
        elif target.end_date < datetime.date.today() and target.status == TargetStatus.ACTIVE:
            target.status = TargetStatus.MISSED
            target.save(update_fields=['status'])

        return {
            'targetId': target.id,
            'targetCode': target.target_code,
            'title': target.title,
            'periodType': target.period_type,
            'startDate': str(eval_start),
            'endDate': str(eval_end),
            'targetType': target.target_type,
            'status': target.status,
            'territoryName': target.territory_name or '',
            'totalTargetAmount': str(total_target_amount),
            'totalAchievedAmount': str(total_achieved_amount),
            'amountAchievementPercentage': float(amount_achievement_percentage),
            'amountVariance': str(amount_variance),
            'totalOrdersCount': total_orders_count,
            'productBreakdown': product_breakdown,
            'shiftPerformance': {
                'shift1MorningCount': shift_1_count,
                'shift2EveningCount': shift_2_count,
                'totalAttendedDays': total_attended_days,
                'lateDaysCount': late_days_count,
            },
            'incentiveEvaluation': {
                'isAchieved': is_target_achieved,
                'incentiveTier': incentive_tier,
                'commissionRatePercentage': float(commission_rate),
                'potentialCommissionAmount': str(potential_commission)
            },
            'assignedTo': {
                'id': target.assigned_to.id,
                'username': target.assigned_to.username,
                'employeeId': getattr(target.assigned_to, 'employee_id', ''),
                'email': target.assigned_to.email,
                'contact': getattr(target.assigned_to, 'contact', ''),
                'roleName': target.assigned_to.role.role_name if target.assigned_to.role else ''
            }
        }

    @staticmethod
    def get_mpo_scorecard(user, start_date=None, end_date=None):
        """
        Builds a comprehensive individual performance scorecard for an MPO user.
        """
        targets_qs = SalesTarget.objects.filter(assigned_to=user).order_by('-start_date')
        if start_date and end_date:
            targets_qs = targets_qs.filter(start_date__lte=end_date, end_date__gte=start_date)

        target_cards = [TargetService.calculate_target_achievement(t) for t in targets_qs]

        # Aggregate totals across active/evaluated targets
        grand_target_amt = sum(Decimal(str(tc['totalTargetAmount'])) for tc in target_cards)
        grand_achieved_amt = sum(Decimal(str(tc['totalAchievedAmount'])) for tc in target_cards)
        grand_commission_amt = sum(Decimal(str(tc['incentiveEvaluation']['potentialCommissionAmount'])) for tc in target_cards)
        grand_pct = ((grand_achieved_amt / grand_target_amt) * Decimal('100.0')).quantize(Decimal('0.01')) if grand_target_amt > 0 else Decimal('0.00')

        return {
            'mpoId': user.id,
            'username': user.username,
            'employeeId': getattr(user, 'employee_id', ''),
            'email': user.email,
            'contact': getattr(user, 'contact', ''),
            'roleName': user.role.role_name if user.role else 'MPO',
            'totalTargetsAssigned': len(target_cards),
            'totalTargetRevenue': str(grand_target_amt),
            'totalAchievedRevenue': str(grand_achieved_amt),
            'overallAchievementPercentage': float(grand_pct),
            'totalEarnedCommission': str(grand_commission_amt),
            'targets': target_cards
        }

    @staticmethod
    def get_mpo_commission_summary(user, start_date=None, end_date=None):
        """
        Builds a focused commission earnings breakdown for the MPO dashboard card.
        """
        scorecard = TargetService.get_mpo_scorecard(user=user, start_date=start_date, end_date=end_date)
        commission_breakdown = []
        for t in scorecard['targets']:
            commission_breakdown.append({
                'targetId': t['targetId'],
                'title': t['title'],
                'targetAmount': t['totalTargetAmount'],
                'achievedAmount': t['totalAchievedAmount'],
                'achievementPercentage': t['amountAchievementPercentage'],
                'incentiveTier': t['incentiveEvaluation']['incentiveTier'],
                'commissionRatePercentage': t['incentiveEvaluation']['commissionRatePercentage'],
                'earnedCommissionAmount': t['incentiveEvaluation']['potentialCommissionAmount'],
                'isAchieved': t['incentiveEvaluation']['isAchieved']
            })
        return {
            'mpoId': user.id,
            'employeeName': f"{user.first_name} {user.last_name}".strip() or user.username,
            'employeeId': getattr(user, 'employee_id', ''),
            'totalTargetRevenue': scorecard['totalTargetRevenue'],
            'totalAchievedRevenue': scorecard['totalAchievedRevenue'],
            'overallAchievementPercentage': scorecard['overallAchievementPercentage'],
            'totalEarnedCommission': scorecard['totalEarnedCommission'],
            'commissionBreakdown': commission_breakdown
        }

    @staticmethod
    def get_consolidated_team_report(start_date=None, end_date=None, period_type=None):
        """
        Generates a consolidated company-wide marketing report ranking all MPOs
        by achievement percentage (Leaderboard) with area and territory rollups.
        """
        targets_qs = SalesTarget.objects.select_related('assigned_to', 'assigned_to__role').all()
        if start_date and end_date:
            targets_qs = targets_qs.filter(start_date__lte=end_date, end_date__gte=start_date)
        if period_type:
            targets_qs = targets_qs.filter(period_type=period_type)

        evaluated_targets = [TargetService.calculate_target_achievement(t) for t in targets_qs]

        # Group by MPO user
        mpo_map = {}
        for ev in evaluated_targets:
            assigned_user = ev.get('assignedTo') or {}
            uid = assigned_user.get('id')
            if not uid:
                continue
            if uid not in mpo_map:
                mpo_map[uid] = {
                    'mpoId': uid,
                    'username': assigned_user.get('username', ''),
                    'employeeId': assigned_user.get('employeeId', ''),
                    'territoryName': ev.get('territoryName', ''),
                    'targetAmount': Decimal('0.00'),
                    'achievedAmount': Decimal('0.00'),
                    'totalOrders': 0,
                    'shiftsAttended': 0,
                    'targetsCount': 0
                }
            mpo_map[uid]['targetAmount'] += Decimal(str(ev['totalTargetAmount']))
            mpo_map[uid]['achievedAmount'] += Decimal(str(ev['totalAchievedAmount']))
            mpo_map[uid]['totalOrders'] += ev['totalOrdersCount']
            mpo_map[uid]['shiftsAttended'] += (ev['shiftPerformance']['shift1MorningCount'] + ev['shiftPerformance']['shift2EveningCount'])
            mpo_map[uid]['targetsCount'] += 1

        leaderboard = []
        for mpo in mpo_map.values():
            tgt = mpo['targetAmount']
            ach = mpo['achievedAmount']
            pct = ((ach / tgt) * Decimal('100.0')).quantize(Decimal('0.01')) if tgt > 0 else Decimal('0.00')
            variance = (ach - tgt).quantize(Decimal('0.01'))

            leaderboard.append({
                'mpoId': mpo['mpoId'],
                'username': mpo['username'],
                'employeeId': mpo['employeeId'],
                'territoryName': mpo['territoryName'],
                'targetAmount': str(tgt),
                'achievedAmount': str(ach),
                'achievementPercentage': float(pct),
                'variance': str(variance),
                'totalOrders': mpo['totalOrders'],
                'shiftsAttended': mpo['shiftsAttended'],
                'targetsCount': mpo['targetsCount'],
                'isTopPerformer': False
            })

        # Sort leaderboard by achievement percentage descending
        leaderboard.sort(key=lambda x: x['achievementPercentage'], reverse=True)
        for rank, item in enumerate(leaderboard, start=1):
            item['rank'] = rank
            if rank == 1 and item['achievementPercentage'] > 0:
                item['isTopPerformer'] = True

        total_team_target = sum(Decimal(str(item['targetAmount'])) for item in leaderboard)
        total_team_achieved = sum(Decimal(str(item['achievedAmount'])) for item in leaderboard)
        team_achievement_pct = ((total_team_achieved / total_team_target) * Decimal('100.0')).quantize(
            Decimal('0.01')
        ) if total_team_target > 0 else Decimal('0.00')

        return {
            'totalMarketingStaff': len(leaderboard),
            'totalTeamTarget': str(total_team_target),
            'totalTeamAchieved': str(total_team_achieved),
            'teamAchievementPercentage': float(team_achievement_pct),
            'totalTeamVariance': str((total_team_achieved - total_team_target).quantize(Decimal('0.01'))),
            'topPerformer': leaderboard[0]['username'] if leaderboard else None,
            'leaderboard': leaderboard
        }


# -----------------------------------------------------------------------------
# 2. SampleDistributionService (Physician Free Samples)
# -----------------------------------------------------------------------------

class SampleDistributionService:
    @staticmethod
    def create_distribution(
        doctor,
        mpo,
        items_data,
        source_warehouse=None,
        distribution_date=None,
        notes=""
    ):
        """
        Creates a DoctorSampleDistribution record with nested DoctorSampleItems.
        If source_warehouse is provided, automatically deducts physical promotional
        inventory stock via InventoryService.record_stock_movement (movement_type='OUT').
        """
        from django.db import transaction
        from inventory.models import Product, Warehouse
        from inventory.services import InventoryService
        from marketing.models import DoctorSampleDistribution, DoctorSampleItem

        if not doctor.is_active:
            raise ValueError(f"Cannot distribute samples: Doctor '{doctor.name}' is inactive.")

        if not items_data:
            raise ValueError("At least one sample medicine item must be provided.")

        with transaction.atomic():
            dist = DoctorSampleDistribution.objects.create(
                doctor=doctor,
                mpo=mpo,
                source_warehouse=source_warehouse,
                distribution_date=distribution_date or datetime.date.today(),
                notes=notes or ""
            )

            total_items = 0
            for item in items_data:
                product_id = item.get('product_id') or item.get('productId')
                batch_number = item.get('batch_number') or item.get('batchNumber') or ""
                quantity = int(item.get('quantity', 1))
                unit = item.get('unit', 'Strips')

                if quantity <= 0:
                    raise ValueError("Sample quantity must be greater than zero.")

                try:
                    product = Product.objects.get(id=product_id, is_active=True)
                except Product.DoesNotExist:
                    raise ValueError(f"Product with ID {product_id} not found or inactive.")

                # Deduct promotional stock if warehouse is specified
                if source_warehouse:
                    InventoryService.record_stock_movement(
                        product=product,
                        warehouse=source_warehouse,
                        batch_number=batch_number,
                        movement_type='OUT',
                        quantity=quantity,
                        reference_no=dist.distribution_number,
                        notes=f"Physician Sample issued to Dr. {doctor.name} ({doctor.specialty})",
                        user=mpo
                    )

                DoctorSampleItem.objects.create(
                    distribution=dist,
                    product=product,
                    batch_number=batch_number,
                    quantity=quantity,
                    unit=unit
                )
                total_items += quantity

            dist.total_items_count = total_items
            dist.save(update_fields=['total_items_count'])

            return dist


# -----------------------------------------------------------------------------
# 3. ClosingSheetService (Daily Sales + Collections Running Balance Engine)
# -----------------------------------------------------------------------------

class ClosingSheetService:
    @staticmethod
    def get_mpo_closing_sheet(user, month=None, year=None):
        """
        Compiles a comprehensive day-by-day chronological sales & collections closing sheet
        for a given Marketing Officer (MPO) in a selected month & year.
        - Daily Sales Invoices: CustomerOrder (ORD-*) created by MPO
        - Daily Collections: PaymentRecord (MR-*) collected by MPO
        - Running cumulative balances (Cumulative Sales, Cumulative Collections, Running Due)
        - Monthly summary metrics (Total Sales, Total Collections, Total Market Due, Total Invoices, Total Receipts)
        """
        import calendar
        from sales.models import CustomerOrder
        from accounting.models import PaymentRecord

        today = datetime.date.today()
        month = int(month or today.month)
        year = int(year or today.year)

        _, num_days = calendar.monthrange(year, month)
        start_date = datetime.date(year, month, 1)
        end_date = datetime.date(year, month, num_days)

        # 1. Fetch MPO's orders in this month
        orders = CustomerOrder.objects.filter(
            created_by=user,
            order_date__gte=start_date,
            order_date__lte=end_date
        ).select_related('customer').order_by('order_date', 'id')

        # Group orders by date
        orders_by_date = {}
        total_monthly_sales = Decimal('0.00')
        total_invoices_count = 0

        for order in orders:
            d_key = order.order_date
            if d_key not in orders_by_date:
                orders_by_date[d_key] = []

            amt = Decimal(str(order.total_amount))
            total_monthly_sales += amt
            total_invoices_count += 1

            orders_by_date[d_key].append({
                'id': order.id,
                'orderNumber': order.order_number,
                'customerId': order.customer_id,
                'customerName': order.customer.name,
                'subtotal': str(order.subtotal),
                'discountAmount': str((Decimal(str(order.subtotal)) * (order.discount_percentage / Decimal('100.0')) + order.discount_flat).quantize(Decimal('0.01'))),
                'taxAmount': str(order.tax_amount),
                'totalAmount': str(order.total_amount),
                'paidAmount': str(order.paid_amount),
                'status': order.status,
                'paymentStatus': order.payment_status,
                'isBranchBooking': order.is_branch_booking
            })

        # 2. Fetch MPO's payment collections in this month
        payments = PaymentRecord.objects.filter(
            created_by=user,
            payment_date__gte=start_date,
            payment_date__lte=end_date
        ).order_by('payment_date', 'id')

        payments_by_date = {}
        total_monthly_collections = Decimal('0.00')
        total_receipts_count = 0

        for pay in payments:
            d_key = pay.payment_date
            if d_key not in payments_by_date:
                payments_by_date[d_key] = []

            p_amt = Decimal(str(pay.amount))
            total_monthly_collections += p_amt
            total_receipts_count += 1

            payments_by_date[d_key].append({
                'id': pay.id,
                'receiptNo': pay.receipt_no,
                'paymentType': pay.payment_type,
                'partyType': pay.party_type,
                'partyId': pay.party_id,
                'amount': str(pay.amount),
                'paymentMethod': pay.payment_method,
                'referenceNo': pay.reference_no,
                'notes': pay.notes
            })

        # 3. Build Daily Chronological Timeline
        daily_entries = []
        cumulative_sales = Decimal('0.00')
        cumulative_collections = Decimal('0.00')

        for day in range(1, num_days + 1):
            curr_date = datetime.date(year, month, day)
            day_orders = orders_by_date.get(curr_date, [])
            day_payments = payments_by_date.get(curr_date, [])

            day_sales = sum((Decimal(str(o['totalAmount'])) for o in day_orders), Decimal('0.00'))
            day_coll = sum((Decimal(str(p['amount'])) for p in day_payments), Decimal('0.00'))

            cumulative_sales += day_sales
            cumulative_collections += day_coll
            running_due = cumulative_sales - cumulative_collections

            daily_entries.append({
                'date': curr_date.strftime('%Y-%m-%d'),
                'dayName': curr_date.strftime('%A'),
                'dayNumber': day,
                'dailySalesAmount': str(day_sales.quantize(Decimal('0.01'))),
                'dailyCollectionsAmount': str(day_coll.quantize(Decimal('0.01'))),
                'cumulativeSalesAmount': str(cumulative_sales.quantize(Decimal('0.01'))),
                'cumulativeCollectionsAmount': str(cumulative_collections.quantize(Decimal('0.01'))),
                'runningOutstandingBalance': str(running_due.quantize(Decimal('0.01'))),
                'invoicesCount': len(day_orders),
                'receiptsCount': len(day_payments),
                'invoices': day_orders,
                'collections': day_payments
            })

        total_market_due = (total_monthly_sales - total_monthly_collections).quantize(Decimal('0.01'))

        return {
            'mpoId': user.id,
            'mpoUsername': user.username,
            'mpoFullName': user.get_full_name() or user.username,
            'employeeId': getattr(user, 'employee_id', None) or f"EMP-{user.id:04d}",
            'month': month,
            'monthName': datetime.date(year, month, 1).strftime('%B'),
            'year': year,
            'summary': {
                'totalMonthlySales': str(total_monthly_sales.quantize(Decimal('0.01'))),
                'totalMonthlyCollections': str(total_monthly_collections.quantize(Decimal('0.01'))),
                'totalMarketDue': str(total_market_due),
                'totalInvoicesCount': total_invoices_count,
                'totalReceiptsCount': total_receipts_count,
                'collectionEfficiencyPercentage': float(((total_monthly_collections / total_monthly_sales) * Decimal('100.0')).quantize(Decimal('0.01'))) if total_monthly_sales > 0 else 0.0
            },
            'dailyTimeline': daily_entries
        }

