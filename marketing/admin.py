from django.contrib import admin
from marketing.models import SalesTarget, ProductTargetItem


class ProductTargetItemInline(admin.TabularInline):
    model = ProductTargetItem
    extra = 1
    fields = ('product', 'target_quantity', 'unit_price', 'target_amount')
    readonly_fields = ('unit_price', 'target_amount')


@admin.register(SalesTarget)
class SalesTargetAdmin(admin.ModelAdmin):
    list_display = (
        'target_code', 'title', 'assigned_to', 'period_type',
        'start_date', 'end_date', 'total_target_amount', 'status'
    )
    list_filter = ('period_type', 'status', 'target_type', 'start_date', 'end_date')
    search_fields = ('target_code', 'title', 'assigned_to__username', 'territory_name')
    readonly_fields = ('target_code', 'created_at', 'updated_at')
    inlines = [ProductTargetItemInline]


@admin.register(ProductTargetItem)
class ProductTargetItemAdmin(admin.ModelAdmin):
    list_display = ('sales_target', 'product', 'target_quantity', 'unit_price', 'target_amount')
    list_filter = ('sales_target__status', 'product__category')
    search_fields = ('sales_target__target_code', 'product__name')


from marketing.models import Doctor, DoctorSampleDistribution, DoctorSampleItem, MPOClosingSnapshot


class DoctorSampleItemInline(admin.TabularInline):
    model = DoctorSampleItem
    extra = 1
    fields = ('product', 'batch_number', 'quantity', 'unit')


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('doctor_code', 'name', 'specialty', 'chamber_or_hospital_name', 'phone', 'assigned_mpo', 'is_active')
    list_filter = ('specialty', 'visiting_shift', 'assigned_mpo', 'is_active')
    search_fields = ('doctor_code', 'name', 'chamber_or_hospital_name', 'bmdc_reg_number', 'phone')
    readonly_fields = ('doctor_code', 'created_at', 'updated_at')


@admin.register(DoctorSampleDistribution)
class DoctorSampleDistributionAdmin(admin.ModelAdmin):
    list_display = ('distribution_number', 'doctor', 'mpo', 'source_warehouse', 'distribution_date', 'total_items_count')
    list_filter = ('distribution_date', 'source_warehouse', 'mpo')
    search_fields = ('distribution_number', 'doctor__name', 'mpo__username')
    readonly_fields = ('distribution_number', 'total_items_count', 'created_at', 'updated_at')
    inlines = [DoctorSampleItemInline]


@admin.register(MPOClosingSnapshot)
class MPOClosingSnapshotAdmin(admin.ModelAdmin):
    list_display = ('mpo', 'month', 'year', 'total_sales_amount', 'total_collected_amount', 'total_credit_due', 'is_locked')
    list_filter = ('year', 'month', 'is_locked')
    search_fields = ('mpo__username',)
    readonly_fields = ('created_at', 'updated_at')

