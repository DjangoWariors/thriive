from django.contrib import admin

from .models import AccessLog, AuditLog, ComputationLog, RetentionPolicy


class ReadOnlyAdmin(admin.ModelAdmin):
    """Append-only logs: browsable in admin, never mutable (the hash chain and
    disclosure trail must stay tamper-proof even for superusers)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ('id', 'action', 'entity_type', 'entity_id', 'user_id', 'timestamp')
    list_filter = ('action',)
    search_fields = ('entity_type', 'entity_id')
    date_hierarchy = 'timestamp'


@admin.register(AccessLog)
class AccessLogAdmin(ReadOnlyAdmin):
    list_display = ('id', 'resource', 'action', 'user_id', 'subject_entity_id',
                    'ip_address', 'timestamp')
    list_filter = ('resource', 'action')
    search_fields = ('request_id', 'ip_address')
    date_hierarchy = 'timestamp'


@admin.register(ComputationLog)
class ComputationLogAdmin(ReadOnlyAdmin):
    list_display = ('id', 'computation_type', 'entity_id', 'period_id',
                    'triggered_by_id', 'timestamp')
    list_filter = ('computation_type',)
    search_fields = ('entity_id',)
    date_hierarchy = 'timestamp'


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ('log_type', 'retain_days', 'archive_strategy', 'is_active')
    list_filter = ('archive_strategy',)
