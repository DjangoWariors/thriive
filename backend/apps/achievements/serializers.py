from rest_framework import serializers

from .models import Achievement, AchievementSnapshot, Alert, AlertRule


class AchievementListSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    kpi_name = serializers.CharField(source='kpi.name', read_only=True)
    # The list renders target/achieved, so it needs the unit too — without it every
    # count KPI (outlets, calls, SKUs) gets formatted as rupees.
    kpi_unit = serializers.CharField(source='kpi.unit', read_only=True)
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    entity_code = serializers.CharField(source='entity.code', read_only=True)
    channel_code = serializers.CharField(source='channel.code', read_only=True, default=None)

    class Meta:
        model = Achievement
        fields = [
            'id', 'target_period', 'kpi', 'kpi_code', 'kpi_name', 'kpi_unit', 'entity',
            'entity_name', 'entity_code', 'channel_code', 'target_value', 'achieved_value',
            'achievement_pct', 'projected_pct', 'gap_to_target', 'growth_pct', 'is_provisional',
        ]


class AchievementDetailSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    kpi_name = serializers.CharField(source='kpi.name', read_only=True)
    kpi_unit = serializers.CharField(source='kpi.unit', read_only=True)
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    period_name = serializers.CharField(source='target_period.name', read_only=True)

    class Meta:
        model = Achievement
        fields = [
            'id', 'target_period', 'period_name', 'kpi', 'kpi_code', 'kpi_name', 'kpi_unit',
            'entity', 'entity_name', 'channel', 'target_value', 'achieved_value', 'gross_value',
            'returns_value', 'achievement_pct', 'gap_to_target', 'daily_run_rate',
            'projected_value', 'projected_pct', 'required_run_rate', 'working_days_elapsed',
            'working_days_total', 'ly_value', 'growth_pct', 'is_provisional', 'computed_at',
            'computation_id',
        ]


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AchievementSnapshot
        fields = ['id', 'achievement', 'snapshot_date', 'achieved_value', 'achievement_pct',
                  'projected_pct']


class AlertSerializer(serializers.ModelSerializer):
    rule_code = serializers.CharField(source='rule.code', read_only=True)
    metric = serializers.CharField(source='rule.metric', read_only=True)
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    kpi_code = serializers.CharField(source='kpi.code', read_only=True, default=None)

    class Meta:
        model = Alert
        fields = ['id', 'rule', 'rule_code', 'metric', 'entity', 'entity_name', 'target_period',
                  'kpi', 'kpi_code', 'metric_value', 'severity', 'status', 'message', 'computed_at']


class AlertRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = [
            'id', 'name', 'code', 'metric', 'comparator', 'threshold', 'scope_entity_types',
            'scope_channels', 'kpi', 'severity', 'recipient_role', 'message_template',
            'is_enabled', 'version', 'is_current',
        ]
        read_only_fields = ['id', 'version', 'is_current']


class ComputeRequestSerializer(serializers.Serializer):
    period_id = serializers.IntegerField()


# ── dashboard payload (documentation only; assembled by DashboardService) ──────
class DashboardKpiCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kpi_code = serializers.CharField()
    kpi_name = serializers.CharField()
    unit = serializers.CharField(allow_blank=True)
    weight_pct = serializers.CharField(allow_null=True)
    target = serializers.CharField()
    achieved = serializers.CharField()
    pct = serializers.CharField()
    projected_pct = serializers.CharField()
    required_run_rate = serializers.CharField()
    gap = serializers.CharField()
    growth_pct = serializers.CharField(allow_null=True)
    multiplier = serializers.CharField(allow_null=True)
    is_provisional = serializers.BooleanField()


class DashboardSerializer(serializers.Serializer):
    entity = serializers.DictField(allow_null=True)
    summary = serializers.DictField()
    kpi_cards = DashboardKpiCardSerializer(many=True)
    child_ranking = serializers.ListField(child=serializers.DictField(), allow_null=True)
    trend = serializers.ListField(child=serializers.DictField())
    channel_mix = serializers.ListField(child=serializers.DictField())
    alerts = serializers.ListField(child=serializers.DictField())
    modules = serializers.DictField()
