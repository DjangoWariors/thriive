from rest_framework import serializers

from .models import (
    ExternalMetric,
    ExternalMetricValue,
    IntegrationBatch,
    KPIDefinition,
    KpiTemplate,
    Transaction,
)

_CONFIG_FIELDS = [
    'name', 'code', 'description', 'category', 'unit', 'decimal_places', 'kpi_type',
    'measure_config', 'ratio_config', 'growth_config', 'composite_config', 'boolean_config',
    'external_config', 'applicable_entity_types', 'channel_filter', 'sku_filter',
]


class KPIDefinitionSerializer(serializers.ModelSerializer):
    """Full KPI detail. Writes are delegated to KPIService via the viewset's
    perform_create/perform_update (which enforce versioning)."""

    class Meta:
        model = KPIDefinition
        fields = _CONFIG_FIELDS + [
            'id', 'version', 'effective_from', 'effective_to', 'is_current',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'version', 'effective_from', 'effective_to', 'is_current',
            'is_active', 'created_at', 'updated_at',
        ]
        # Drop DRF's auto (code, version) UniqueTogetherValidator. Because `version` is
        # read-only it gets filled from the model default (1), not the instance's real
        # version, so editing any KPI that's already on v2+ falsely trips "must make a
        # unique set". Integrity is guaranteed by the DB UniqueConstraint plus
        # KPIService.update_kpi(), which always inserts the next version.
        validators: list = []


class KPIDefinitionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = KPIDefinition
        fields = [
            'id', 'code', 'name', 'kpi_type', 'category', 'unit', 'decimal_places',
            'applicable_entity_types', 'channel_filter', 'version', 'is_current',
            # Per-type config so the list can render a compact read-only formula column.
            'measure_config', 'ratio_config', 'growth_config', 'composite_config',
            'boolean_config', 'external_config', 'sku_filter',
        ]


class KPIConfigValidateSerializer(serializers.ModelSerializer):
    """Accepts a candidate KPI config for /validate/ — same writable shape as the
    full serializer but never persisted."""

    class Meta:
        model = KPIDefinition
        fields = _CONFIG_FIELDS


class KpiTemplateSerializer(serializers.ModelSerializer):
    """Read-only — the builder's 'pick a template' gallery is populated from these."""

    class Meta:
        model = KpiTemplate
        fields = [
            'id', 'code', 'name', 'description', 'icon', 'display_order',
            'category', 'unit', 'decimal_places', 'kpi_type',
            'measure_config', 'ratio_config', 'growth_config', 'composite_config',
            'boolean_config', 'external_config', 'sku_filter',
        ]


class KPIPreviewSerializer(serializers.Serializer):
    config = KPIConfigValidateSerializer()
    entity_id = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    as_of = serializers.DateField(required=False, allow_null=True,
                                  help_text='Optional. When set, also returns the run-rate projection to the full period.')


class TransactionSerializer(serializers.ModelSerializer):
    # attributed_node_id is a plain id column (ingest perf, no FK) — the territory
    # label is resolved in bulk by the list view and passed through context.
    attributed_node_label = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'attributed_node_id', 'attributed_node_label', 'outlet_code', 'bill_ref',
            'sku_code', 'channel_code',
            'transaction_date', 'posted_date', 'transaction_type', 'transaction_level',
            'source', 'external_ref', 'gross_amount', 'discount_amount', 'tax_amount',
            'net_amount', 'quantity', 'uom', 'base_quantity', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'base_quantity', 'is_active', 'created_at']

    def get_attributed_node_label(self, obj) -> str:
        return self.context.get('node_labels', {}).get(obj.attributed_node_id, '')


class TransactionBulkImportSerializer(serializers.Serializer):
    data = serializers.CharField(
        required=False, allow_blank=True,
        help_text='Raw CSV text (with a header row). Omit when uploading a file.',
    )
    file = serializers.FileField(
        required=False, help_text='CSV file. Takes precedence over the data field.',
    )

    def validate(self, attrs):
        if not attrs.get('data') and not attrs.get('file'):
            raise serializers.ValidationError('Provide either CSV text in "data" or a "file".')
        return attrs


class ExternalMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalMetric
        fields = [
            'id', 'code', 'name', 'description', 'unit', 'decimal_places',
            'granularity', 'period_grain', 'default_aggregation',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']


class ExternalMetricValueSerializer(serializers.ModelSerializer):
    metric_code = serializers.CharField(source='metric.code', read_only=True)

    class Meta:
        model = ExternalMetricValue
        fields = [
            'id', 'metric', 'metric_code', 'entity', 'node_id', 'measured_on',
            'value', 'source', 'external_ref', 'created_at',
        ]
        read_only_fields = fields


class MetricValuePushSerializer(serializers.Serializer):
    """JSON push body: {source, client_batch_ref?, rows: [...]}. Rows are validated
    per-row by IngestionService (partial accept), not here."""

    source = serializers.CharField(max_length=30)
    client_batch_ref = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    rows = serializers.ListField(
        child=serializers.DictField(), min_length=1, max_length=5000,
        help_text='Each row: {metric_code, entity_id|node_id, measured_on, value, external_ref?}',
    )


class MetricValueBulkImportSerializer(TransactionBulkImportSerializer):
    """CSV import body for metric values — same file/data shape as transactions."""


class TransactionPushSerializer(serializers.Serializer):
    """JSON push body for transactions. Rows are validated per-row by
    IngestionService (partial accept); external_ref is required on every row."""

    source = serializers.ChoiceField(choices=['api_push', 'dms_sync', 'sfa_sync'])
    client_batch_ref = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    rows = serializers.ListField(
        child=serializers.DictField(), min_length=1, max_length=5000,
        help_text='Each row: Transaction fields incl. attributed_node_id, transaction_date, external_ref.',
    )


class IntegrationBatchSerializer(serializers.ModelSerializer):
    pushed_by_display = serializers.CharField(source='pushed_by.__str__', read_only=True, default='')

    class Meta:
        model = IntegrationBatch
        fields = [
            'id', 'batch_kind', 'source', 'client_batch_ref', 'status',
            'received_count', 'accepted_count', 'rejected_count', 'row_errors',
            'pushed_by', 'pushed_by_display', 'created_at',
        ]
        read_only_fields = fields
