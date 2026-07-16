from django.contrib import admin

from .models import SKU, SKUGroup, UOMConversion


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'brand', 'category', 'mrp', 'is_focus', 'is_npi', 'is_active')
    list_filter = ('brand', 'category', 'is_focus', 'is_npi', 'is_active')
    search_fields = ('code', 'name')


@admin.register(SKUGroup)
class SKUGroupAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'filter_type', 'is_active')
    list_filter = ('filter_type', 'is_active')
    search_fields = ('code', 'name')


@admin.register(UOMConversion)
class UOMConversionAdmin(admin.ModelAdmin):
    list_display = ('sku_code', 'from_uom', 'to_uom', 'factor', 'is_active')
    list_filter = ('from_uom', 'to_uom')
    search_fields = ('sku_code',)
