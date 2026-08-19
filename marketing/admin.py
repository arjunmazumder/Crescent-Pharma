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
