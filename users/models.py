from django.db import models
from django.contrib.auth.models import AbstractUser
from core.models import Role

class CustomUser(AbstractUser):
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    contact = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    nid_number = models.CharField(max_length=50, null=True, blank=True)
    
    # Shift times
    morning_shift_start = models.TimeField(default='09:00:00')
    morning_shift_end = models.TimeField(default='12:00:00')
    evening_shift_start = models.TimeField(default='16:00:00')
    evening_shift_end = models.TimeField(default='20:00:00')
    
    location_bounded_attendance = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'users'
        
    def __str__(self):
        return f"{self.username} ({self.employee_id or 'No ID'})"

    def save(self, *args, **kwargs):
        if not self.employee_id or not str(self.employee_id).strip():
            # Auto-generate format: EMP-0001, EMP-0002, etc.
            last_employee = CustomUser.objects.filter(employee_id__startswith='EMP-').order_by('-employee_id').first()
            if last_employee and last_employee.employee_id:
                try:
                    last_number = int(last_employee.employee_id.split('-')[-1])
                    next_number = last_number + 1
                except (ValueError, IndexError):
                    next_number = 1
            else:
                next_number = 1

            # Ensure uniqueness
            candidate_id = f"EMP-{next_number:04d}"
            while CustomUser.objects.filter(employee_id=candidate_id).exclude(pk=self.pk).exists():
                next_number += 1
                candidate_id = f"EMP-{next_number:04d}"

            self.employee_id = candidate_id

        super().save(*args, **kwargs)

    def get_effective_permissions(self):
        """Returns a list of all permission codenames the user has.
        For superuser, returns ['*'] (wildcard full access).
        For regular users, returns exact combined permissions (Role + Direct user_permissions).
        """
        if self.is_superuser:
            return ["all"]
        perms = set(self.user_permissions.values_list('codename', flat=True))
        if self.role and self.role.is_active:
            perms.update(self.role.permissions.values_list('codename', flat=True))
        return sorted(list(perms))
