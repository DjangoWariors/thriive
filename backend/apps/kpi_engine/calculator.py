"""KPICalculator — turns a KPIDefinition + a date window into Decimal results.

Pure computation over the Transaction table (engine layer): it reads, never writes.
The one organising principle: **always re-aggregate raw transactions over the geography
the entity owns**, then let ``kpi_type`` decide the math. Sales attach to geography nodes
(``Transaction.attributed_node_id``), and an organisation entity's responsibility is the
set of geography territories it owns on the period date (via ``assignments.Assignment``),
each expanded to its subtree. Because we never sum child *results*, ratio/growth
"recompute at each level" for free — a manager's lines-per-bill is total lines ÷ total
bills across the whole owned territory, not the average of the children's ratios.

For a leaf territory the owned subtree is just itself, so leaf and manager share one path.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count, DecimalField, Max, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode
from apps.master_data.models import SKUGroup

from . import periods
from .expressions import safe_eval
from .models import ExternalMetric, ExternalMetricValue, KPIDefinition, Transaction

_SALE_Q = Q(transaction_type=Transaction.SALE)
_RETURN_Q = Q(transaction_type__in=[Transaction.RETURN, Transaction.CREDIT_NOTE])
_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=24, decimal_places=6))

# Largest attributed_node_id IN-list we ship to Postgres; beyond this a bulk
# aggregate runs unrestricted and the ownership fold drops unowned nodes.
_IN_LIST_MAX = 10_000

_BOOLEAN_OPS = {
    'gte': lambda a, b: a >= b,
    'gt': lambda a, b: a > b,
    'lte': lambda a, b: a <= b,
    'lt': lambda a, b: a < b,
    'eq': lambda a, b: a == b,
}


class KPICalculator:
    def __init__(self, kpi: KPIDefinition, period_start, period_end):
        self.kpi = kpi
        self.period_start = period_start
        self.period_end = period_end
        self._sku_code_cache: dict = {}  # sku_filter repr → resolved codes (lazy)

    # ── public API ──────────────────────────────────────────────────────────
    def compute_for_entity(self, entity_id: int) -> Decimal:
        # Subquery form: a national owner's subtree (150k nodes) never becomes a
        # SQL IN-list literal — membership compiles to `IN (SELECT id ...)`.
        node_qs = AssignmentService.scope_node_qs_for_entity(entity_id, on=self.period_end)
        return self.round_value(self._compute_raw([] if node_qs is None else node_qs, entity_id))

    def compute_bulk(self, entity_ids: list[int]) -> dict[int, Decimal]:
        """Compute for many entities. For the common same-level case (siblings with
        disjoint subtrees, e.g. all ASEs in a daily achievement run) the simple
        aggregations run as a single grouped query and fold by subtree."""
        mc = self.kpi.measure_config or {}
        simple = self.kpi.kpi_type in (KPIDefinition.VALUE, KPIDefinition.COUNT, KPIDefinition.COUNT_DISTINCT)
        # A per-group "having" filter (e.g. EC = outlets with net > 0) and weighted
        # distribution can't be folded from per-leaf counts, so fall back to the
        # per-entity path for those.
        if simple and not mc.get('having') and mc.get('aggregation') != 'weighted_distinct':
            return self._bulk_simple(entity_ids)
        # Non-foldable KPIs still aggregate per entity, but ownership resolves once
        # for the whole set — the per-entity fan-out was the 150k bottleneck, not the math.
        owned_map = AssignmentService.scope_node_ids_map(entity_ids, on=self.period_end)
        return {
            eid: self.round_value(self._compute_raw(owned_map.get(eid, []), eid))
            for eid in entity_ids
        }

    def compute_bulk_for_nodes(self, node_ids: list[int]) -> dict[int, Decimal]:
        """This KPI for each geography node over that node's own subtree, keyed by node id.

        The geography-axis analogue of ``compute_bulk``: geography-axis disaggregation uses it
        to get each child node's historical base. **Precondition:** ``node_ids`` must be
        disjoint (no node an ancestor of another), else an ancestor and descendant double-count.
        The disaggregation caller only ever passes one parent's direct children, which is disjoint.
        """
        node_ids = list(node_ids)
        if not node_ids:
            return {}
        subtree_map = {nid: self._subtree_node_ids(nid) for nid in node_ids}

        mc = self.kpi.measure_config or {}
        simple = self.kpi.kpi_type in (KPIDefinition.VALUE, KPIDefinition.COUNT, KPIDefinition.COUNT_DISTINCT)
        if not (simple and not mc.get('having') and mc.get('aggregation') != 'weighted_distinct'):
            # having / weighted / non-simple KPIs can't fold from per-leaf counts.
            # entity_id=None: on the geography axis there is no org entity (matters for
            # person-grain external metrics, which must not misread a node id).
            return {nid: self.round_value(self._compute_raw(subtree_map[nid], None)) for nid in node_ids}

        node_to_target: dict[int, int] = {}
        all_nodes: set[int] = set()
        for target, leaf_ids in subtree_map.items():
            for leaf in leaf_ids:
                node_to_target[leaf] = target
                all_nodes.add(leaf)
        per_node = self._grouped_aggregate(
            self.kpi.measure_config, list(all_nodes), (self.period_start, self.period_end),
        )
        result = {nid: Decimal('0') for nid in node_ids}
        for leaf_id, value in per_node.items():
            target = node_to_target.get(leaf_id)
            if target is not None:
                result[target] += value
        return {nid: self.round_value(value) for nid, value in result.items()}

    def values_by_node(self) -> dict[int, Decimal] | None:
        """Raw per-attributed-node values over the whole window, for KPIs whose subtree
        value is the sum of its member nodes' values (the same fold condition as
        ``compute_bulk``). Returns None when folding is invalid — ratio/growth/boolean/
        composite/external, per-group having, weighted distribution — and the caller must
        aggregate per subtree instead (``compute_for_subtrees``)."""
        mc = self.kpi.measure_config or {}
        simple = self.kpi.kpi_type in (KPIDefinition.VALUE, KPIDefinition.COUNT, KPIDefinition.COUNT_DISTINCT)
        if not (simple and not mc.get('having') and mc.get('aggregation') != 'weighted_distinct'):
            return None
        return self._grouped_aggregate(mc, None, (self.period_start, self.period_end))

    def compute_for_subtrees(self, subtree_map: dict[int, list[int]]) -> dict[int, Decimal]:
        """This KPI per key, aggregated over precomputed member-node sets. Keys may overlap
        (a region and its towns) — each is computed independently over its own set.
        entity_id=None: geography axis, no org entity."""
        return {
            key: self.round_value(self._compute_raw(node_ids, None))
            for key, node_ids in subtree_map.items()
        }

    @staticmethod
    def _subtree_node_ids(node_id: int) -> list[int]:
        row = GeographyNode.objects.filter(pk=node_id, is_active=True).values('path').first()
        if row is None:
            return []
        return list(
            GeographyNode.objects.filter(path__startswith=row['path'], is_active=True)
            .values_list('id', flat=True)
        )

    # ── per-type dispatch (raw, unrounded) ──────────────────────────────────
    def _compute_raw(self, entity_ids, entity_id) -> Decimal:
        kt = self.kpi.kpi_type
        window = (self.period_start, self.period_end)

        if kt in (KPIDefinition.VALUE, KPIDefinition.COUNT, KPIDefinition.COUNT_DISTINCT):
            return self._aggregate(self.kpi.measure_config, entity_ids, window)

        if kt == KPIDefinition.RATIO:
            cfg = self.kpi.ratio_config or {}
            num = self._aggregate(cfg.get('numerator', {}), entity_ids, window)
            den = self._aggregate(cfg.get('denominator', {}), entity_ids, window)
            return num / den if den else Decimal('0')

        if kt == KPIDefinition.GROWTH:
            cfg = self.kpi.growth_config or {}
            base_window = periods.resolve_comparison_window(
                self.period_start, self.period_end,
                cfg.get('basis', periods.LAST_YEAR_SAME_PERIOD),
                cfg.get('offset'),
            )
            current = self._aggregate(self.kpi.measure_config, entity_ids, window)
            base = self._aggregate(self.kpi.measure_config, entity_ids, base_window)
            output = cfg.get('output', 'growth_pct')
            if output == 'growth_absolute':
                return current - base
            if output == 'index':
                return current / base * 100 if base else Decimal('0')
            return (current - base) / base * 100 if base else Decimal('0')  # growth_pct

        if kt == KPIDefinition.BOOLEAN:
            cfg = self.kpi.boolean_config or {}
            base = self._aggregate(self.kpi.measure_config, entity_ids, window)
            op = _BOOLEAN_OPS.get(cfg.get('operator', 'gte'))
            threshold = Decimal(str(cfg.get('threshold', 0)))
            return Decimal('1') if op and op(base, threshold) else Decimal('0')

        if kt == KPIDefinition.EXTERNAL:
            return self._external_value(entity_ids, entity_id)

        if kt == KPIDefinition.COMPOSITE:
            cfg = self.kpi.composite_config or {}
            variables = {}
            for component in cfg.get('components', []):
                code = component.get('kpi_code')
                comp_kpi = KPIDefinition.objects.filter(
                    code=code, is_current=True, is_active=True,
                ).first()
                if comp_kpi is None:
                    variables[code] = Decimal('0')
                    continue
                sub = KPICalculator(comp_kpi, self.period_start, self.period_end)
                variables[code] = sub._compute_raw(entity_ids, entity_id)
            return safe_eval(cfg.get('expression', '0'), variables)

        return Decimal('0')

    def _external_value(self, node_ids, entity_id) -> Decimal:
        """External-metric KPI: aggregate ExternalMetricValue facts over the window.
        Territory-grain metrics (TLSD, blue lines) sum over the owned geography subtree
        exactly like transactions; person-grain metrics (RCPA %, iQuest) read the exact
        entity's rows only — no org rollup (a manager's average score is not a business
        number), so on the geography axis (entity_id None) they are always 0."""
        cfg = self.kpi.external_config or {}
        metric = ExternalMetric.objects.filter(code=cfg.get('metric_code'), is_active=True).first()
        if metric is None:
            return Decimal('0')

        qs = ExternalMetricValue.objects.filter(
            metric=metric, is_active=True,
            measured_on__gte=self.period_start, measured_on__lte=self.period_end,
        )
        if metric.granularity == ExternalMetric.ENTITY:
            if entity_id is None:
                return Decimal('0')
            qs = qs.filter(entity_id=entity_id)
        else:
            qs = qs.filter(node_id__in=node_ids)

        agg = cfg.get('aggregation') or metric.default_aggregation
        if agg == ExternalMetric.LATEST:
            latest = qs.order_by('-measured_on', '-id').values_list('value', flat=True).first()
            return latest if latest is not None else Decimal('0')
        if agg == ExternalMetric.AVG:
            return qs.aggregate(v=Coalesce(Avg('value'), _ZERO))['v']
        if agg == ExternalMetric.MAX:
            return qs.aggregate(v=Coalesce(Max('value'), _ZERO))['v']
        return qs.aggregate(v=Coalesce(Sum('value'), _ZERO))['v']

    # ── aggregation ─────────────────────────────────────────────────────────
    def _aggregate(self, measure_config: dict, entity_ids, window) -> Decimal:
        """Single scalar aggregate of one measure spec over a set of entities + window."""
        if not measure_config:
            return Decimal('0')
        field = measure_config.get('measure_field') or 'net_amount'
        agg = measure_config.get('aggregation') or 'sum'
        net = measure_config.get('net_logic') or 'all'
        qs = self._scoped_qs(measure_config, entity_ids, window)

        if agg == 'sum':
            if net == 'sales_minus_returns':
                row = qs.aggregate(
                    s=Coalesce(Sum(field, filter=_SALE_Q), _ZERO),
                    r=Coalesce(Sum(field, filter=_RETURN_Q), _ZERO),
                )
                return row['s'] - row['r']
            if net == 'gross_only':
                return qs.aggregate(s=Coalesce(Sum(field, filter=_SALE_Q), _ZERO))['s']
            if net == 'returns_only':
                return qs.aggregate(s=Coalesce(Sum(field, filter=_RETURN_Q), _ZERO))['s']
            return qs.aggregate(s=Coalesce(Sum(field), _ZERO))['s']

        if agg == 'weighted_distinct':
            return self._weighted_distinct(measure_config, entity_ids, window)

        # Per-group threshold (e.g. Effective Coverage = count of outlets where the
        # NET of a field, sales − returns, clears a threshold). Needs both sale and
        # return rows, so it runs before the net row-filter.
        if agg == 'count_distinct' and measure_config.get('having'):
            return self._count_distinct_having(qs, field, measure_config['having'])

        qs = self._apply_net_row_filter(qs, net)
        if agg == 'count_distinct':
            return Decimal(qs.exclude(**{field: ''}).values(field).distinct().count())
        return Decimal(qs.count())  # count

    def _grouped_aggregate(self, measure_config: dict, node_ids, window) -> dict[int, Decimal]:
        """Same as _aggregate but grouped by attributed_node_id → {node_id: value}."""
        field = measure_config.get('measure_field') or 'net_amount'
        agg = measure_config.get('aggregation') or 'sum'
        net = measure_config.get('net_logic') or 'all'
        qs = self._scoped_qs(measure_config, node_ids, window)

        if agg == 'sum':
            if net == 'sales_minus_returns':
                rows = qs.values('attributed_node_id').annotate(
                    s=Coalesce(Sum(field, filter=_SALE_Q), _ZERO),
                    r=Coalesce(Sum(field, filter=_RETURN_Q), _ZERO),
                )
                return {r['attributed_node_id']: r['s'] - r['r'] for r in rows}
            row_filter = _SALE_Q if net == 'gross_only' else (_RETURN_Q if net == 'returns_only' else None)
            agg_expr = Sum(field, filter=row_filter) if row_filter is not None else Sum(field)
            rows = qs.values('attributed_node_id').annotate(v=Coalesce(agg_expr, _ZERO))
            return {r['attributed_node_id']: r['v'] for r in rows}

        qs = self._apply_net_row_filter(qs, net)
        if agg == 'count_distinct':
            rows = qs.exclude(**{field: ''}).values('attributed_node_id').annotate(v=Count(field, distinct=True))
        else:
            rows = qs.values('attributed_node_id').annotate(v=Count('id'))
        return {r['attributed_node_id']: Decimal(r['v']) for r in rows}

    def _count_distinct_having(self, qs, field, having: dict) -> Decimal:
        """Group by ``field``, compute net (sales − returns) of having['field'] per
        group, and count groups that satisfy the operator/value condition."""
        hfield = having.get('field') or 'net_amount'
        op = _BOOLEAN_OPS.get(having.get('operator', 'gt'), _BOOLEAN_OPS['gt'])
        threshold = Decimal(str(having.get('value', 0)))
        rows = (
            qs.exclude(**{field: ''})
            .values(field)
            .annotate(
                s=Coalesce(Sum(hfield, filter=_SALE_Q), _ZERO),
                r=Coalesce(Sum(hfield, filter=_RETURN_Q), _ZERO),
            )
        )
        return Decimal(sum(1 for row in rows if op(row['s'] - row['r'], threshold)))

    def _bulk_simple(self, entity_ids: list[int]) -> dict[int, Decimal]:
        # Map each owned geography node back to the organisation entity that owns it.
        # Same-level targets (e.g. all ASEs in a run) own disjoint territory subtrees.
        # Batched resolver: constant query count for the whole entity set, instead of
        # 2-3 ownership queries per entity (300k+ at a 150k-retailer level).
        owned_map = AssignmentService.scope_node_ids_map(entity_ids, on=self.period_end)
        node_to_target: dict[int, int] = {}
        all_nodes: set[int] = set()
        for target, node_ids in owned_map.items():
            for node_id in node_ids:
                node_to_target[node_id] = target
                all_nodes.add(node_id)

        # Past this size an IN-list literal costs more than aggregating the whole
        # filtered window — the node_to_target fold drops unowned nodes either way.
        scope_nodes = list(all_nodes) if len(all_nodes) <= _IN_LIST_MAX else None
        per_node = self._grouped_aggregate(
            self.kpi.measure_config, scope_nodes, (self.period_start, self.period_end),
        )
        result = {eid: Decimal('0') for eid in entity_ids}
        for node_id, value in per_node.items():
            target = node_to_target.get(node_id)
            if target is not None:
                result[target] += value
        return {eid: self.round_value(value) for eid, value in result.items()}

    # ── queryset scoping ────────────────────────────────────────────────────
    def _scoped_qs(self, measure_config: dict, node_ids, window, ignore_sku_filter=False):
        """node_ids=None means no territory restriction (whole-table grouped aggregates)."""
        start, end = window
        qs = Transaction.objects.filter(
            is_active=True,
            transaction_date__gte=start,
            transaction_date__lte=end,
        )
        if node_ids is not None:
            qs = qs.filter(attributed_node_id__in=node_ids)
        if self.kpi.channel_filter:
            qs = qs.filter(channel_code__in=self.kpi.channel_filter)
        if not ignore_sku_filter:
            sku_codes = self._measure_sku_codes(measure_config)
            if sku_codes is not None:
                qs = qs.filter(sku_code__in=sku_codes)
        level = measure_config.get('transaction_level')
        if level:
            qs = qs.filter(transaction_level=level)
        sources = measure_config.get('source_filter')
        if sources:
            qs = qs.filter(source__in=sources)
        return qs

    @staticmethod
    def _apply_net_row_filter(qs, net: str):
        if net == 'gross_only' or net == 'sales_minus_returns':
            return qs.filter(_SALE_Q)
        if net == 'returns_only':
            return qs.filter(_RETURN_Q)
        return qs

    def _measure_sku_codes(self, measure_config: dict):
        """SKU codes to filter on, or None. A measure may carry its own ``sku_filter`` (used by
        Weighted Distribution, where numerator and denominator need different SKU scopes);
        otherwise the KPI-level filter applies."""
        sku_filter = measure_config.get('sku_filter') or self.kpi.sku_filter or {}
        key = repr(sku_filter)
        if key not in self._sku_code_cache:
            self._sku_code_cache[key] = self._codes_from_filter(sku_filter)
        return self._sku_code_cache[key]

    @staticmethod
    def _codes_from_filter(sku_filter: dict):
        ftype = (sku_filter or {}).get('type', 'all')
        if ftype == 'explicit':
            codes = list(sku_filter.get('sku_codes', []))
        elif ftype == 'group':
            group = SKUGroup.objects.filter(code=sku_filter.get('group_code'), is_active=True).first()
            codes = list(group.get_skus().values_list('code', flat=True)) if group else []
        else:
            codes = []  # 'all' → no restriction
        return codes or None

    def _weighted_distinct(self, mc: dict, entity_ids, window) -> Decimal:
        """Weighted Distribution: sum a per-group weight over the qualifying groups.

        Group by ``group_field`` (e.g. outlet); the qualifying set is the groups present in the
        (SKU-)filtered transactions; each group's weight = SUM(``weight_field``). With
        ``weight_scope='all'`` the weight ignores the SKU filter, i.e. the outlet's *total*
        throughput — so WD = Σ throughput of outlets that stocked the brand ÷ Σ throughput of all.
        """
        group_field = mc.get('group_field') or 'outlet_code'
        weight_field = mc.get('weight_field') or 'net_amount'
        scope = mc.get('weight_scope', 'filtered')
        net = mc.get('net_logic') or 'all'

        qualifying_qs = self._apply_net_row_filter(self._scoped_qs(mc, entity_ids, window), net)
        qualifying = set(qualifying_qs.exclude(**{group_field: ''}).values_list(group_field, flat=True).distinct())
        if not qualifying:
            return Decimal('0')

        weight_qs = self._scoped_qs(mc, entity_ids, window, ignore_sku_filter=(scope == 'all'))
        weight_qs = self._apply_net_row_filter(weight_qs, net).filter(**{f'{group_field}__in': qualifying})
        rows = weight_qs.values(group_field).annotate(w=Coalesce(Sum(weight_field), _ZERO))
        return sum((r['w'] for r in rows), Decimal('0'))

    # ── helpers ───────────────────────────────────────────────────────────
    def round_value(self, value) -> Decimal:
        quant = Decimal(10) ** -self.kpi.decimal_places
        return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
