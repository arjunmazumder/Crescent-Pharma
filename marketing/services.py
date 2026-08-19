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
    def calculate_target_achievement(target):
        """
        Calculates real-time achievement for a SalesTarget instance.
        Aggregates confirmed/delivered sales orders booked by the assigned MPO
        within [start_date, end_date], product-wise quantity & revenue,
        and dual-shift attendance compliance.
        """
        if isinstance(target, (int, str)):
            target = SalesTarget.objects.get(id=int(target))

        # 1. Fetch relevant orders
        orders = CustomerOrder.objects.filter(
            created_by=target.assigned_to,
            order_date__gte=target.start_date,
            order_date__lte=target.end_date,
            status__in=[OrderStatus.CONFIRMED, OrderStatus.DELIVERED]
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
            date__gte=target.start_date,
            date__lte=target.end_date
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

        # 4. Incentive Tier Evaluation
        is_target_achieved = total_achieved_amount >= total_target_amount and (total_target_amount > Decimal('0.00'))
        if amount_achievement_percentage >= Decimal('120.00'):
            incentive_tier = 'Super Achiever (120%+)'
            commission_rate = Decimal('5.00')
        elif amount_achievement_percentage >= Decimal('100.00'):
            incentive_tier = 'Target Achiever (100%+)'
            commission_rate = Decimal('3.00')
        elif amount_achievement_percentage >= Decimal('80.00'):
            incentive_tier = 'Near Target (80-99%)'
            commission_rate = Decimal('1.00')
        else:
            incentive_tier = 'Below Target (<80%)'
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
            'assignedToId': target.assigned_to.id,
            'assignedToUsername': target.assigned_to.username,
            'employeeId': getattr(target.assigned_to, 'employee_id', ''),
            'territoryName': target.territory_name or '',
            'periodType': target.period_type,
            'startDate': str(target.start_date),
            'endDate': str(target.end_date),
            'targetType': target.target_type,
            'status': target.status,
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
            'targets': target_cards
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
            uid = ev['assignedToId']
            if uid not in mpo_map:
                mpo_map[uid] = {
                    'mpoId': uid,
                    'username': ev['assignedToUsername'],
                    'employeeId': ev['employeeId'],
                    'territoryName': ev['territoryName'],
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
