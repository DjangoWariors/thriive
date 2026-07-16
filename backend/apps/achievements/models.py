"""Achievement & alert schema — two layers of the same compute pass.

An ``Achievement`` is the join of an actual (computed by ``KPICalculator``) against a target
(``TargetAllocation.effective_target``) for one entity × KPI × period — the person fact that
feeds SIP payouts and dashboards, resolved through the Assignment bridge. The daily computation
upserts these and writes a same-day ``AchievementSnapshot`` so trend/run-rate-over-time can be
charted without recomputing history.

A ``TerritoryAchievement`` is the geography-canonical plan-tracking fact underneath: one row
per committed ``TargetAllocation`` dimension, aggregated over the node's subtree with no
Assignment resolution (transfer-proof by construction).

``AlertRule`` is a generic, config-driven threshold over an Achievement metric (or a derived
one like ``no_sale_days``). Nothing here is FMCG-specific: "target-at-risk territory" is just
``metric=projected_pct, comparator=lt, threshold=90`` against entities of a given type.
"""
from django.db import models

from apps.core.models import BaseModel, VersionedMixin

_MONEY = dict(max_digits=18, decimal_places=4, default=0)
_PCT = dict(max_digits=8, decimal_places=2, null=True, blank=True)


class Achievement(BaseModel):
    """One actual-vs-target row, dimensioned by entity × KPI × period × channel."""

    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.CASCADE, related_name='achievements',
    )
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='achievements',
    )
    entity = models.ForeignKey(
        'hierarchy.Node', on_delete=models.CASCADE, related_name='achievements',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='achievements',
    )

    # Core measures
    target_value = models.DecimalField(**_MONEY)
    achieved_value = models.DecimalField(**_MONEY)
    gross_value = models.DecimalField(**_MONEY)
    returns_value = models.DecimalField(**_MONEY)
    achievement_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    gap_to_target = models.DecimalField(**_MONEY)

    # Run-rate / month-end projection (working-day aware)
    daily_run_rate = models.DecimalField(**_MONEY)
    projected_value = models.DecimalField(**_MONEY)
    projected_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    required_run_rate = models.DecimalField(**_MONEY)
    working_days_elapsed = models.PositiveIntegerField(default=0)
    working_days_total = models.PositiveIntegerField(default=0)

    # Growth vs last-year-same-period (optional — null when no base data)
    ly_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    growth_pct = models.DecimalField(**_PCT)

    # Lifecycle
    is_provisional = models.BooleanField(default=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    computation_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'achievements_achievement'
        ordering = ['target_period', 'kpi', 'entity']
        constraints = [
            # nulls_distinct=False: channel-null rows must be unique too, and the compute
            # rewrite's ON CONFLICT bulk upsert needs one plain (non-partial) index to infer.
            models.UniqueConstraint(
                fields=['target_period', 'kpi', 'entity', 'channel'],
                name='achievement_dim_uniq',
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=['entity', 'target_period'], name='achv_entity_period_idx'),
            models.Index(fields=['target_period', 'kpi'], name='achv_period_kpi_idx'),
        ]

    def __str__(self):
        return f'{self.entity_id}/{self.kpi_id} {self.achievement_pct}% ({self.target_period_id})'


class AchievementSnapshot(BaseModel):
    """Frozen point-in-time value for an Achievement — the trend time-series. One per day."""

    achievement = models.ForeignKey(
        Achievement, on_delete=models.CASCADE, related_name='snapshots',
    )
    snapshot_date = models.DateField(db_index=True)
    achieved_value = models.DecimalField(**_MONEY)
    achievement_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    projected_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        db_table = 'achievements_snapshot'
        ordering = ['snapshot_date']
        constraints = [
            models.UniqueConstraint(
                fields=['achievement', 'snapshot_date'], name='achv_snapshot_day_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.achievement_id} @ {self.snapshot_date}: {self.achievement_pct}%'


class TerritoryAchievement(BaseModel):
    """The plan-tracking fact: actual vs target for one committed allocation dimension —
    geography node × KPI × period × channel × SKU group (mirrors ``TargetAllocation``, so
    volume is bounded by the plan's grain, never a node × SKU explosion).

    Actuals aggregate transactions over the node's own subtree; no Assignment resolution is
    involved, so territory facts are transfer-proof by construction. The person-facing
    ``Achievement`` stays the SIP/money input; both layers are written by the same compute
    pass over the same transaction aggregates, so they cannot drift.
    """

    target_period = models.ForeignKey(
        'targets.TargetPeriod', on_delete=models.CASCADE, related_name='territory_achievements',
    )
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', on_delete=models.PROTECT, related_name='territory_achievements',
    )
    node = models.ForeignKey(
        'hierarchy.GeographyNode', on_delete=models.CASCADE, related_name='territory_achievements',
    )
    channel = models.ForeignKey(
        'hierarchy.Channel', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='territory_achievements',
    )
    sku_group = models.ForeignKey(
        'master_data.SKUGroup', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='territory_achievements',
    )

    target_value = models.DecimalField(**_MONEY)
    achieved_value = models.DecimalField(**_MONEY)
    achievement_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    gap_to_target = models.DecimalField(**_MONEY)

    computed_at = models.DateTimeField(null=True, blank=True)
    computation_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'achievements_territory'
        ordering = ['target_period', 'kpi', 'node']
        constraints = [
            # nulls_distinct=False: the all-channel/all-SKU row (NULL dims) must be unique
            # too, and the bulk upsert's ON CONFLICT needs a plain index to infer.
            models.UniqueConstraint(
                fields=['target_period', 'kpi', 'node', 'channel', 'sku_group'],
                name='territory_achv_dim_uniq',
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=['target_period', 'kpi'], name='territory_achv_period_kpi_idx'),
            models.Index(fields=['node', 'target_period'], name='territory_achv_node_period_idx'),
        ]

    def __str__(self):
        return f'{self.node_id}/{self.kpi_id} {self.achievement_pct}% ({self.target_period_id})'


class AlertRule(BaseModel, VersionedMixin):
    """Configurable threshold over an achievement metric. Generic by design — no FMCG term
    is hardcoded; the client builds rules like 'projected_pct < 90 for territories'."""

    ACHIEVEMENT_PCT = 'achievement_pct'
    PROJECTED_PCT = 'projected_pct'
    GAP_TO_TARGET = 'gap_to_target'
    REQUIRED_RUN_RATE = 'required_run_rate'
    NO_SALE_DAYS = 'no_sale_days'
    GROWTH_PCT = 'growth_pct'
    METRIC_CHOICES = [
        (ACHIEVEMENT_PCT, 'Achievement %'),
        (PROJECTED_PCT, 'Projected month-end %'),
        (GAP_TO_TARGET, 'Gap to target'),
        (REQUIRED_RUN_RATE, 'Required run rate'),
        (NO_SALE_DAYS, 'Days since last sale'),
        (GROWTH_PCT, 'Growth vs last year'),
    ]

    COMPARATORS = [('lt', '<'), ('lte', '≤'), ('gt', '>'), ('gte', '≥'), ('eq', '=')]

    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'
    SEVERITY_CHOICES = [(INFO, 'Info'), (WARNING, 'Warning'), (CRITICAL, 'Critical')]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    metric = models.CharField(max_length=30, choices=METRIC_CHOICES)
    comparator = models.CharField(max_length=3, choices=COMPARATORS, default='lt')
    threshold = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    scope_entity_types = models.JSONField(default=list, blank=True)  # [type_code, ...]; empty = all
    scope_channels = models.JSONField(default=list, blank=True)      # [channel_code, ...]; empty = all
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='alert_rules',
    )
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=WARNING)
    recipient_role = models.CharField(max_length=50, blank=True, default='')  # for Sprint 11 notifications
    message_template = models.CharField(
        max_length=255, blank=True, default='{entity}: {metric} is {value}',
    )
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'achievements_alertrule'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='achv_alertrule_code_ver_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} (v{self.version})'


class Alert(BaseModel):
    """A generated alert instance: a rule breached for an entity in a period."""

    OPEN = 'open'
    ACKNOWLEDGED = 'acknowledged'
    RESOLVED = 'resolved'
    STATUS_CHOICES = [(OPEN, 'Open'), (ACKNOWLEDGED, 'Acknowledged'), (RESOLVED, 'Resolved')]

    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='alerts')
    entity = models.ForeignKey('hierarchy.Node', on_delete=models.CASCADE, related_name='alerts')
    target_period = models.ForeignKey('targets.TargetPeriod', on_delete=models.CASCADE, related_name='alerts')
    kpi = models.ForeignKey(
        'kpi_engine.KPIDefinition', null=True, blank=True, on_delete=models.SET_NULL, related_name='alerts',
    )
    metric_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    severity = models.CharField(max_length=10, choices=AlertRule.SEVERITY_CHOICES, default=AlertRule.WARNING)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    message = models.CharField(max_length=255, blank=True, default='')
    computed_at = models.DateTimeField(null=True, blank=True)
    computation_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'achievements_alert'
        ordering = ['-computed_at', '-id']
        constraints = [
            # One live alert per (rule, entity, period, kpi). Re-evaluation updates in place.
            models.UniqueConstraint(
                fields=['rule', 'entity', 'target_period', 'kpi'],
                name='achv_alert_dim_uniq',
                condition=models.Q(kpi__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['rule', 'entity', 'target_period'],
                name='achv_alert_dim_nokpi_uniq',
                condition=models.Q(kpi__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=['entity', 'target_period', 'status'], name='achv_alert_scope_idx'),
        ]

    def __str__(self):
        return f'[{self.severity}] {self.rule.code} {self.entity_id} ({self.status})'
