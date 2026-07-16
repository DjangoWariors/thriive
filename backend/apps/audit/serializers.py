from rest_framework import serializers

from apps.audit.models import AccessLog, AuditLog, ComputationLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_label = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id', 'action', 'entity_type', 'entity_id',
            'user_id', 'user_label', 'changes',
            'prev_hash', 'row_hash', 'timestamp',
        ]
        read_only_fields = fields

    def get_user_label(self, obj) -> str | None:
        labels = self.context.get('user_labels') or {}
        return labels.get(obj.user_id)


class AccessLogSerializer(serializers.ModelSerializer):
    user_label = serializers.SerializerMethodField()

    class Meta:
        model = AccessLog
        fields = [
            'id', 'user_id', 'user_label', 'resource', 'object_id',
            'subject_entity_id', 'action', 'request_id', 'ip_address', 'timestamp',
        ]
        read_only_fields = fields

    def get_user_label(self, obj) -> str | None:
        labels = self.context.get('user_labels') or {}
        return labels.get(obj.user_id)


class ComputationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComputationLog
        fields = [
            'id', 'computation_type', 'entity_id', 'period_id',
            'triggered_by_id', 'config_snapshot', 'result_snapshot', 'timestamp',
        ]
        read_only_fields = fields


class ChainVerifyRequestSerializer(serializers.Serializer):
    start_id = serializers.IntegerField(required=False, allow_null=True)
    end_id = serializers.IntegerField(required=False, allow_null=True)


class ChainVerifyResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    broken_at = serializers.IntegerField(allow_null=True)
    reason = serializers.CharField(allow_null=True)
    checked = serializers.IntegerField()
