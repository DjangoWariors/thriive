from rest_framework import serializers

from .models import BulkJob


class BulkJobSerializer(serializers.ModelSerializer):
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = BulkJob
        fields = [
            'id',
            'job_type',
            'status',
            'is_terminal',
            'total_rows',
            'processed_rows',
            'success_count',
            'error_count',
            'errors',
            'result',
            'request_id',
            'created_by',
            'created_at',
            'updated_at',
            'started_at',
            'finished_at',
        ]
        read_only_fields = fields
