from django.db import models

from apps.core.models import BaseModel, VersionedMixin


class KPIDefinition(BaseModel, VersionedMixin):
    """
    Represents a configurable KPI whose definition is versioned.

    Instead of updating an existing KPI, every change creates a new version.
    This preserves older definitions so historical reports and calculations
    continue to use the KPI logic that was valid when they were generated.

    The KPI's calculation is determined by kpi_type and its corresponding
    JSON configuration. The model itself is generic and contains no client- or
    industry-specific logic. Different KPI definitions—such as primary sales,
    ECO, lines per bill, secondary sales growth, or MSL compliance—are created
    simply by changing the configuration.
    """


    VALUE = 'value'  # SUM of a money/quantity field
    COUNT = 'count' # COUNT of matching rows
    COUNT_DISTINCT = 'count_distinct'  # COUNT(DISTINCT field) — ECO, bills cut
    RATIO = 'ratio'   # numerator agg ÷ denominator agg (drop size, lines/bill)
    GROWTH = 'growth'  # current window vs a comparison window (% / abs / index)
    COMPOSITE = 'composite' # expression over other KPI codes
    BOOLEAN = 'boolean'  # base measure vs threshold → 1.00 / 0.00
    EXTERNAL = 'external' # aggregate of an ExternalMetric feed (SFA/agency)
    KPI_TYPE_CHOICES = [
        (VALUE, 'Value (sum)'),
        (COUNT, 'Count'),
        (COUNT_DISTINCT, 'Count distinct'),
        (RATIO, 'Ratio'),
        (GROWTH, 'Growth'),
        (COMPOSITE, 'Composite'),
        (BOOLEAN, 'Boolean / threshold'),
        (EXTERNAL, 'External metric'),
    ]


    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, blank=True, default='', db_index=True)
    unit = models.CharField(max_length=30, blank=True, default='')
    decimal_places = models.PositiveSmallIntegerField(default=2)
    kpi_type = models.CharField(max_length=20, choices=KPI_TYPE_CHOICES, default=VALUE)
    measure_config = models.JSONField(default=dict, blank=True)
    ratio_config = models.JSONField(default=dict, blank=True)
    growth_config = models.JSONField(default=dict, blank=True)
    composite_config = models.JSONField(default=dict, blank=True)
    boolean_config = models.JSONField(default=dict, blank=True)
    external_config = models.JSONField(default=dict, blank=True)
    # Scope filters (shared across all types). Empty list = no restriction.
    applicable_entity_types = models.JSONField(default=list, blank=True)
    channel_filter = models.JSONField(default=list, blank=True)
    # sku_filter: {type: all|group|explicit, group_code, sku_codes: [...]}
    sku_filter = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'kpi_engine_kpidefinition'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'version'],
                name='kpi_definition_code_ver_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['is_current', 'kpi_type'], name='kpi_def_cur_type_idx'),
            models.Index(fields=['category', 'is_current'], name='kpi_def_cat_cur_idx'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name} (v{self.version})'


class KpiTemplate(BaseModel):
    """
    Reusable template for creating KPIs with pre-filled settings.
    Templates speed up KPI creation by providing default values in the builder.
    They are client-configurable, not versioned, and serve only as starting
    points.
    """
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(max_length=50, blank=True, default='')
    display_order = models.PositiveSmallIntegerField(default=0)
    category = models.CharField(max_length=50, blank=True, default='')
    unit = models.CharField(max_length=30, blank=True, default='')
    decimal_places = models.PositiveSmallIntegerField(default=2)
    kpi_type = models.CharField(
        max_length=20, choices=KPIDefinition.KPI_TYPE_CHOICES, default=KPIDefinition.VALUE,
    )
    measure_config = models.JSONField(default=dict, blank=True)
    ratio_config = models.JSONField(default=dict, blank=True)
    growth_config = models.JSONField(default=dict, blank=True)
    composite_config = models.JSONField(default=dict, blank=True)
    boolean_config = models.JSONField(default=dict, blank=True)
    external_config = models.JSONField(default=dict, blank=True)
    sku_filter = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'kpi_engine_kpitemplate'
        ordering = ['display_order', 'name']

    def __str__(self):
        return f'{self.code} — {self.name}'


class Transaction(BaseModel):
    """A raw sales or return transaction from any source. Optimized for high-volume,
    append-only ingestion.

    attributed_node_id stores the geography node ID as a plain BigIntegerField
    instead of a Django FK for faster imports. It represents the territory or outlet
    where the transaction occurred. Ownership is resolved later through
    assignments.Assignment, so territory changes automatically affect KPI
    calculations without updating historical transactions.

    The record also stores gross, net, discount, and tax amounts, allowing clients
    to calculate metrics such as GSV or NSV from the same imported data.
    """

    SALE = 'sale'
    RETURN = 'return'
    CREDIT_NOTE = 'credit_note'
    TRANSACTION_TYPE_CHOICES = [
        (SALE, 'Sale'),
        (RETURN, 'Return'),
        (CREDIT_NOTE, 'Credit note'),
    ]

    PRIMARY = 'primary' # company → distributor (sell-in)
    SECONDARY = 'secondary' # distributor → retailer (the main incentive driver)
    TERTIARY = 'tertiary' # retailer → consumer
    LEVEL_CHOICES = [
        (PRIMARY, 'Primary'),
        (SECONDARY, 'Secondary'),
        (TERTIARY, 'Tertiary'),
    ]

    # Attribution — geography node (where the sale happened), never a person
    attributed_node_id = models.BigIntegerField(db_index=True)
    outlet_code = models.CharField(max_length=50, blank=True, default='')
    bill_ref = models.CharField(max_length=80, blank=True, default='')
    sku_code = models.CharField(max_length=50, blank=True, default='', db_index=True)
    channel_code = models.CharField(max_length=20, blank=True, default='', db_index=True)
    transaction_date = models.DateField(db_index=True)
    posted_date = models.DateField(null=True, blank=True)
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_TYPE_CHOICES, default=SALE,
    )
    transaction_level = models.CharField(
        max_length=20, choices=LEVEL_CHOICES, default=SECONDARY, db_index=True,
    )
    source = models.CharField(max_length=30, blank=True, default='')
    # Idempotency key from the source system. Same (source, external_ref) upserts in place.
    external_ref = models.CharField(max_length=120, blank=True, default='', db_index=True)
    gross_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Volume — Decimal because cases/kg/litre need fractions
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    uom = models.CharField(max_length=20, blank=True, default='')
    base_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = 'kpi_engine_transaction'
        ordering = ['-transaction_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_ref'],
                condition=~models.Q(external_ref=''),
                name='kpi_txn_source_ref_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['attributed_node_id', 'transaction_date'], name='kpi_txn_node_date_idx'),
            models.Index(fields=['channel_code', 'transaction_date'], name='kpi_txn_chan_date_idx'),
            models.Index(fields=['transaction_date', 'transaction_level'], name='kpi_txn_date_lvl_idx'),
        ]

    def __str__(self):
        return f'{self.transaction_type} {self.net_amount} @ {self.transaction_date} (node {self.attributed_node_id})'


class ExternalMetric(BaseModel):
    """
    Represents a catalog of external, non-transaction data sources such as
    SFA productive calls, agency activation scores, and TLSD metrics.

    This model only defines the metadata for a metric (its unit and data grain).
    The actual calculation logic is defined by the versioned KPI that references
    this catalog entry, so a simple BaseModel is sufficient. This follows the
    same approach used for the KPI template and measure catalogs.

    The granularity field determines what each recorded value belongs to:

    - entity
      Used for individual or entity-level metrics, such as RCPA % or iQuest scores.
      Values are stored against the specific entity and are not rolled up through
      the organizational hierarchy. For example, a manager's iQuest score is not
      derived by averaging the scores of their team.

    - geography_node
      Used for territory-based metrics, such as TLSD or Blue Line coverage.
      Values are attached to a geographic node and can be aggregated across the
      territory hierarchy in the same way as transactional data.
    """

    ENTITY = 'entity'
    GEOGRAPHY_NODE = 'geography_node'
    GRANULARITY_CHOICES = [
        (ENTITY, 'Person (organisation entity)'),
        (GEOGRAPHY_NODE, 'Territory (geography node)'),
    ]

    DAILY = 'daily'
    MONTHLY = 'monthly'
    GRAIN_CHOICES = [(DAILY, 'Daily'), (MONTHLY, 'Monthly')]

    SUM = 'sum'
    AVG = 'avg'
    LATEST = 'latest'
    MAX = 'max'
    AGGREGATION_CHOICES = [(SUM, 'Sum'), (AVG, 'Average'), (LATEST, 'Latest'), (MAX, 'Max')]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    unit = models.CharField(max_length=30, blank=True, default='')
    decimal_places = models.PositiveSmallIntegerField(default=2)
    granularity = models.CharField(max_length=20, choices=GRANULARITY_CHOICES, default=GEOGRAPHY_NODE)
    period_grain = models.CharField(max_length=10, choices=GRAIN_CHOICES, default=MONTHLY)
    default_aggregation = models.CharField(max_length=10, choices=AGGREGATION_CHOICES, default=SUM)

    class Meta:
        db_table = 'kpi_engine_externalmetric'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} — {self.name}'


class ExternalMetricValue(BaseModel):
    """One fact row of an external metric: metric × (entity XOR geography node) ×
    date × value. Monthly-grain rows normalise ``measured_on`` to the month start at
    ingestion. Idempotent on (source, external_ref) when the source supplies a ref,
    else on the natural key — re-pushing updates in place.
    """

    metric = models.ForeignKey(ExternalMetric, on_delete=models.PROTECT, related_name='values')
    # Exactly one of the two, matching metric.granularity (enforced at ingestion).
    entity = models.ForeignKey(
        'hierarchy.Node', null=True, blank=True, on_delete=models.PROTECT,
        related_name='external_metric_values',
    )

    node_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    measured_on = models.DateField(db_index=True)
    value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    source = models.CharField(max_length=30, blank=True, default='')
    external_ref = models.CharField(max_length=120, blank=True, default='', db_index=True)

    class Meta:
        db_table = 'kpi_engine_externalmetricvalue'
        ordering = ['-measured_on', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_ref'],
                condition=~models.Q(external_ref=''),
                name='kpi_emv_source_ref_uniq',
            ),
            models.UniqueConstraint(
                fields=['metric', 'entity', 'measured_on'],
                condition=models.Q(entity__isnull=False),
                name='kpi_emv_metric_entity_day_uniq',
            ),
            models.UniqueConstraint(
                fields=['metric', 'node_id', 'measured_on'],
                condition=models.Q(node_id__isnull=False),
                name='kpi_emv_metric_node_day_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['metric', 'measured_on'], name='kpi_emv_metric_date_idx'),
        ]

    def __str__(self):
        who = f'entity {self.entity_id}' if self.entity_id else f'node {self.node_id}'
        return f'{self.metric_id}: {self.value} @ {self.measured_on} ({who})'


class IntegrationBatch(BaseModel):
    """
    Tracks every inbound data push, whether it contains transactions or metric values.
    Each record represents a single import request and acts as a reconciliation log.
    If a push is rejected, the original payload is stored so the source system can
    correct the data and submit it again.
    Imports are idempotent, meaning the same data can be safely re-submitted without
    creating duplicates. If a request with the same `client_batch_ref` is received
    again, the system returns the original processing result instead of importing
    the data a second time.
    """

    TRANSACTIONS = 'transactions'
    METRIC_VALUES = 'metric_values'
    KIND_CHOICES = [(TRANSACTIONS, 'Transactions'), (METRIC_VALUES, 'Metric values')]

    ACCEPTED = 'accepted'
    PARTIAL = 'partial'
    REJECTED = 'rejected'
    STATUS_CHOICES = [(ACCEPTED, 'Accepted'), (PARTIAL, 'Partial'), (REJECTED, 'Rejected')]

    batch_kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    source = models.CharField(max_length=30)
    client_batch_ref = models.CharField(max_length=120, blank=True, default='', db_index=True)

    received_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    row_errors = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    pushed_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='integration_batches',
    )

    class Meta:
        db_table = 'kpi_engine_integrationbatch'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['batch_kind', 'source', 'client_batch_ref'],
                condition=~models.Q(client_batch_ref=''),
                name='kpi_batch_kind_src_ref_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.batch_kind} from {self.source}: {self.accepted_count}/{self.received_count} accepted'
