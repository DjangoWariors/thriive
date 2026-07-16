from rest_framework import serializers

from apps.reports.models import DeliveryTarget, ReportDefinition, ReportExecution, ReportSchedule


class ReportDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportDefinition
        fields = [
            'id', 'name', 'code', 'category', 'description',
            'param_schema', 'default_formats', 'required_permission', 'is_confidential',
            'is_dataset',
        ]
        read_only_fields = fields


class ReportExecutionSerializer(serializers.ModelSerializer):
    is_terminal = serializers.BooleanField(read_only=True)
    definition_code = serializers.CharField(source='definition.code', read_only=True)
    definition_name = serializers.CharField(source='definition.name', read_only=True)
    requested_by_label = serializers.SerializerMethodField()

    class Meta:
        model = ReportExecution
        fields = [
            'id', 'definition', 'definition_code', 'definition_name',
            'requested_by', 'requested_by_label', 'parameters', 'status', 'is_terminal',
            'format', 'row_count', 'file_size', 'error', 'computation_refs',
            'expires_at', 'created_at', 'started_at', 'finished_at',
        ]
        read_only_fields = fields

    def get_requested_by_label(self, obj) -> str | None:
        u = obj.requested_by
        if u is None:
            return None
        return f'{u.first_name} {u.last_name}'.strip() or u.email


class GenerateReportSerializer(serializers.Serializer):
    code = serializers.CharField()
    parameters = serializers.DictField(required=False, default=dict)
    format = serializers.ChoiceField(choices=ReportExecution.Format.choices,
                                     default=ReportExecution.Format.XLSX)


class ReportScheduleSerializer(serializers.ModelSerializer):
    definition_code = serializers.SlugRelatedField(
        slug_field='code', source='definition', queryset=ReportDefinition.objects.all())
    definition_name = serializers.CharField(source='definition.name', read_only=True)
    delivery_target_code = serializers.CharField(
        source='delivery_target.code', read_only=True, default=None,
    )

    class Meta:
        model = ReportSchedule
        fields = [
            'id', 'name', 'definition_code', 'definition_name', 'parameters', 'format',
            'cron_minute', 'cron_hour', 'cron_day_of_week', 'cron_day_of_month',
            'cron_month_of_year', 'recipients', 'delivery', 'delivery_target',
            'delivery_target_code', 'is_enabled',
            'last_run_at', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'definition_name', 'delivery_target_code',
                            'last_run_at', 'created_at', 'updated_at']

    def validate(self, attrs):
        delivery = attrs.get('delivery', getattr(self.instance, 'delivery', None))
        target = attrs.get('delivery_target', getattr(self.instance, 'delivery_target', None))
        if delivery == ReportSchedule.Delivery.TARGET and target is None:
            raise serializers.ValidationError(
                {'delivery_target': 'Choose a delivery target for target delivery.'},
            )
        return attrs


class DeliveryTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryTarget
        fields = ['id', 'code', 'name', 'kind', 'config', 'credential_env',
                  'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
