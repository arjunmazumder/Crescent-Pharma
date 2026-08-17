from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'employee_id', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Role & Permissions', {'fields': ('role',)}),
        ('Employee Info', {'fields': ('employee_id', 'contact', 'address', 'date_of_birth', 'joining_date', 'nid_number')}),
        ('Shift Info', {'fields': ('morning_shift_start', 'morning_shift_end', 'evening_shift_start', 'evening_shift_end', 'location_bounded_attendance')}),
    )

admin.site.register(CustomUser, CustomUserAdmin)
