"""I/O shaping for the incentives API. All writes delegate to services."""
from datetime import date

from rest_framework import serializers

from apps.hierarchy.models import Channel, Node, NodeType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetPeriod

from .models import (
    ExceptionCategory,
    IncentiveScheme,
    MultiplierTier,
    Payout,
    PayoutCycle,
    PayoutException,
    PayoutLineItem,
    PayoutRun,
    SchemeGate,
    SchemeKPI,
    VariablePay,
)


def _user_full_name(user):
    if user is None:
        return None
    return f'{user.first_name} {user.last_name}'.strip() or user.email


def _current_kpis():
    return KPIDefinition.objects.filter(is_current=True, is_active=True)


# ── scheme config ──────────────────────────────────────────────────────────────

class TierSerializer(serializers.ModelSerializer):
    class Meta:
        model = MultiplierTier
        fields = ['min_achievement_pct', 'max_achievement_pct', 'multiplier']


class SchemeKPIWriteSerializer(serializers.Serializer):
    kpi = serializers.PrimaryKeyRelatedField(queryset=_current_kpis())
    incentive_category = serializers.ChoiceField(
        choices=SchemeKPI.CATEGORY_CHOICES, default=SchemeKPI.SALES,
    )
    weightage = serializers.DecimalField(max_digits=8, decimal_places=2)
    min_qualifying_pct = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True, default=None,
    )
    multiplier_cap = serializers.DecimalField(
        max_digits=6, decimal_places=3, required=False, allow_null=True, default=None,
    )
    display_order = serializers.IntegerField(required=False, default=0)
    tiers = TierSerializer(many=True)


class SchemeGateWriteSerializer(serializers.Serializer):
    kpi = serializers.PrimaryKeyRelatedField(queryset=_current_kpis())
    operator = serializers.ChoiceField(choices=SchemeGate.OPERATOR_CHOICES, default=SchemeGate.GTE)
    threshold_pct = serializers.DecimalField(max_digits=8, decimal_places=2)
    display_order = serializers.IntegerField(required=False, default=0)


class SchemeGateReadSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    kpi_name = serializers.CharField(source='kpi.name', read_only=True)

    class Meta:
        model = SchemeGate
        fields = ['id', 'kpi', 'kpi_code', 'kpi_name', 'operator', 'threshold_pct', 'display_order']


class SchemeWriteSerializer(serializers.Serializer):
    """Full scheme payload (create and update-as-new-version share this shape).
    Cross-field/business validation lives in SchemeService.validate_config."""

    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=50)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    target_entity_type = serializers.PrimaryKeyRelatedField(
        queryset=NodeType.objects.filter(is_current=True, is_active=True),
    )
    channel = serializers.PrimaryKeyRelatedField(
        queryset=Channel.objects.filter(is_active=True), required=False, allow_null=True,
        default=None,
    )
    payout_frequency = serializers.ChoiceField(
        choices=IncentiveScheme.FREQUENCY_CHOICES, default=IncentiveScheme.MONTHLY,
    )
    vp_basis_pct = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, default=100,
    )
    overall_cap_pct = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True, default=None,
    )
    gates = SchemeGateWriteSerializer(many=True, required=False, default=list)
    gatekeeper_action = serializers.ChoiceField(
        choices=IncentiveScheme.GATEKEEPER_ACTION_CHOICES,
        default=IncentiveScheme.ZERO_PAYOUT,
    )
    effective_from = serializers.DateField(required=False, default=date.today)
    kpis = SchemeKPIWriteSerializer(many=True)


class SchemeKPIReadSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source='kpi.code', read_only=True)
    kpi_name = serializers.CharField(source='kpi.name', read_only=True)
    tiers = TierSerializer(many=True, read_only=True)

    class Meta:
        model = SchemeKPI
        fields = ['id', 'kpi', 'kpi_code', 'kpi_name', 'incentive_category', 'weightage',
                  'min_qualifying_pct', 'multiplier_cap', 'display_order', 'tiers']


class SchemeListSerializer(serializers.ModelSerializer):
    entity_type_code = serializers.CharField(source='target_entity_type.code', read_only=True)
    entity_type_name = serializers.CharField(source='target_entity_type.name', read_only=True)
    channel_code = serializers.CharField(source='channel.code', read_only=True, default=None)
    kpi_count = serializers.IntegerField(source='kpis.count', read_only=True)
    has_gatekeeper = serializers.SerializerMethodField()

    class Meta:
        model = IncentiveScheme
        fields = ['id', 'code', 'name', 'description', 'entity_type_code', 'entity_type_name',
                  'channel_code', 'payout_frequency', 'vp_basis_pct', 'overall_cap_pct',
                  'has_gatekeeper',
                  'kpi_count', 'version', 'is_current', 'is_active', 'effective_from',
                  'updated_at']

    def get_has_gatekeeper(self, obj) -> bool:
        return obj.gates.exists()


class SchemeDetailSerializer(serializers.ModelSerializer):
    entity_type_code = serializers.CharField(source='target_entity_type.code', read_only=True)
    entity_type_name = serializers.CharField(source='target_entity_type.name', read_only=True)
    channel_code = serializers.CharField(source='channel.code', read_only=True, default=None)
    gates = SchemeGateReadSerializer(many=True, read_only=True)
    kpis = SchemeKPIReadSerializer(many=True, read_only=True)

    class Meta:
        model = IncentiveScheme
        fields = ['id', 'code', 'name', 'description', 'target_entity_type',
                  'entity_type_code', 'entity_type_name', 'channel', 'channel_code',
                  'payout_frequency', 'vp_basis_pct', 'overall_cap_pct', 'gates',
                  'gatekeeper_action',
                  'kpis', 'version',
                  'is_current', 'is_active', 'effective_from', 'effective_to', 'updated_at']


class SchemeValidateResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.CharField())


# ── variable pay ───────────────────────────────────────────────────────────────

class VariablePaySerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    entity_code = serializers.CharField(source='entity.code', read_only=True)
    period_code = serializers.CharField(source='target_period.code', read_only=True)

    class Meta:
        model = VariablePay
        fields = ['id', 'entity', 'entity_name', 'entity_code', 'target_period',
                  'period_code', 'amount', 'eligible_working_days', 'source', 'updated_at']
        read_only_fields = ['id', 'source', 'updated_at']


class VariablePayUpsertSerializer(serializers.Serializer):
    entity = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.filter(is_current=True, is_active=True),
    )
    target_period = serializers.PrimaryKeyRelatedField(queryset=TargetPeriod.objects.all())
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    eligible_working_days = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0,
    )


class VariablePayBulkSerializer(serializers.Serializer):
    target_period = serializers.PrimaryKeyRelatedField(queryset=TargetPeriod.objects.all())
    # [{entity_code, amount, eligible_working_days?}]
    rows = serializers.ListField(child=serializers.DictField(), allow_empty=False)


# ── payout runs ────────────────────────────────────────────────────────────────

class PayoutRunSerializer(serializers.ModelSerializer):
    scheme_code = serializers.CharField(source='scheme.code', read_only=True)
    scheme_name = serializers.CharField(source='scheme.name', read_only=True)
    scheme_version = serializers.IntegerField(source='scheme.version', read_only=True)
    period_code = serializers.CharField(source='target_period.code', read_only=True)
    submitted_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PayoutRun
        fields = ['id', 'scheme', 'scheme_code', 'scheme_name', 'scheme_version',
                  'target_period', 'period_code', 'kind', 'cycle', 'reference_run', 'status',
                  'computation_log_id',
                  'submitted_by', 'submitted_by_name', 'submitted_at',
                  'approved_by', 'approved_by_name', 'approved_at', 'rejection_reason',
                  'paid_at', 'payment_ref', 'entities_processed', 'error_count',
                  'total_payout', 'errors', 'created_at', 'updated_at']

    def _full_name(self, user):
        if user is None:
            return None
        return f'{user.first_name} {user.last_name}'.strip() or user.email

    def get_submitted_by_name(self, obj):
        return self._full_name(obj.submitted_by)

    def get_approved_by_name(self, obj):
        return self._full_name(obj.approved_by)


class AdjustRequestSerializer(serializers.Serializer):
    reference_run_id = serializers.IntegerField()
    cycle_id = serializers.IntegerField()


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField()


class MarkPaidSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(required=False, allow_blank=True, default='')


# ── payouts ────────────────────────────────────────────────────────────────────

class PayoutLineItemSerializer(serializers.ModelSerializer):
    kpi_name = serializers.CharField(source='scheme_kpi.kpi.name', read_only=True)
    kpi_id = serializers.IntegerField(source='scheme_kpi.kpi_id', read_only=True)
    incentive_category = serializers.CharField(
        source='scheme_kpi.incentive_category', read_only=True,
    )

    class Meta:
        model = PayoutLineItem
        fields = ['id', 'kpi_code', 'kpi_name', 'kpi_id', 'incentive_category',
                  'target_value', 'achieved_value', 'achievement_pct', 'tier_min',
                  'tier_max', 'base_multiplier', 'applied_multiplier', 'weightage',
                  'weighted_multiplier', 'line_payout', 'treatment']


class PayoutListSerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    entity_code = serializers.CharField(source='entity.code', read_only=True)
    entity_type_code = serializers.CharField(source='entity.entity_type.code', read_only=True)
    scheme_code = serializers.CharField(source='scheme.code', read_only=True)
    run_status = serializers.CharField(source='run.status', read_only=True)
    has_exception = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = ['id', 'run', 'run_status', 'scheme', 'scheme_code', 'target_period',
                  'entity', 'entity_name', 'entity_code', 'entity_type_code',
                  'variable_pay_amount', 'proration_factor', 'eligible_vp',
                  'gatekeeper_status', 'has_exception', 'gross_payout', 'capped',
                  'total_payout', 'total_multiplier', 'hold_status', 'hold_reason',
                  'adjustment_amount']

    def get_has_exception(self, obj) -> bool:
        return obj.exception_id is not None


class ExceptionCategorySerializer(serializers.ModelSerializer):
    channel_code = serializers.CharField(source='channel.code', read_only=True, default=None)

    class Meta:
        model = ExceptionCategory
        fields = ['id', 'code', 'name', 'description', 'channel', 'channel_code',
                  'duration_config', 'default_sales_kpi_action',
                  'default_execution_kpi_action', 'default_gatekeeper_action',
                  'requires_dates', 'workflow_definition_code']


class PayoutExceptionSerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    entity_code = serializers.CharField(source='entity.code', read_only=True)
    period_code = serializers.CharField(source='target_period.code', read_only=True)
    scheme_code = serializers.CharField(source='scheme.code', read_only=True, default=None)
    category_name = serializers.CharField(source='category_ref.name', read_only=True, default=None)
    requested_by_name = serializers.SerializerMethodField()
    impact_amount = serializers.SerializerMethodField()
    workflow_id = serializers.SerializerMethodField()
    workflow_status = serializers.SerializerMethodField()
    current_step_name = serializers.SerializerMethodField()

    children_count = serializers.IntegerField(source='children.count', read_only=True)

    class Meta:
        model = PayoutException
        fields = ['id', 'entity', 'entity_name', 'entity_code', 'target_period',
                  'period_code', 'scheme', 'scheme_code', 'category', 'category_ref',
                  'category_name', 'sales_kpi_action', 'execution_kpi_action',
                  'gatekeeper_action', 'reason', 'reference_date', 'parent',
                  'children_count', 'status', 'requested_by',
                  'requested_by_name', 'approved_by', 'approved_at', 'rejection_reason',
                  'impact_amount', 'workflow_id', 'workflow_status', 'current_step_name',
                  'created_at']
        read_only_fields = ['id', 'status', 'category_ref', 'parent', 'children_count',
                            'requested_by', 'approved_by',
                            'approved_at', 'rejection_reason', 'created_at']

    def get_requested_by_name(self, obj):
        user = obj.requested_by
        if user is None:
            return None
        return f'{user.first_name} {user.last_name}'.strip() or user.email

    def _instance(self, obj):
        # Memoize the governing workflow instance on the object to avoid repeat queries
        # across the four method fields.
        if not hasattr(obj, '_wf_instance'):
            from apps.workflows.services import WorkflowService
            obj._wf_instance = WorkflowService.for_subject('incentives.PayoutException', obj.pk)
        return obj._wf_instance

    def get_impact_amount(self, obj) -> str | None:
        inst = self._instance(obj)
        return (inst.context_data or {}).get('impact_amount') if inst else None

    def get_workflow_id(self, obj) -> int | None:
        inst = self._instance(obj)
        return inst.pk if inst else None

    def get_workflow_status(self, obj) -> str | None:
        inst = self._instance(obj)
        return inst.status if inst else None

    def get_current_step_name(self, obj) -> str | None:
        inst = self._instance(obj)
        if inst is None:
            return None
        step = next((s for s in inst.steps.all() if s.status in ('active', 'escalated')), None)
        return step.name if step else None


class PayoutDetailSerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source='entity.name', read_only=True)
    entity_code = serializers.CharField(source='entity.code', read_only=True)
    scheme_code = serializers.CharField(source='scheme.code', read_only=True)
    scheme_name = serializers.CharField(source='scheme.name', read_only=True)
    scheme_version = serializers.IntegerField(source='scheme.version', read_only=True)
    period_code = serializers.CharField(source='target_period.code', read_only=True)
    period_name = serializers.CharField(source='target_period.name', read_only=True)
    run_status = serializers.CharField(source='run.status', read_only=True)
    line_items = PayoutLineItemSerializer(many=True, read_only=True)
    exception = PayoutExceptionSerializer(read_only=True)
    computed_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Payout
        fields = ['id', 'run', 'run_status', 'scheme', 'scheme_code', 'scheme_name',
                  'scheme_version', 'target_period', 'period_code', 'period_name',
                  'entity', 'entity_name', 'entity_code', 'variable_pay_amount',
                  'proration_factor', 'eligible_vp', 'gatekeeper_status', 'gate_results',
                  'exception',
                  'gross_payout', 'capped', 'total_payout', 'total_multiplier',
                  'hold_status', 'hold_reason', 'adjustment_amount',
                  'computation_id', 'computed_at', 'line_items']


class PayoutSummarySerializer(serializers.Serializer):
    total_payout = serializers.CharField()
    entities = serializers.IntegerField()
    capped_count = serializers.IntegerField()
    gatekeeper_failed_count = serializers.IntegerField()
    exception_count = serializers.IntegerField()


# ── payout cycles (month-close) ──────────────────────────────────────────────────

class PayoutCycleSerializer(serializers.ModelSerializer):
    period_code = serializers.CharField(source='target_period.code', read_only=True)
    period_name = serializers.CharField(source='target_period.name', read_only=True)
    period_type = serializers.CharField(source='target_period.period_type', read_only=True)
    finalized_by_name = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    disbursed_by_name = serializers.SerializerMethodField()
    is_ready = serializers.SerializerMethodField()

    class Meta:
        model = PayoutCycle
        fields = ['id', 'target_period', 'period_code', 'period_name', 'period_type', 'status',
                  'readiness', 'is_ready', 'readiness_overridden', 'override_reason',
                  'finalized_at', 'finalized_by', 'finalized_by_name', 'achievement_computation_id',
                  'submitted_by', 'submitted_by_name', 'submitted_at',
                  'approved_by', 'approved_by_name', 'approved_at',
                  'disbursed_by', 'disbursed_by_name', 'disbursed_at',
                  'register_ref', 'total_payout', 'created_at', 'updated_at']

    def get_is_ready(self, obj) -> bool | None:
        return (obj.readiness or {}).get('is_ready')

    def get_finalized_by_name(self, obj):
        return _user_full_name(obj.finalized_by)

    def get_submitted_by_name(self, obj):
        return _user_full_name(obj.submitted_by)

    def get_approved_by_name(self, obj):
        return _user_full_name(obj.approved_by)

    def get_disbursed_by_name(self, obj):
        return _user_full_name(obj.disbursed_by)


class CycleCreateSerializer(serializers.Serializer):
    period_id = serializers.IntegerField()


class CycleFinalizeSerializer(serializers.Serializer):
    override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(required=False, allow_blank=True, default='')


class DisburseSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(required=False, allow_blank=True, default='')
    register_ref = serializers.CharField(required=False, allow_blank=True, default='')


class HoldSerializer(serializers.Serializer):
    reason = serializers.CharField()
