from django.contrib import admin
from .models import (
    Category, Attribute, AttributeValue, Product,
    ProductAttributeValue, Warehouse, StockLevel, StockMovement
)


class ProductAttributeValueInline(admin.TabularInline):
    model = ProductAttributeValue
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'parent', 'display_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'code', 'description')
    ordering = ('display_order', 'name')


class AttributeValueInline(admin.TabularInline):
    model = AttributeValue
    extra = 2


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')
    inlines = [AttributeValueInline]


@admin.register(AttributeValue)
class AttributeValueAdmin(admin.ModelAdmin):
    list_display = ('attribute', 'value', 'code', 'created_at')
    list_filter = ('attribute',)
    search_fields = ('value', 'attribute__name')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'unique_id', 'generic_name', 'category', 'unit',
        'selling_price', 'purchase_price', 'min_stock_level', 'is_active'
    )
    list_filter = ('category', 'is_active', 'requires_prescription')
    search_fields = ('name', 'generic_name', 'unique_id', 'barcode', 'drug_registration_number')
    inlines = [ProductAttributeValueInline]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'contact_number', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'address')


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'warehouse', 'batch_number', 'expiry_date',
        'quantity', 'reserved_quantity', 'rack_location', 'updated_at'
    )
    list_filter = ('warehouse', 'expiry_date')
    search_fields = ('product__name', 'product__unique_id', 'batch_number', 'warehouse__name')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'movement_type', 'product', 'warehouse', 'batch_number',
        'quantity', 'previous_stock', 'new_stock', 'reference_no', 'created_by', 'created_at'
    )
    list_filter = ('movement_type', 'warehouse', 'created_at')
    search_fields = ('product__name', 'product__unique_id', 'batch_number', 'reference_no', 'notes')
