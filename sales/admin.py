from django.contrib import admin
from .models import Customer, CustomerOrder, CustomerOrderItem


class CustomerOrderItemInline(admin.TabularInline):
    model = CustomerOrderItem
    extra = 1
    fields = ('product', 'warehouse', 'batch_number', 'quantity', 'unit_price', 'vat_percentage', 'discount_percentage', 'total_price')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('customer_code', 'name', 'proprietor_name', 'phone', 'customer_type', 'city', 'drug_license_expiry_date', 'is_active', 'created_at')
    list_filter = ('customer_type', 'is_active', 'city')
    search_fields = ('name', 'customer_code', 'proprietor_name', 'phone', 'drug_license_no')
    readonly_fields = ('customer_code', 'created_at', 'updated_at')


@admin.register(CustomerOrder)
class CustomerOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'customer', 'order_date', 'status', 'payment_status', 'payment_method', 'total_amount', 'created_by', 'created_at')
    list_filter = ('status', 'payment_status', 'payment_method', 'order_date')
    search_fields = ('order_number', 'customer__name', 'customer__customer_code', 'notes', 'shipping_address')
    readonly_fields = ('order_number', 'created_at', 'updated_at')
    inlines = [CustomerOrderItemInline]


@admin.register(CustomerOrderItem)
class CustomerOrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'warehouse', 'batch_number', 'quantity', 'unit_price', 'total_price')
    list_filter = ('warehouse',)
    search_fields = ('order__order_number', 'product__name', 'batch_number')
