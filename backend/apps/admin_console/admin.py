from django.contrib import admin

from .models import FeatureFlag, SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'category', 'value', 'value_type', 'is_sensitive', 'is_active')
    list_filter = ('category', 'is_sensitive')
    search_fields = ('key', 'description')


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ('code', 'is_enabled', 'scope', 'scope_value', 'is_active')
    list_filter = ('is_enabled', 'scope')
    search_fields = ('code', 'description')
