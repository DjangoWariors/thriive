from django.contrib import admin

from .models import BulkJob


@admin.register(BulkJob)
class BulkJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_type', 'status', 'total_rows', 'processed_rows',
                    'success_count', 'error_count', 'created_by', 'started_at', 'finished_at')
    list_filter = ('job_type', 'status')
    search_fields = ('request_id',)
    raw_id_fields = ('created_by',)
    date_hierarchy = 'created_at'
