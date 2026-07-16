"""Incentive scheme & payout schema.

An ``IncentiveScheme`` (versioned) targets one NodeType and weighs a set of KPIs
(``SchemeKPI``, weightages sum to 100) through step multiplier grids (``MultiplierTier``).
``VariablePay`` is the per-entity, per-period pay base — an HR fact independent of any
scheme; the scheme declares what share of it it pays against via ``vp_basis_pct``.

A ``PayoutRun`` is the stateful lifecycle object for one scheme × period computation
(computing → computed → under_review → approved → paid, with supersede on recompute).
``Payout`` / ``PayoutLineItem`` snapshot every input used (achievement values, matched
tier, applied multiplier, treatment) so a payout is explainable line by line years later.
``PayoutException`` overrides performance treatment per category (sales / execution /
gatekeeper) for one entity-period, with maker-checker approval.

ComputationLog (apps.audit) stays the append-only audit record: every compute writes one
with a full scheme config snapshot, and its id is stamped on the run and every payout.
"""
from django.db import models

from apps.core.models import BaseModel, VersionedMixin

_MONEY = dict(max_digits=15, decimal_places=2, default=0)
_VALUE = dict(max_digits=18, decimal_places=4, default=0)
_PCT_NULL = dict(max_digits=8, decimal_places=2, null=True, blank=True)
_MULT = dict(max_digits=6, decimal_places=3)


class IncentiveScheme(BaseModel, VersionedMixin):
    """A versioned incentive plan for one NodeType. Editing creates a new version;
    child SchemeKPIs/tiers are re-created against the new version row."""

    ZERO_PAYOUT = 'zero_payout'
    CAP_AT_1X = 'cap_at_1x'
    GATEKEEPER_ACTION_CHOICES = [
        (ZERO_PAYOUT, 'Zero payout'),
        (CAP_AT_1X, 'Cap multipliers at 1x'),
    ]

    MONTHLY = 'monthly'
    ANNUAL = 'annual'
    FREQUENCY_CHOICES = [(MONTHLY, 'Monthly'), (ANNUAL, 'Annual')]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True, default='')
    target_entity_type = models.ForeignKey(
        'hierarchy.NodeType', on_delete=models.PROTECT, related_name='incentive_schemes',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='incentive_schemes',
    )
    # SIP component: which period type this scheme's runs compute against. An 80/20
    # monthly/annual SIP = two schemes for the same entity type × channel whose
    # vp_basis_pct sum to 100 (surfaced by the SIP-structure view).
    payout_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=MONTHLY)
    # Share of the entity's VariablePay this scheme pays against (monthly scheme = 100).
    vp_basis_pct = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    # Total payout ≤ overall_cap_pct% × eligible VP. Null = uncapped.
    overall_cap_pct = models.DecimalField(**_PCT_NULL)

    # Gate criteria live in SchemeGate rows (all must pass); this is the single
    # combined consequence applied when any gate fails.
    gatekeeper_action = models.CharField(
        max_length=20, choices=GATEKEEPER_ACTION_CHOICES, default=ZERO_PAYOUT,
    )

    class Meta:
        db_table = 'incentives_scheme'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='inc_scheme_code_ver_uniq'),
        ]
        indexes = [
            models.Index(fields=['target_entity_type', 'is_current'], name='inc_scheme_type_cur_idx'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} (v{self.version})'


class SchemeKPI(BaseModel):
    """One weighted KPI inside a scheme. ``incentive_category`` is what PayoutException
    per-category actions key on (sales vs execution KPIs are treated differently on leave)."""

    SALES = 'sales'
    EXECUTION = 'execution'
    CATEGORY_CHOICES = [(SALES, 'Sales'), (EXECUTION, 'Execution')]

    scheme = models.ForeignKey(IncentiveScheme, on_delete=models.CASCADE, related_name='kpis')
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='scheme_kpis',
    )
    incentive_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=SALES)
    weightage = models.DecimalField(max_digits=8, decimal_places=2)  # Σ per scheme == 100.00
    # Below this achievement %, the KPI line pays zero (decelerator floor). Null = no floor.
    min_qualifying_pct = models.DecimalField(**_PCT_NULL)
    # Hard ceiling on the matched tier multiplier. Null = uncapped.
    multiplier_cap = models.DecimalField(null=True, blank=True, **_MULT)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'incentives_schemekpi'
        ordering = ['display_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['scheme', 'kpi'], name='inc_schemekpi_uniq'),
        ]

    def __str__(self):
        return f'{self.scheme.code}:{self.kpi.code} w={self.weightage}'


class MultiplierTier(BaseModel):
    """One step in a KPI's achievement→multiplier grid. Min inclusive, max exclusive;
    the last tier has max NULL (unlimited). Tiers must be contiguous from 0."""

    scheme_kpi = models.ForeignKey(SchemeKPI, on_delete=models.CASCADE, related_name='tiers')
    min_achievement_pct = models.DecimalField(max_digits=8, decimal_places=2)
    max_achievement_pct = models.DecimalField(**_PCT_NULL)
    multiplier = models.DecimalField(**_MULT)

    class Meta:
        db_table = 'incentives_multipliertier'
        ordering = ['min_achievement_pct']
        constraints = [
            models.UniqueConstraint(
                fields=['scheme_kpi', 'min_achievement_pct'], name='inc_tier_min_uniq',
            ),
        ]

    def __str__(self):
        upper = self.max_achievement_pct if self.max_achievement_pct is not None else '∞'
        return f'[{self.min_achievement_pct}–{upper}) → {self.multiplier}x'


class SchemeGate(BaseModel):
    """One gate criterion on a scheme. ALL gates must pass or the scheme's
    ``gatekeeper_action`` applies (RFP: RCPA ≥ 85 AND geofence ≥ 85 AND iQuest ≥ 80…).
    A gate KPI may be an external-metric KPI, so agency/SFA scores can gate payouts."""

    GTE = 'gte'
    GT = 'gt'
    OPERATOR_CHOICES = [(GTE, '≥'), (GT, '>')]

    scheme = models.ForeignKey(IncentiveScheme, on_delete=models.CASCADE, related_name='gates')
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='gate_schemes',
    )
    operator = models.CharField(max_length=5, choices=OPERATOR_CHOICES, default=GTE)
    threshold_pct = models.DecimalField(max_digits=8, decimal_places=2)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'incentives_schemegate'
        ordering = ['display_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['scheme', 'kpi'], name='inc_gate_scheme_kpi_uniq'),
        ]

    def __str__(self):
        return f'{self.scheme.code}: {self.kpi.code} {self.operator} {self.threshold_pct}%'


class VariablePay(BaseModel):
    """The monthly variable-pay base for one entity in one period — an HR/data fact.
    ``eligible_working_days`` prorates for mid-period joiners/transfers/approved leave."""

    MANUAL = 'manual'
    BULK_IMPORT = 'bulk_import'
    SOURCE_CHOICES = [(MANUAL, 'Manual'), (BULK_IMPORT, 'Bulk import')]

    entity = models.ForeignKey(
        'hierarchy.Node', on_delete=models.CASCADE, related_name='variable_pays',
    )
    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.CASCADE, related_name='variable_pays',
    )
    amount = models.DecimalField(**_MONEY)
    # Null = eligible for the full period (proration factor 1).
    eligible_working_days = models.PositiveIntegerField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=MANUAL)

    class Meta:
        db_table = 'incentives_variablepay'
        ordering = ['target_period', 'entity']
        constraints = [
            models.UniqueConstraint(fields=['entity', 'target_period'], name='inc_vp_entity_period_uniq'),
        ]
        indexes = [
            models.Index(fields=['target_period'], name='inc_vp_period_idx'),
        ]

    def __str__(self):
        return f'VP {self.entity_id}@{self.target_period_id}: {self.amount}'


class PayoutCycle(BaseModel):
    """One month's incentive close — *"June 2026 SIP payout"*. One per TargetPeriod
    (monthly or annual). It owns the readiness checklist, the finalize step (which freezes
    the period's achievements), its final PayoutRuns, and — in later phases — the review
    board, cycle-level approval and disbursement register.

    The lifecycle mirrors how an FMCG incentive-ops team actually closes a month:
    open (estimates feed dashboards) → finalizing (readiness green or audited override;
    achievements frozen) → computing (final runs off frozen numbers) → under_review →
    approved → disbursed → closed.
    """

    OPEN = 'open'
    FINALIZING = 'finalizing'
    COMPUTING = 'computing'
    UNDER_REVIEW = 'under_review'
    APPROVED = 'approved'
    DISBURSED = 'disbursed'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (OPEN, 'Open'),
        (FINALIZING, 'Finalizing'),
        (COMPUTING, 'Computing'),
        (UNDER_REVIEW, 'Under review'),
        (APPROVED, 'Approved'),
        (DISBURSED, 'Disbursed'),
        (CLOSED, 'Closed'),
    ]

    target_period = models.OneToOneField(
        'targets.TargetPeriod', on_delete=models.PROTECT, related_name='payout_cycle',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True)

    # Last computed readiness snapshot: {'is_ready': bool, 'checks': [{key,label,status,count,detail}]}.
    readiness = models.JSONField(default=dict, blank=True)
    readiness_overridden = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True, default='')

    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # The finalize ComputationLog whose achievement numbers this cycle is frozen against.
    achievement_computation_id = models.BigIntegerField(null=True, blank=True)

    submitted_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    disbursed_at = models.DateTimeField(null=True, blank=True)
    register_ref = models.CharField(max_length=100, blank=True, default='')

    total_payout = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'incentives_payoutcycle'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='inc_cycle_status_idx'),
        ]

    def __str__(self):
        return f'Cycle {self.target_period_id} ({self.status})'


class PayoutRun(BaseModel):
    """The lifecycle object for one scheme × period computation. Approved runs are
    immutable — corrections go reject → recompute (which supersedes). Sprint 9's
    workflow engine attaches to these status transitions.

    ``kind`` distinguishes the nightly **estimate** (auto-superseding, never submitted),
    the cycle's **final** run (computed off frozen achievements), and an **adjustment**
    (P5 — the delta vs a paid reference run). Estimate and final runs for the same
    scheme × period coexist; the live-uniqueness key is (scheme, period, kind)."""

    ESTIMATE = 'estimate'
    FINAL = 'final'
    ADJUSTMENT = 'adjustment'
    KIND_CHOICES = [
        (ESTIMATE, 'Estimate'),
        (FINAL, 'Final'),
        (ADJUSTMENT, 'Adjustment'),
    ]

    COMPUTING = 'computing'
    COMPUTED = 'computed'
    FAILED = 'failed'
    UNDER_REVIEW = 'under_review'
    APPROVED = 'approved'
    PAID = 'paid'
    SUPERSEDED = 'superseded'
    STATUS_CHOICES = [
        (COMPUTING, 'Computing'),
        (COMPUTED, 'Computed'),
        (FAILED, 'Failed'),
        (UNDER_REVIEW, 'Under review'),
        (APPROVED, 'Approved'),
        (PAID, 'Paid'),
        (SUPERSEDED, 'Superseded'),
    ]
    # Statuses considered "live" (at most one such run per scheme code × period).
    LIVE_STATUSES = (COMPUTING, COMPUTED, UNDER_REVIEW, APPROVED, PAID)
    # Live statuses that block starting a new run for the same scheme code × period.
    BLOCKING_STATUSES = (COMPUTING, UNDER_REVIEW, APPROVED, PAID)

    scheme = models.ForeignKey(IncentiveScheme, on_delete=models.PROTECT, related_name='runs')
    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.PROTECT, related_name='payout_runs',
    )
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default=FINAL, db_index=True)
    cycle = models.ForeignKey(
        PayoutCycle, null=True, blank=True, on_delete=models.SET_NULL, related_name='runs',
    )
    # Adjustment runs (P5) reference the paid run they compute a delta against.
    reference_run = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='adjustments',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=COMPUTING, db_index=True,
    )
    computation_log_id = models.BigIntegerField(null=True, blank=True)

    triggered_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    submitted_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_ref = models.CharField(max_length=100, blank=True, default='')

    entities_processed = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    total_payout = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # [{"entity_id": N, "code": "no_variable_pay", "error": "..."}]
    errors = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'incentives_payoutrun'
        ordering = ['-created_at']
        constraints = [
            # One live run per scheme × period × kind — estimate and final coexist; a new
            # run of the same kind supersedes the prior one.
            models.UniqueConstraint(
                fields=['scheme', 'target_period', 'kind'],
                name='inc_run_live_uniq',
                condition=~models.Q(status__in=['superseded', 'failed']),
            ),
        ]
        indexes = [
            models.Index(fields=['target_period', 'status'], name='inc_run_period_status_idx'),
            models.Index(fields=['cycle', 'kind'], name='inc_run_cycle_kind_idx'),
        ]

    def __str__(self):
        return f'Run #{self.pk} {self.scheme.code}@{self.target_period.code} ({self.status})'


class PayoutException(BaseModel):
    """Per-entity-period override of performance treatment, with maker-checker approval.
    ``category`` is a free-form reason class (maternity_leave, new_joiner, transfer, …) —
    client configuration, not a platform enum. Scheme-specific rows win over scheme-null."""

    ACTUAL = 'actual_performance'
    DEFAULT_1X = 'default_1x'
    ZERO = 'zero'
    KPI_ACTION_CHOICES = [
        (ACTUAL, 'Actual performance'),
        (DEFAULT_1X, 'Default to 1x'),
        (ZERO, 'Zero'),
    ]

    NO_EXEMPTION = 'no_exemption'
    EXEMPTED = 'exempted'
    GATEKEEPER_ACTION_CHOICES = [(NO_EXEMPTION, 'No exemption'), (EXEMPTED, 'Exempted')]

    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = [(PENDING, 'Pending'), (APPROVED, 'Approved'), (REJECTED, 'Rejected')]

    entity = models.ForeignKey(
        'hierarchy.Node', on_delete=models.CASCADE, related_name='payout_exceptions',
    )
    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.CASCADE, related_name='payout_exceptions',
    )
    # Set on auto-materialized children: approving a multi-month exception (category
    # duration_config) creates one approved child per following monthly period.
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children',
    )
    # The date duration rules key on (e.g. joining date for the new-joiner cutoff rule).
    reference_date = models.DateField(null=True, blank=True)
    scheme = models.ForeignKey(
        IncentiveScheme, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='payout_exceptions',
    )
    category = models.CharField(max_length=50, blank=True, default='')
    category_ref = models.ForeignKey(
        'incentives.ExceptionCategory', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='exceptions',
    )
    sales_kpi_action = models.CharField(max_length=20, choices=KPI_ACTION_CHOICES, default=ACTUAL)
    execution_kpi_action = models.CharField(max_length=20, choices=KPI_ACTION_CHOICES, default=ACTUAL)
    gatekeeper_action = models.CharField(
        max_length=20, choices=GATEKEEPER_ACTION_CHOICES, default=NO_EXEMPTION,
    )
    reason = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    requested_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    approved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'incentives_payoutexception'
        ordering = ['-created_at']
        constraints = [
            # One live (non-rejected) exception per dimension. NULL schemes are distinct in
            # Postgres, so split like Achievement's channel-null constraint pair.
            models.UniqueConstraint(
                fields=['entity', 'target_period', 'scheme'],
                name='inc_exc_dim_uniq',
                condition=models.Q(scheme__isnull=False) & ~models.Q(status='rejected'),
            ),
            models.UniqueConstraint(
                fields=['entity', 'target_period'],
                name='inc_exc_dim_noscheme_uniq',
                condition=models.Q(scheme__isnull=True) & ~models.Q(status='rejected'),
            ),
        ]
        indexes = [
            models.Index(fields=['target_period', 'status'], name='inc_exc_period_status_idx'),
        ]

    def __str__(self):
        return f'Exception {self.entity_id}@{self.target_period_id} ({self.status})'


class ExceptionCategory(BaseModel, VersionedMixin):
    """Configurable catalog of exception reasons (medical_leave, transfer, damage_expiry_claim, …).

    Generic-platform rule: the FMCG reasons are *seed data*, not a code enum. Each category
    pre-fills the default KPI treatment a maker would otherwise pick, and names the workflow
    definition that should govern requests of this kind (different reasons can route differently)."""

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    # Null = applies to every channel; set = only entities of this channel may use it.
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='exception_categories',
    )
    # Multi-month effect, expressed as config (not code):
    #   {}                                              → single period
    #   {"type": "fixed", "effect_months": N}           → covers N monthly periods
    #   {"type": "join_day_cutoff", "cutoff_day": 15,
    #    "months_on_or_before": 2, "months_after": 3}   → RFP new-joiner rule
    duration_config = models.JSONField(default=dict, blank=True)
    default_sales_kpi_action = models.CharField(
        max_length=20, choices=PayoutException.KPI_ACTION_CHOICES, default=PayoutException.ACTUAL,
    )
    default_execution_kpi_action = models.CharField(
        max_length=20, choices=PayoutException.KPI_ACTION_CHOICES, default=PayoutException.ACTUAL,
    )
    default_gatekeeper_action = models.CharField(
        max_length=20, choices=PayoutException.GATEKEEPER_ACTION_CHOICES,
        default=PayoutException.NO_EXEMPTION,
    )
    requires_dates = models.BooleanField(default=False)
    # Workflow definition code that governs this reason; blank → platform default.
    workflow_definition_code = models.CharField(max_length=80, blank=True, default='')

    class Meta:
        db_table = 'incentives_exceptioncategory'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='inc_exccat_code_ver_uniq'),
        ]
        indexes = [
            models.Index(fields=['code', 'is_current'], name='inc_exccat_code_cur_idx'),
        ]

    def __str__(self):
        return self.code


class Payout(BaseModel):
    """One entity's payout inside a run. Every input is snapshotted so the number is
    explainable without re-querying live config."""

    NOT_APPLICABLE = 'not_applicable'
    PASSED = 'passed'
    GK_FAILED = 'failed'
    EXEMPTED = 'exempted'
    GATEKEEPER_STATUS_CHOICES = [
        (NOT_APPLICABLE, 'Not applicable'),
        (PASSED, 'Passed'),
        (GK_FAILED, 'Failed'),
        (EXEMPTED, 'Exempted'),
    ]

    # Per-payee hold, applied during cycle review (pre-disbursement). A held payout is
    # visible and audited but excluded from the disbursement register; released before the
    # register is cut it pays normally, held it rides the next cycle's adjustment run (P5).
    HOLD_NONE = 'none'
    HOLD_HELD = 'held'
    HOLD_RELEASED = 'released'
    HOLD_STATUS_CHOICES = [
        (HOLD_NONE, 'Not held'),
        (HOLD_HELD, 'Held'),
        (HOLD_RELEASED, 'Released'),
    ]

    run = models.ForeignKey(PayoutRun, on_delete=models.CASCADE, related_name='payouts')
    # Denormalized from run for direct entity × period queries.
    scheme = models.ForeignKey(IncentiveScheme, on_delete=models.PROTECT, related_name='payouts')
    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.PROTECT, related_name='payouts',
    )
    entity = models.ForeignKey(
        'hierarchy.Node', on_delete=models.PROTECT, related_name='payouts',
    )

    variable_pay_amount = models.DecimalField(**_MONEY)
    proration_factor = models.DecimalField(max_digits=6, decimal_places=4, default=1)
    eligible_vp = models.DecimalField(**_MONEY)

    gatekeeper_status = models.CharField(
        max_length=20, choices=GATEKEEPER_STATUS_CHOICES, default=NOT_APPLICABLE,
    )
    # Per-gate explainability: [{kpi_code, achievement_pct, operator, threshold_pct, passed}]
    gate_results = models.JSONField(default=list, blank=True)
    exception = models.ForeignKey(
        PayoutException, null=True, blank=True, on_delete=models.SET_NULL, related_name='payouts',
    )

    gross_payout = models.DecimalField(**_MONEY)
    capped = models.BooleanField(default=False)
    total_payout = models.DecimalField(**_MONEY)
    # Σ weighted multipliers — the headline "multiplier" shown on dashboards.
    total_multiplier = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    computation_id = models.BigIntegerField(null=True, blank=True)

    hold_status = models.CharField(
        max_length=10, choices=HOLD_STATUS_CHOICES, default=HOLD_NONE, db_index=True,
    )
    hold_reason = models.TextField(blank=True, default='')

    # Adjustment-run rows only: the delta actually paid/recovered this cycle
    # (current recomputed total − the amount already paid on the referenced run).
    # Positive = arrears, negative = recovery. 0 on ordinary runs. ``total_payout`` stays
    # the full recomputed figure so the line items still reconcile to it.
    adjustment_amount = models.DecimalField(**_MONEY)

    class Meta:
        db_table = 'incentives_payout'
        ordering = ['-total_payout', 'entity_id']
        constraints = [
            models.UniqueConstraint(fields=['run', 'entity'], name='inc_payout_run_entity_uniq'),
        ]
        indexes = [
            models.Index(fields=['entity', 'target_period'], name='inc_payout_entity_period_idx'),
            models.Index(fields=['target_period', 'scheme'], name='inc_payout_period_scheme_idx'),
        ]

    def __str__(self):
        return f'Payout {self.entity_id}@{self.target_period_id}: {self.total_payout}'


class PayoutLineItem(BaseModel):
    """Per-KPI contribution inside a payout — the transparency record a rep sees:
    achievement → matched tier → base multiplier → applied multiplier → contribution."""

    ACTUAL = 'actual'
    DEFAULT_1X = 'default_1x'
    ZERO = 'zero'
    BELOW_THRESHOLD = 'below_threshold'
    CAPPED = 'capped'
    TREATMENT_CHOICES = [
        (ACTUAL, 'Actual'),
        (DEFAULT_1X, 'Default 1x'),
        (ZERO, 'Zero'),
        (BELOW_THRESHOLD, 'Below qualifying threshold'),
        (CAPPED, 'Capped'),
    ]

    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name='line_items')
    scheme_kpi = models.ForeignKey(SchemeKPI, on_delete=models.PROTECT, related_name='line_items')
    kpi_code = models.CharField(max_length=50)

    target_value = models.DecimalField(**_VALUE)
    achieved_value = models.DecimalField(**_VALUE)
    achievement_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    tier_min = models.DecimalField(**_PCT_NULL)
    tier_max = models.DecimalField(**_PCT_NULL)
    base_multiplier = models.DecimalField(default=0, **_MULT)
    applied_multiplier = models.DecimalField(default=0, **_MULT)
    weightage = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    weighted_multiplier = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    line_payout = models.DecimalField(**_MONEY)
    treatment = models.CharField(max_length=20, choices=TREATMENT_CHOICES, default=ACTUAL)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'incentives_payoutlineitem'
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.kpi_code}: {self.applied_multiplier}x → {self.line_payout}'
