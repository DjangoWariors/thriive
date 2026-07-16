"""AchievementCalculator — joins computed actuals (KPICalculator) against targets
(TargetAllocation) and derives FMCG run-rate / projection / growth. Engine layer: reads only,
returns plain dicts. The service persists them.

Two passes share one instance: ``compute_for_kpi`` (person fact — actuals over owned
geography via the Assignment bridge) and ``compute_territory_for_kpi`` (territory fact —
one row per committed allocation dimension, aggregated over the node's own subtree).

Run-rate is working-day aware and reuses the helpers in ``kpi_engine.periods`` rather than
re-implementing the math. Month-end loading (phasing curves) is a documented later hook —
Sprint 6 uses a flat working-day run-rate.
"""
import bisect
import copy
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apps.hierarchy.models import Channel, GeographyNode
from apps.kpi_engine import periods
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import KPIDefinition
from apps.master_data.models import SKUGroup
from apps.targets.models import TargetAllocation
from apps.targets.services import TargetService

_Q2 = Decimal('0.01')
_Q4 = Decimal('0.0001')


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if not denominator:
        return Decimal('0.00')
    return (numerator / denominator * 100).quantize(_Q2, rounding=ROUND_HALF_UP)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(_Q4, rounding=ROUND_HALF_UP)


class AchievementCalculator:
    def __init__(self, target_period, as_of: date | None = None):
        self.period = target_period
        self.start = target_period.start_date
        self.end = target_period.end_date
        self.as_of = as_of or date.today()

    # ── KPI applicability ────────────────────────────────────────────────────
    def applicable_kpis(self, type_code: str):
        """Current KPIs that apply to this entity type (or to all — empty list means any)."""
        kpis = KPIDefinition.objects.filter(is_current=True, is_active=True)
        return [
            k for k in kpis
            if not k.applicable_entity_types or type_code in k.applicable_entity_types
        ]

    # ── per-KPI computation over a set of entities ───────────────────────────
    def compute_for_kpi(self, kpi: KPIDefinition, entities) -> list[dict]:
        """Return one result dict per entity for this KPI."""
        ids = [e.id for e in entities]
        if not ids:
            return []

        achieved = KPICalculator(kpi, self.start, self.end).compute_bulk(ids)
        gross, returns = self._gross_returns(kpi, ids, achieved)
        targets = self._targets(kpi, ids)
        ly = self._last_year(kpi, ids)

        total_wd = self.period.working_days or periods.working_days_between(self.start, self.end)
        elapsed_wd = self._elapsed_working_days(total_wd)
        remaining_wd = max(0, total_wd - elapsed_wd)

        results = []
        for entity in entities:
            eid = entity.id
            ach = _money(achieved.get(eid, 0))
            tgt = _money(targets.get(eid, 0))
            gap = _money(tgt - ach)

            daily_rr = _money(ach / elapsed_wd) if elapsed_wd > 0 else Decimal('0')
            projected = _money(periods.project_full_period(ach, elapsed_wd, total_wd))
            required_rr = _money(gap / remaining_wd) if (remaining_wd > 0 and gap > 0) else Decimal('0')

            ly_val = ly.get(eid)
            growth = _pct(ach - ly_val, ly_val) if ly_val else None

            results.append({
                'entity_id': eid,
                'channel_id': entity.channel_id,
                'target_value': tgt,
                'achieved_value': ach,
                'gross_value': _money(gross.get(eid, ach)),
                'returns_value': _money(returns.get(eid, 0)),
                'achievement_pct': _pct(ach, tgt),
                'gap_to_target': gap,
                'daily_run_rate': daily_rr,
                'projected_value': projected,
                'projected_pct': _pct(projected, tgt),
                'required_run_rate': required_rr,
                'working_days_elapsed': elapsed_wd,
                'working_days_total': total_wd,
                'ly_value': _money(ly_val) if ly_val is not None else None,
                'growth_pct': growth,
            })
        return results

    # ── territory pass ───────────────────────────────────────────────────────
    def compute_territory_for_kpi(self, kpi: KPIDefinition) -> list[dict]:
        """One result dict per committed TargetAllocation dimension for this KPI — the
        plan-tracking territory fact. Actuals aggregate the node's own subtree (no
        Assignment resolution), so the rows are transfer-proof by construction and volume
        is bounded by the plan's committed grain."""
        allocs = list(
            TargetAllocation.objects.live().filter(
                target_period=self.period, kpi=kpi,
            ).values('geography_node_id', 'channel_id', 'sku_group_id', 'target_value', 'override_value')
        )
        if not allocs:
            return []

        node_paths = dict(
            GeographyNode.objects.filter(
                id__in={a['geography_node_id'] for a in allocs},
            ).values_list('id', 'path')
        )
        channel_codes = dict(
            Channel.objects.filter(
                id__in={a['channel_id'] for a in allocs if a['channel_id']},
            ).values_list('id', 'code')
        )
        group_codes = dict(
            SKUGroup.objects.filter(
                id__in={a['sku_group_id'] for a in allocs if a['sku_group_id']},
            ).values_list('id', 'code')
        )

        by_dim: dict[tuple, list[dict]] = {}
        for a in allocs:
            by_dim.setdefault((a['channel_id'], a['sku_group_id']), []).append(a)

        results = []
        for (channel_id, sku_group_id), dim_allocs in by_dim.items():
            scoped = self._dim_scoped(kpi, channel_codes.get(channel_id), group_codes.get(sku_group_id))
            kcalc = KPICalculator(scoped, self.start, self.end)
            target_paths = {
                a['geography_node_id']: node_paths[a['geography_node_id']]
                for a in dim_allocs if a['geography_node_id'] in node_paths
            }
            actuals = self._territory_actuals(kcalc, target_paths)
            for a in dim_allocs:
                tgt = _money(a['override_value'] if a['override_value'] is not None else a['target_value'])
                ach = _money(actuals.get(a['geography_node_id'], 0))
                results.append({
                    'node_id': a['geography_node_id'],
                    'channel_id': channel_id,
                    'sku_group_id': sku_group_id,
                    'target_value': tgt,
                    'achieved_value': ach,
                    'achievement_pct': _pct(ach, tgt),
                    'gap_to_target': _money(tgt - ach),
                })
        return results

    @staticmethod
    def _dim_scoped(kpi, channel_code, group_code):
        """Shallow clone carrying the allocation dimension's channel / SKU-group scope
        (no DB write). The committed dimension is the tracking grain, so it overrides
        the KPI-level filter."""
        if not channel_code and not group_code:
            return kpi
        clone = copy.copy(kpi)
        if channel_code:
            clone.channel_filter = [channel_code]
        if group_code:
            clone.sku_filter = {'type': 'group', 'group_code': group_code}
        return clone

    def _territory_actuals(self, kcalc: KPICalculator, target_paths: dict[int, str]) -> dict[int, Decimal]:
        per_node = kcalc.values_by_node()
        if per_node is not None:
            return self._fold_to_targets(kcalc, per_node, target_paths)
        return kcalc.compute_for_subtrees(self._subtree_ids(target_paths))

    @staticmethod
    def _fold_to_targets(kcalc, per_node: dict[int, Decimal], target_paths: dict[int, str]) -> dict[int, Decimal]:
        """Fold per-trading-node values up to every target whose subtree contains them.
        Allocations exist at several levels at once (a region and its towns), so a trading
        node credits each ancestor target — every level's actual is its own subtree sum."""
        if not per_node:
            return {}
        targets_by_path: dict[str, list[int]] = {}
        for nid, path in target_paths.items():
            targets_by_path.setdefault(path, []).append(nid)
        trading = GeographyNode.objects.filter(
            id__in=per_node.keys(), is_active=True,
        ).values_list('id', 'path')
        totals: dict[int, Decimal] = {}
        for tid, tpath in trading:
            for prefix in _ancestor_paths(tpath):
                for nid in targets_by_path.get(prefix, ()):
                    totals[nid] = totals.get(nid, Decimal('0')) + per_node[tid]
        return {nid: kcalc.round_value(v) for nid, v in totals.items()}

    @staticmethod
    def _subtree_ids(target_paths: dict[int, str]) -> dict[int, list[int]]:
        """Member node ids per target (self + active descendants), resolved with one
        indexed prefix query per minimal covering prefix — never one query per node."""
        if not target_paths:
            return {}
        covering = _minimal_prefixes(sorted(set(target_paths.values())))
        rows: list[tuple[int, str]] = []
        for prefix in covering:
            rows += GeographyNode.objects.filter(
                is_active=True, path__startswith=prefix,
            ).values_list('id', 'path')
        rows.sort(key=lambda r: r[1])
        paths = [r[1] for r in rows]
        out = {}
        for nid, tpath in target_paths.items():
            i = bisect.bisect_left(paths, tpath)
            members = []
            while i < len(paths) and paths[i].startswith(tpath):
                members.append(rows[i][0])
                i += 1
            out[nid] = members
        return out

    # ── helpers ──────────────────────────────────────────────────────────────
    def _elapsed_working_days(self, total_wd: int) -> int:
        if self.as_of < self.start:
            return 0
        upto = min(self.as_of, self.end)
        return min(total_wd, periods.working_days_between(self.start, upto))

    def _gross_returns(self, kpi, ids, achieved):
        """Gross (sales) and returns split — meaningful for VALUE KPIs on a money measure.
        For other KPI types the split is not defined, so gross = achieved and returns = 0."""
        if kpi.kpi_type != KPIDefinition.VALUE:
            return {}, {}
        gross = KPICalculator(self._with_net(kpi, 'gross_only'), self.start, self.end).compute_bulk(ids)
        returns = KPICalculator(self._with_net(kpi, 'returns_only'), self.start, self.end).compute_bulk(ids)
        return gross, returns

    @staticmethod
    def _with_net(kpi, net_logic):
        """Shallow clone of a KPI with the measure's net_logic overridden (no DB write)."""
        clone = copy.copy(kpi)
        clone.measure_config = {**(kpi.measure_config or {}), 'net_logic': net_logic}
        return clone

    def _targets(self, kpi, ids) -> dict:
        # Score-type external KPIs (RCPA %, iQuest…) carry a fixed benchmark so
        # achievement_pct reads as the raw score — no geography allocation exists for them.
        if kpi.kpi_type == KPIDefinition.EXTERNAL:
            cfg = kpi.external_config or {}
            if cfg.get('target_source') == 'fixed':
                fixed = _money(cfg.get('fixed_target', 0))
                return {eid: fixed for eid in ids}
        # Targets live on geography; a person's target is the rollup of the territories they
        # own as-of the period end — resolved through the Assignment bridge in TargetService.
        return TargetService.derive_entity_targets(self.period, kpi, ids, on=self.end)

    def _last_year(self, kpi, ids) -> dict:
        try:
            base_start, base_end = periods.resolve_comparison_window(
                self.start, self.end, periods.LAST_YEAR_SAME_PERIOD,
            )
        except ValueError:
            return {}
        return KPICalculator(kpi, base_start, base_end).compute_bulk(ids)


def _ancestor_paths(path: str) -> list[str]:
    """Every self-or-ancestor materialized path of '/A/B/C/' → ['/A/', '/A/B/', '/A/B/C/']."""
    if not path:
        return []
    parts = path.strip('/').split('/')
    return ['/' + '/'.join(parts[:i + 1]) + '/' for i in range(len(parts))]


def _minimal_prefixes(sorted_paths: list[str]) -> list[str]:
    """Drop paths already covered by an earlier (shorter) prefix in the sorted list."""
    kept: list[str] = []
    for p in sorted_paths:
        if not kept or not p.startswith(kept[-1]):
            kept.append(p)
    return kept
