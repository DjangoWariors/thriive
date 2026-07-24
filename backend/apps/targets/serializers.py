from rest_framework import serializers

from .models import (
    AllocationRecipe,
    PlanKpi,
    PlanRun,
    ReviewTask,
    RevisionPolicy,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
)


class TargetPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetPeriod
        fields = [
            'id', 'name', 'code', 'fiscal_year', 'period_type', 'start_date', 'end_date',
            'parent', 'channel', 'working_days', 'path', 'depth', 'status',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'path', 'depth', 'status', 'created_at', 'updated_at']


class TargetPeriodNodeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = TargetPeriod
        fields = ['id', 'name', 'code', 'period_type', 'start_date', 'end_date', 'status',
                  'working_days', 'depth', 'children']

    def get_children(self, obj):
        return TargetPeriodNodeSerializer(obj.get_children(), many=True).data


class TargetAllocationSerializer(serializers.ModelSerializer):
    effective_target = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    geography_name = serializers.SerializerMethodField()
    geography_code = serializers.SerializerMethodField()
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    period_code = serializers.CharField(source='target_period.code', read_only=True)

    class Meta:
        model = TargetAllocation
        fields = [
            'id', 'target_period', 'period_code', 'kpi', 'kpi_code',
            'geography_node', 'geography_name', 'geography_code',
            'channel', 'sku_group', 'target_value', 'original_target_value', 'override_value', 'base_value',
            'effective_target', 'status', 'is_modified', 'modification_reason', 'source',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_geography_name(self, obj):
        return obj.geography_node.name if obj.geography_node_id else None

    def get_geography_code(self, obj):
        return obj.geography_node.code if obj.geography_node_id else None


class RevisionPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = RevisionPolicy
        fields = [
            'id', 'name', 'code', 'target_period', 'channel', 'entity_type',
            'auto_approve_within_pct', 'hard_ceiling_pct', 'max_revisions_per_period',
            'freeze_after', 'requires_reason',
            'version', 'effective_from', 'effective_to', 'is_current', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'version', 'effective_from', 'effective_to', 'is_current', 'created_at', 'updated_at']


class TargetRevisionSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TargetRevision
        fields = [
            'id', 'allocation', 'old_value', 'new_value', 'delta', 'delta_pct', 'reason',
            'source', 'band', 'status', 'requested_by', 'requested_by_name',
            'approved_by', 'approved_by_name', 'approved_at', 'effective_date', 'created_at',
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return self._name(obj.requested_by)

    def get_approved_by_name(self, obj):
        return self._name(obj.approved_by)

    @staticmethod
    def _name(user):
        if user is None:
            return None
        full = f'{user.first_name} {user.last_name}'.strip()
        return full or str(user)


# ── plan aggregate ────────────────────────────────────────────────────────────
class AllocationRecipeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationRecipe
        fields = [
            'id', 'name', 'code', 'channel', 'kpi', 'weight_components', 'base_window',
            'growth', 'constraints', 'rounding',
            'version', 'effective_from', 'effective_to', 'is_current', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'version', 'effective_from', 'effective_to', 'is_current', 'created_at', 'updated_at']


class PlanKpiSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    kpi_name = serializers.CharField(source='kpi.name', read_only=True)
    recipe_code = serializers.CharField(source='recipe.code', read_only=True, default=None)

    class Meta:
        model = PlanKpi
        fields = ['id', 'kpi', 'kpi_code', 'kpi_name', 'recipe', 'recipe_code',
                  'baseline_spec', 'product_split', 'top_value', 'derived_top_value']
        read_only_fields = fields


class TargetPlanSerializer(serializers.ModelSerializer):
    period_code = serializers.CharField(source='period.code', read_only=True)
    period_type = serializers.CharField(source='period.period_type', read_only=True)
    root_geography_name = serializers.CharField(source='root_geography.name', read_only=True)
    root_geography_code = serializers.CharField(source='root_geography.code', read_only=True)
    kpis = PlanKpiSerializer(source='plan_kpis', many=True, read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = TargetPlan
        fields = [
            'id', 'name', 'code', 'period', 'period_code', 'period_type', 'root_geography',
            'root_geography_name', 'root_geography_code', 'channel', 'planning_grain',
            'review_levels', 'product_scope', 'settings', 'status', 'owner', 'kpis', 'progress',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_progress(self, obj):
        runs = {'staged': 0, 'committed': 0}
        committed_kinds = set()
        for kind, run_status in obj.runs.values_list('kind', 'status'):
            if run_status == PlanRun.STAGED:
                runs['staged'] += 1
            elif run_status == PlanRun.COMMITTED:
                runs['committed'] += 1
                committed_kinds.add(kind)
        tasks = list(obj.review_tasks.values_list('status', flat=True))
        open_statuses = (ReviewTask.PENDING, ReviewTask.ESCALATED)
        return {
            'runs': runs,
            'committed_stages': sorted(committed_kinds),
            'review': {'total': len(tasks), 'open': sum(1 for s in tasks if s in open_statuses)},
        }


class PlanKpiSpecSerializer(serializers.Serializer):
    kpi_id = serializers.IntegerField()
    recipe_id = serializers.IntegerField(required=False, allow_null=True)
    baseline_spec = serializers.DictField(required=False)
    product_split = serializers.DictField(required=False)
    top_value = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, allow_null=True)


class TargetPlanCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=50)
    period_id = serializers.IntegerField()
    root_geography_id = serializers.IntegerField()
    channel_id = serializers.IntegerField(required=False, allow_null=True)
    planning_grain = serializers.CharField(required=False, allow_blank=True, default='')
    review_levels = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    product_scope = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    settings = serializers.DictField(required=False, default=dict)
    kpis = PlanKpiSpecSerializer(many=True)


class PlanRunSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='plan.code', read_only=True)
    scope_node_code = serializers.CharField(source='scope_node.code', read_only=True, default=None)
    error = serializers.SerializerMethodField()

    class Meta:
        model = PlanRun
        fields = ['id', 'plan', 'plan_code', 'kind', 'status', 'scope_node', 'scope_node_code',
                  'config_snapshot', 'stats', 'job', 'error', 'committed_by', 'committed_at',
                  'created_at']
        read_only_fields = fields

    def get_error(self, run) -> str:
        """Why the run failed, so the workspace can say it instead of silently re-enabling
        the button. The task records the reason on its BulkJob, not on the run."""
        if run.status != PlanRun.FAILED or run.job_id is None:
            return ''
        messages = [m for row in (run.job.errors or []) for m in (row.get('errors') or [])]
        return messages[0] if messages else ''


class ReviewTaskSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='plan.code', read_only=True)
    node_name = serializers.CharField(source='node.name', read_only=True)
    node_code = serializers.CharField(source='node.code', read_only=True)
    node_level = serializers.CharField(source='node.level', read_only=True)
    owner_name = serializers.CharField(source='owner_node.name', read_only=True, default=None)

    class Meta:
        model = ReviewTask
        fields = ['id', 'plan', 'plan_code', 'node', 'node_name', 'node_code', 'node_level',
                  'owner_node', 'owner_name', 'status', 'submitted_by', 'submitted_at', 'notes']
        read_only_fields = fields


class PlanTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s for s, _ in TargetPlan.STATUS_CHOICES])
    force_over_budget = serializers.BooleanField(required=False, default=False)


class SetPlanTopSerializer(serializers.Serializer):
    kpi_id = serializers.IntegerField()
    value = serializers.DecimalField(max_digits=18, decimal_places=4)


class StartRunSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[PlanRun.BASELINE, PlanRun.SPATIAL, PlanRun.PRODUCT])


class RealignSerializer(serializers.Serializer):
    scope_node_id = serializers.IntegerField()


class CommitRunSerializer(serializers.Serializer):
    override_strategy = serializers.ChoiceField(choices=['keep', 'drop'], required=False, default='keep')


class ReviewAcceptSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class ReviewAdjustSerializer(serializers.Serializer):
    allocation_id = serializers.IntegerField()
    override_value = serializers.DecimalField(max_digits=18, decimal_places=4)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    rebalance = serializers.BooleanField(required=False, default=True)


class ReviewAdjustMineSerializer(ReviewAdjustSerializer):
    """Task-less adjust: the backend resolves which of the caller's open tasks contains
    the allocation (a reviewer may own several review territories)."""
    plan_id = serializers.IntegerField()


class ForceCloseSerializer(serializers.Serializer):
    reason = serializers.CharField()


# ── request serializers ──────────────────────────────────────────────────────
class GenerateYearSerializer(serializers.Serializer):
    fiscal_year = serializers.CharField(max_length=15, help_text='e.g. "2026-27"')
    start_month = serializers.IntegerField(required=False, default=4, min_value=1, max_value=12,
                                           help_text='Fiscal-year start month. 4 = April (default), 1 = calendar year.')
    channel_id = serializers.IntegerField(required=False, allow_null=True)
    working_days_per_month = serializers.IntegerField(required=False, default=26, min_value=1, max_value=31)


class ModifyAllocationSerializer(serializers.Serializer):
    override_value = serializers.DecimalField(max_digits=18, decimal_places=4)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    rebalance = serializers.BooleanField(required=False, default=True)


class ApproveAllSerializer(serializers.Serializer):
    scope_entity_id = serializers.IntegerField(required=False, allow_null=True)


class RejectAllocationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class PreflightSerializer(serializers.Serializer):
    override_value = serializers.DecimalField(max_digits=18, decimal_places=4)


class AllocationBulkImportSerializer(serializers.Serializer):
    data = serializers.CharField(required=False, allow_blank=True,
                                 help_text='Raw CSV text. Omit when uploading a file.')
    file = serializers.FileField(required=False, help_text='CSV file. Takes precedence over data.')
    reason = serializers.CharField(
        required=False, allow_blank=True, default='',
        help_text='Why the targets are changing. Carried onto every revision the upload '
                  'raises; required when a revision policy asks for one.')

    def validate(self, attrs):
        if not attrs.get('data') and not attrs.get('file'):
            raise serializers.ValidationError('Provide either CSV text in "data" or a "file".')
        return attrs
