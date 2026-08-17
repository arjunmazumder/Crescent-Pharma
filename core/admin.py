from django.contrib import admin
from .models import Lookup, Role, AuditLog

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('id', 'role_name', 'is_active', 'created_at')
    search_fields = ('role_name',)
    filter_horizontal = ('permissions',)

admin.site.register(Lookup)
admin.site.register(AuditLog)
