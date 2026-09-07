from django.contrib import admin
from .models import Lookup, Role, AuditLog, CompanyProfile

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('id', 'role_name', 'is_active', 'created_at')
    search_fields = ('role_name',)
    filter_horizontal = ('permissions',)

admin.site.register(Lookup)
admin.site.register(AuditLog)


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'business_identification_number',
                    'drug_license_number', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'legal_name', 'business_identification_number',
                     'tax_identification_number', 'drug_license_number')
