from django.contrib import admin

from .models import DeliveryTarget, ReportDefinition, ReportExecution, ReportSchedule


@admin.register(ReportDefinition)
class ReportDefinitionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category', 'required_permission', 'is_confidential',
                    'is_dataset', 'is_active')
    list_filter = ('category', 'is_confidential', 'is_dataset', 'is_active')
    search_fields = ('code', 'name')


@admin.register(ReportExecution)
class ReportExecutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'definition', 'requested_by', 'status', 'format', 'row_count',
                    'started_at', 'finished_at')
    list_filter = ('status', 'format')
    search_fields = ('definition__code',)
    raw_id_fields = ('definition', 'requested_by')
    date_hierarchy = 'created_at'


@admin.register(ReportSchedule)
class ReportScheduleAdmin(admin.ModelAdmin):
    list_display = ('name', 'definition', 'format', 'delivery', 'is_enabled',
                    'owner', 'last_run_at')
    list_filter = ('delivery', 'format', 'is_enabled')
    search_fields = ('name', 'definition__code')
    raw_id_fields = ('definition', 'delivery_target', 'owner')


@admin.register(DeliveryTarget)
class DeliveryTargetAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'credential_env', 'is_active')
    list_filter = ('kind',)
    search_fields = ('code', 'name')
