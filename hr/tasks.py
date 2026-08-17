from celery import shared_task
from django.utils import timezone
from django.contrib.auth import get_user_model
from hr.models import Attendance, Holiday, WeekendConfig, LeaveRequest
from core.models import Lookup

User = get_user_model()

@shared_task
def mark_absent_cron_job():
    today = timezone.now().date()
    
    # 1. Skip if today is a public holiday
    if Holiday.objects.filter(date=today).exists():
        holiday = Holiday.objects.get(date=today)
        return f"Skipped: Today is a public holiday ({holiday.name})."
    
    # 2. Skip if today is an active weekend day
    # Django/Python weekday: Monday=0, Tuesday=1 ... Sunday=6
    if WeekendConfig.objects.filter(day_of_week=today.weekday(), is_active=True).exists():
        return f"Skipped: Today is an active weekend/off-day (day {today.weekday()})."

    # Only mark regular active employees as absent (exclude superusers)
    employees = User.objects.filter(is_active=True, is_superuser=False)
    marked_count = 0
    
    for emp in employees:
        # Check if employee has an active approved leave today
        active_leave = LeaveRequest.objects.filter(
            user=emp,
            start_date__lte=today,
            end_date__gte=today,
            status=LeaveRequest.STATUS_CHOICES['APPROVED']
        ).first()

        if active_leave:
            if not Attendance.objects.filter(user=emp, date=today).exists():
                Attendance.objects.create(
                    user=emp,
                    date=today,
                    shift=1,
                    status=Attendance.STATUS_CHOICES['ON_LEAVE'],
                    notes=f"Approved {active_leave.leave_type}"
                )
            continue

        if not Attendance.objects.filter(user=emp, date=today).exists():
            Attendance.objects.create(
                user=emp,
                date=today,
                shift=1,
                status=Attendance.STATUS_CHOICES['ABSENT'],
                notes="Auto-marked absent by system"
            )
            marked_count += 1
            
    return f"Cron job completed: {marked_count} employees marked absent."
