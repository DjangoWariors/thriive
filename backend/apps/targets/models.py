from decimal import Decimal

from django.db import models

from apps.core.models import BaseModel, VersionedMixin


class TargetPeriod(BaseModel):
    """A planning period. Targets are always set monthly — the month is the only period
    targets/plans attach to. The annual period exists purely as the fiscal-year container
    (it parents its 12 months in the calendar, and annual SIP payout runs compute against
    it); it never carries targets.
    """

    ANNUAL = 'annual'
    MONTHLY = 'monthly'
    SCHEME = 'scheme'
    CUSTOM = 'custom'
    PERIOD_TYPE_CHOICES = [
        (ANNUAL, 'Annual'),
        (MONTHLY, 'Monthly'),
        (SCHEME, 'Scheme'),
        (CUSTOM, 'Custom'),
    ]

    DRAFT = 'draft'
    PUBLISHED = 'published'
    LOCKED = 'locked'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (PUBLISHED, 'Published'),
        (LOCKED, 'Locked'),
        (CLOSED, 'Closed'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    fiscal_year = models.CharField(max_length=15, blank=True, default='', db_index=True)  # e.g. 2026-27
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPE_CHOICES, default=MONTHLY)
    start_date = models.DateField()
    end_date = models.DateField()
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='target_periods',
    )
    working_days = models.PositiveIntegerField(null=True, blank=True)
    path = models.CharField(max_length=1000, db_index=True, blank=True, default='')
    depth = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True)

    class Meta:
        db_table = 'targets_targetperiod'
        ordering = ['start_date', 'code']
        indexes = [
            models.Index(fields=['fiscal_year', 'period_type'], name='target_period_fy_type_idx'),
            models.Index(fields=['parent'], name='target_period_parent_idx'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'

    def save(self, *args, **kwargs):
        if self.parent_id:
            row = type(self).objects.values('path', 'depth').get(pk=self.parent_id)
            self.path = row['path'] + self.code + '/'
            self.depth = row['depth'] + 1
        else:
            self.path = f'/{self.code}/'
            self.depth = 0
        super().save(*args, **kwargs)

    def get_children(self):
        return self.children.filter(is_active=True).order_by('start_date', 'code')


class AllocationRecipe(BaseModel, VersionedMixin):
    """How a parent geography node's target splits among its children — a *blend* of weight
    components plus growth and constraints (see docs/TARGET_MODULE_REVAMP_PLAN.md §5).

    ``weight_components``: list of {source, key?, weight}. Sources:
      contribution     → child's share of KPI history over ``base_window``
      attribute        → a geography attribute (outlet_count, population, …)
      external_metric  → an ExternalMetric code (market index, census feeds)
      equal            → flat weight
    Component weights are normalised at compute time. ``constraints`` clamp each child's split
    (growth floor/cap vs base, absolute floor); the clamped delta redistributes so the parent
    total still reconciles exactly.
    """

    CONTRIBUTION = 'contribution'
    ATTRIBUTE = 'attribute'
    EXTERNAL_METRIC = 'external_metric'
    EQUAL = 'equal'
    WEIGHT_SOURCES = [CONTRIBUTION, ATTRIBUTE, EXTERNAL_METRIC, EQUAL]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='allocation_recipes',
    )
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='allocation_recipes',
    )
    # [{"source": "contribution", "weight": 70}, {"source": "attribute", "key": "outlet_count", "weight": 30}]
    weight_components = models.JSONField(default=list, blank=True)
    # {"basis": "ly_same_period"} — window the contribution/growth math reads history from
    base_window = models.JSONField(default=dict, blank=True)
    # {"default_pct": 12, "per_level_pct": {"ZONE": {"NORTH": 15}}}
    growth = models.JSONField(default=dict, blank=True)
    # {"min_growth_pct": 0, "max_growth_pct": 40, "floor_value": 0, "no_negative": true}
    constraints = models.JSONField(default=dict, blank=True)
    # {"unit": 1000}
    rounding = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'targets_allocationrecipe'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='target_recipe_code_ver_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} (v{self.version})'


class TargetPlan(BaseModel):
    """One planning exercise ("FY 2026-27 · GT · Core Value + EC"): owns its configuration,
    its simulation runs, its review cascade and its committed allocations. The plan — not the
    period — carries the planning lifecycle.
    """

    DRAFT = 'draft'
    IN_REVIEW = 'in_review'
    PUBLISHED = 'published'
    LOCKED = 'locked'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (IN_REVIEW, 'In review'),
        (PUBLISHED, 'Published'),
        (LOCKED, 'Locked'),
        (CLOSED, 'Closed'),
    ]
    # States whose committed numbers are live downstream (achievements, person targets).
    LIVE_STATUSES = (PUBLISHED, LOCKED, CLOSED)

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    period = models.ForeignKey(TargetPeriod, on_delete=models.PROTECT, related_name='plans')
    root_geography = models.ForeignKey(
        'hierarchy.GeographyNode', on_delete=models.PROTECT, related_name='target_plans',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='target_plans',
    )
    # Geography level code the plan materialises down to; '' = all the way to leaves.
    planning_grain = models.CharField(max_length=100, blank=True, default='')
    # Geography level codes whose owners get a ReviewTask in the cascade.
    review_levels = models.JSONField(default=list, blank=True)
    # SKU-group codes in scope for the product-split stage; [] = plan has no product axis.
    product_scope = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    owner = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='target_plans',
    )

    class Meta:
        db_table = 'targets_targetplan'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['period', 'status'], name='target_plan_period_status_idx'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} ({self.status})'


class PlanKpi(BaseModel):
    """One KPI inside a plan: which recipe splits it, how its baseline is built, and its
    top number. ``top_value`` is what the planner committed to (typed from the AOP letter
    or accepted from the derived suggestion); ``derived_top_value`` is always kept
    alongside as the sanity anchor (Σ baseline × (1 + growth)).
    """

    plan = models.ForeignKey(TargetPlan, on_delete=models.CASCADE, related_name='plan_kpis')
    kpi = models.ForeignKey('kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='plan_kpis')
    recipe = models.ForeignKey(
        AllocationRecipe, null=True, blank=True, on_delete=models.PROTECT, related_name='plan_kpis',
    )
    # {"components": [{"basis": "ly_same_period", "weight": 60}, {"basis": "l3m_avg", "weight": 40}]}
    baseline_spec = models.JSONField(default=dict, blank=True)
    # {"mode": "history"} or {"mode": "fixed", "mix": {"NPI": 8, "FOCUS": 25}}
    product_split = models.JSONField(default=dict, blank=True)
    top_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    derived_top_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'targets_plankpi'
        ordering = ['plan', 'kpi']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'kpi'], name='target_plankpi_uniq'),
        ]

    def __str__(self):
        return f'plan={self.plan_id} kpi={self.kpi_id}'


class PlanRun(BaseModel):
    """One computation over a plan (a stage of the AOP pipeline, or a realignment re-split).
    Runs write to ``RunAllocation`` staging — never to committed targets — until an explicit
    commit copies staging into ``TargetAllocation`` and snapshots the config used.
    """

    BASELINE = 'baseline'
    TOP_DOWN = 'top_down'
    SPATIAL = 'spatial'
    PRODUCT = 'product'
    REALIGN = 'realign'
    KIND_CHOICES = [
        (BASELINE, 'Baseline'),
        (TOP_DOWN, 'Top number'),
        (SPATIAL, 'Spatial split'),
        (PRODUCT, 'Product split'),
        (REALIGN, 'Realignment re-split'),
    ]

    PENDING = 'pending'
    RUNNING = 'running'
    STAGED = 'staged'
    COMMITTED = 'committed'
    DISCARDED = 'discarded'
    FAILED = 'failed'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (RUNNING, 'Running'),
        (STAGED, 'Staged'),
        (COMMITTED, 'Committed'),
        (DISCARDED, 'Discarded'),
        (FAILED, 'Failed'),
    ]

    plan = models.ForeignKey(TargetPlan, on_delete=models.CASCADE, related_name='runs')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    # Realign runs re-split only this subtree, holding its committed total fixed.
    scope_node = models.ForeignKey(
        'hierarchy.GeographyNode', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    config_snapshot = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    job = models.ForeignKey('jobs.BulkJob', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    committed_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'targets_planrun'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['plan', 'kind', 'status'], name='target_run_plan_kind_idx'),
        ]

    def __str__(self):
        return f'run plan={self.plan_id} {self.kind} ({self.status})'


class RunAllocation(BaseModel):
    """A staged target number produced by a run — same dimensions as ``TargetAllocation`` but
    invisible to achievements/incentives until the run commits. ``explain`` records the resolved
    weight vector per component (the RFP's "logics must be explained").
    """

    run = models.ForeignKey(PlanRun, on_delete=models.CASCADE, related_name='allocations')
    kpi = models.ForeignKey('kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='+')
    target_period = models.ForeignKey(TargetPeriod, on_delete=models.CASCADE, related_name='+')
    geography_node = models.ForeignKey('hierarchy.GeographyNode', on_delete=models.CASCADE, related_name='+')
    channel = models.ForeignKey('hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sku_group = models.ForeignKey(
        'master_data.SKUGroup', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    base_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    explain = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'targets_runallocation'
        indexes = [
            models.Index(fields=['run', 'kpi', 'geography_node'], name='target_runalloc_run_idx'),
        ]

    def __str__(self):
        return f'staged run={self.run_id} node={self.geography_node_id} = {self.value}'


class ReviewTask(BaseModel):
    """Cascade-review bookkeeping: one task per review-level territory, addressed to the
    territory's owner (resolved through the Assignment bridge when the cascade opens). The
    approval mechanics themselves are ``TargetRevision`` + the target_revision workflow —
    this row only tracks who has responded and how.
    """

    PENDING = 'pending'
    ACCEPTED = 'accepted'
    ADJUSTED = 'adjusted'
    ESCALATED = 'escalated'
    FORCE_CLOSED = 'force_closed'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (ACCEPTED, 'Accepted'),
        (ADJUSTED, 'Adjusted'),
        (ESCALATED, 'Escalated'),
        (FORCE_CLOSED, 'Force closed'),
    ]

    plan = models.ForeignKey(TargetPlan, on_delete=models.CASCADE, related_name='review_tasks')
    node = models.ForeignKey('hierarchy.GeographyNode', on_delete=models.CASCADE, related_name='+')
    owner_node = models.ForeignKey(
        'hierarchy.Node', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    submitted_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'targets_reviewtask'
        ordering = ['plan', 'node']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'node'], name='target_review_plan_node_uniq'),
        ]

    def __str__(self):
        return f'review plan={self.plan_id} node={self.node_id} ({self.status})'


class TargetAllocationQuerySet(models.QuerySet):
    def live(self):
        """Rows allowed to drive downstream reads (achievements, person targets, portals):
        plan-less rows (bulk imports), or rows committed by a plan that has actually gone
        live. Draft/in-review plan numbers stay invisible outside the plan workspace."""
        return self.filter(is_active=True).filter(
            models.Q(plan__isnull=True) | models.Q(plan__status__in=TargetPlan.LIVE_STATUSES))


class TargetAllocation(BaseModel):
    """A single committed target number, dimensioned by geography_node × KPI × period × channel
    × sku_group.

    Targets are geography-canonical: they attach to a territory, never to a person. A person's
    target is derived by rolling up the territories they own (see TargetService.derive_entity_targets).
    ``target_value`` is the system-set (plan-committed) number; ``override_value`` is a manual edit.
    The number that actually counts is ``effective_target`` (override if present).
    """

    PENDING = 'pending'
    APPROVED = 'approved'
    LOCKED = 'locked'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (APPROVED, 'Approved'),
        (LOCKED, 'Locked'),
    ]

    SYSTEM = 'system_disaggregated'
    MANUAL = 'manual'
    BULK = 'bulk_import'
    SOURCE_CHOICES = [
        (SYSTEM, 'System disaggregated'),
        (MANUAL, 'Manual'),
        (BULK, 'Bulk import'),
    ]

    target_period = models.ForeignKey(TargetPeriod, on_delete=models.CASCADE, related_name='allocations')
    # The plan whose run committed this number; null for plan-less rows (e.g. raw bulk imports).
    plan = models.ForeignKey(
        TargetPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='allocations',
    )
    kpi = models.ForeignKey('kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='target_allocations')
    # The canonical anchor: a territory. Sales attach to geography, so targets do too — target
    # and actual live on the same axis and reconcile without crossing the Assignment bridge.
    geography_node = models.ForeignKey(
        'hierarchy.GeographyNode', on_delete=models.CASCADE, related_name='target_allocations',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='target_allocations',
    )
    sku_group = models.ForeignKey(
        'master_data.SKUGroup', null=True, blank=True, on_delete=models.SET_NULL, related_name='target_allocations',
    )

    target_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    original_target_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    override_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    base_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    is_modified = models.BooleanField(default=False)
    modification_reason = models.TextField(blank=True, default='')
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SYSTEM)

    objects = TargetAllocationQuerySet.as_manager()

    class Meta:
        db_table = 'targets_targetallocation'
        ordering = ['target_period', 'kpi', 'geography_node']
        constraints = [
            # nulls_distinct=False: the all-channel/all-SKU row (NULL dims) must be unique too.
            models.UniqueConstraint(
                fields=['target_period', 'kpi', 'geography_node', 'channel', 'sku_group'],
                name='target_alloc_dim_uniq', nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=['target_period', 'kpi'], name='target_alloc_period_kpi_idx'),
            models.Index(fields=['target_period', 'geography_node'], name='target_alloc_geo_idx'),
            models.Index(fields=['status'], name='target_alloc_status_idx'),
        ]

    def __str__(self):
        return f'{self.geography_node_id}/{self.kpi_id} = {self.effective_target} ({self.target_period_id})'

    @property
    def effective_target(self):
        return self.override_value if self.override_value is not None else self.target_value


class RevisionPolicy(BaseModel, VersionedMixin):
    """Governs how far a *live* target may be revised before it needs approval or is blocked
    (the FMCG "change cap"). Scoped by period / channel / entity_type; the most specific current
    policy wins. With no matching policy, the platform keeps its default maker-checker behaviour
    (every live edit routes for approval; live = published-plan rows and all plan-less rows) —
    capping is opt-in by configuration.

    ``delta_pct`` is always measured against ``TargetAllocation.original_target_value`` so a series
    of small edits cannot cumulatively drift past the band.
    """

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    target_period = models.ForeignKey(
        TargetPeriod, null=True, blank=True, on_delete=models.CASCADE, related_name='revision_policies',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL, related_name='revision_policies',
    )
    entity_type = models.ForeignKey(
        'hierarchy.NodeType', null=True, blank=True, on_delete=models.SET_NULL, related_name='revision_policies',
    )

    # Within this %, a revision auto-approves. Between this and the ceiling, it escalates.
    auto_approve_within_pct = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('10'))
    # Above this %, the revision is blocked outright. Null = no hard ceiling.
    hard_ceiling_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_revisions_per_period = models.PositiveIntegerField(null=True, blank=True)
    freeze_after = models.DateField(null=True, blank=True)
    requires_reason = models.BooleanField(default=True)

    class Meta:
        db_table = 'targets_revisionpolicy'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='target_revpolicy_code_ver_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} (v{self.version})'


class TargetRevision(BaseModel):
    """Append-only history of a single target change — the displayable, exportable governance
    timeline. Complements (does not replace) ``audit.AuditLog`` (global stream) and
    ``audit.ComputationLog`` (compute provenance). Written for human-driven changes only:
    manual overrides and the sibling rebalances they trigger.
    """

    MANUAL = 'manual'
    REBALANCE = 'rebalance'
    SOURCE_CHOICES = [(MANUAL, 'Manual override'), (REBALANCE, 'Sibling rebalance')]

    AUTO = 'auto'
    ESCALATE = 'escalate'
    BAND_CHOICES = [(AUTO, 'Auto-approved'), (ESCALATE, 'Escalated')]

    APPROVED = 'approved'
    PENDING = 'pending'
    REJECTED = 'rejected'
    STATUS_CHOICES = [(APPROVED, 'Approved'), (PENDING, 'Pending'), (REJECTED, 'Rejected')]

    allocation = models.ForeignKey(TargetAllocation, on_delete=models.CASCADE, related_name='revisions')
    # For REBALANCE rows: the manual revision that caused them. Rejecting that revision
    # must also revert its side effects, or the parent total stays broken.
    triggered_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='side_effects',
    )
    old_value = models.DecimalField(max_digits=18, decimal_places=4)
    new_value = models.DecimalField(max_digits=18, decimal_places=4)
    delta = models.DecimalField(max_digits=18, decimal_places=4)
    delta_pct = models.DecimalField(max_digits=8, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=MANUAL)
    band = models.CharField(max_length=12, choices=BAND_CHOICES, default=AUTO)
    requested_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=APPROVED)
    approved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'targets_targetrevision'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['allocation', '-created_at'], name='target_rev_alloc_idx'),
            models.Index(fields=['status'], name='target_rev_status_idx'),
        ]

    def __str__(self):
        return f'rev alloc={self.allocation_id} {self.old_value}→{self.new_value} ({self.status})'
