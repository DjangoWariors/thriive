"""Achievement business logic. The only layer that writes achievement/alert rows.

``AchievementService.compute_period`` runs one full computation for a period as a series of
per-KPI units (``start_run`` -> ``compute_kpi_unit`` x N -> ``finalize_run``) under one
ComputationLog. Each unit writes both layers — the territory fact (``TerritoryAchievement``,
per committed allocation dimension) and the person fact (``Achievement`` + snapshot) — with
chunked bulk upserts, each chunk committing on its own: no period-wide transaction, and a
re-run converges (idempotent), which is what matters for a nightly job. The KPI is also the
fan-out unit for the distributed path (``tasks.compute_daily_achievements``).

``DashboardService.build`` assembles the role-adaptive dashboard payload; managers (entities
with children) get subtree aggregates + ranked children, leaf entities get their own KPIs.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.assignments.services import AssignmentService
from apps.audit.models import ComputationLog
from apps.core.exceptions import BusinessError
from apps.core.scoping import requester_can_reach_entity, scope_transactions_by_territory
from apps.hierarchy.models import Node, NodeType
from apps.kpi_engine.models import ExternalMetric, ExternalMetricValue, KPIDefinition, Transaction
from apps.targets.models import TargetAllocation, TargetPeriod

from .alerts import evaluate as evaluate_alerts
from .calculator import AchievementCalculator
from .models import Achievement, AchievementSnapshot, Alert, TerritoryAchievement

_VIEW_PERM = 'achievement_view'
_SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}
_CHUNK = 1000

# is_provisional is deliberately NOT here: a recompute must preserve the frozen flag a
# cycle finalize set (see incentives.PayoutCycleService.finalize). New rows insert True;
# on conflict the existing (possibly frozen) value is kept.
_ACHIEVEMENT_UPDATE_FIELDS = [
    'target_value', 'achieved_value', 'gross_value', 'returns_value', 'achievement_pct',
    'gap_to_target', 'daily_run_rate', 'projected_value', 'projected_pct',
    'required_run_rate', 'working_days_elapsed', 'working_days_total', 'ly_value',
    'growth_pct', 'computed_at', 'computation_id', 'updated_at',
]
_TERRITORY_UPDATE_FIELDS = [
    'target_value', 'achieved_value', 'achievement_pct', 'gap_to_target',
    'computed_at', 'computation_id', 'updated_at',
]


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class AchievementService:
    @staticmethod
    def compute_period(target_period_id: int, triggered_by=None, as_of: date | None = None) -> dict:
        """Run every KPI unit in-process and finalize. Production fans the same units out
        as parallel Celery tasks (see ``tasks.compute_daily_achievements``)."""
        ctx = AchievementService.start_run(target_period_id, triggered_by=triggered_by, as_of=as_of)
        for kpi_id in ctx['kpi_ids']:
            AchievementService.compute_kpi_unit(
                ctx['period_id'], kpi_id, ctx['computation_id'], ctx['as_of'], ctx['type_codes'],
            )
        return AchievementService.finalize_run(ctx['period_id'], ctx['computation_id'], ctx['as_of'])

    # ── run lifecycle ────────────────────────────────────────────────────────
    @staticmethod
    def start_run(target_period_id: int, triggered_by=None, as_of: date | None = None) -> dict:
        """Open the ComputationLog and resolve the run plan: which entity types are in
        scope and which KPIs form the units (applicable to those types, or carrying
        committed allocations this period)."""
        period = TargetPeriod.objects.get(pk=target_period_id)
        as_of = as_of or date.today()
        type_codes = sorted(AchievementService._eligible_type_codes(period))
        kpi_ids = AchievementService._unit_kpi_ids(period, set(type_codes))
        log = ComputationLog.objects.create(
            computation_type='achievement',
            entity_id=0,
            period_id=period.id,
            triggered_by_id=getattr(triggered_by, 'pk', None),
            config_snapshot={'period_code': period.code, 'as_of': as_of.isoformat()},
            result_snapshot={'units': [], 'unit_total': len(kpi_ids), 'entity_types': type_codes},
        )
        return {'period_id': period.id, 'computation_id': log.id, 'as_of': as_of,
                'kpi_ids': kpi_ids, 'type_codes': type_codes}

    @staticmethod
    def compute_kpi_unit(period_id: int, kpi_id: int, computation_id: int,
                         as_of: date, type_codes: list[str]) -> dict:
        """One fan-out unit: territory pass + person pass for a single KPI. Failures are
        recorded on the run, never raised — one bad KPI must not abort the others."""
        period = TargetPeriod.objects.get(pk=period_id)
        kpi = KPIDefinition.objects.get(pk=kpi_id)
        summary = {'kpi_code': kpi.code, 'persons': 0, 'territories': 0, 'error': None}
        now = timezone.now()
        try:
            calc = AchievementCalculator(period, as_of=as_of)
            summary['territories'] = AchievementService._territory_pass(
                period, kpi, calc, computation_id, now,
            )
            summary['persons'] = AchievementService._person_pass(
                period, kpi, calc, computation_id, type_codes, now, as_of,
            )
        except Exception as exc:  # noqa: BLE001 — recorded per unit, run continues
            summary['error'] = f'{kpi.code}: {exc}'
        summary['is_last'] = AchievementService._record_unit(computation_id, summary)
        return summary

    @staticmethod
    def finalize_run(period_id: int, computation_id: int, as_of: date) -> dict:
        """After the last unit: evaluate alerts over the fresh rows, close the log,
        notify. Called exactly once per run (last unit on the distributed path)."""
        period = TargetPeriod.objects.get(pk=period_id)
        log = ComputationLog.objects.get(pk=computation_id)
        units = log.result_snapshot.get('units', [])
        errors = [u['error'] for u in units if u.get('error')]
        processed = sum(u.get('persons', 0) for u in units)
        territories = sum(u.get('territories', 0) for u in units)

        alert_count = AchievementService._sync_alerts(period, computation_id, as_of, timezone.now())

        log.result_snapshot = {
            **log.result_snapshot,
            'records_processed': processed, 'territory_records': territories,
            'alerts': alert_count, 'errors': errors,
        }
        log.save(update_fields=['result_snapshot'])

        computed_entity_ids = set(
            Achievement.objects.filter(
                target_period=period, computation_id=computation_id,
            ).values_list('entity_id', flat=True)
        )
        from .notifications import notify_achievements_computed
        notify_achievements_computed(period, computed_entity_ids, computation_id=computation_id)

        return {'computation_id': computation_id, 'records_processed': processed,
                'territory_records': territories, 'alerts': alert_count, 'errors': errors}

    @staticmethod
    def _unit_kpi_ids(period, type_codes: set[str]) -> list[int]:
        """The run's KPI units: current KPIs applicable to the eligible types, plus KPIs
        (any version) carrying committed allocations this period — a plan may have
        committed against a version the type-driven pass would not pick up."""
        applicable = {
            k.id for k in KPIDefinition.objects.filter(is_current=True, is_active=True)
            if not k.applicable_entity_types or set(k.applicable_entity_types) & type_codes
        }
        with_allocations = set(
            TargetAllocation.objects.live().filter(
                target_period=period, kpi__is_active=True,
            ).values_list('kpi_id', flat=True).distinct()
        )
        return sorted(applicable | with_allocations)

    @staticmethod
    def _record_unit(computation_id: int, summary: dict) -> bool:
        """Append a unit's outcome to the run log under a row lock (units run in parallel
        on the distributed path). Returns True for the unit that completes the run."""
        with transaction.atomic():
            log = ComputationLog.objects.select_for_update().get(pk=computation_id)
            units = log.result_snapshot.setdefault('units', [])
            units.append({k: summary[k] for k in ('kpi_code', 'persons', 'territories', 'error')})
            log.save(update_fields=['result_snapshot'])
            return len(units) >= log.result_snapshot.get('unit_total', 0)

    # ── the two write passes ─────────────────────────────────────────────────
    @staticmethod
    def _territory_pass(period, kpi, calc, computation_id, now) -> int:
        """Upsert the plan-tracking facts for this KPI, then drop rows whose allocation
        dimension is no longer committed — the fact table mirrors the plan exactly."""
        rows = calc.compute_territory_for_kpi(kpi)
        objs = [
            TerritoryAchievement(
                target_period=period, kpi=kpi, node_id=r['node_id'],
                channel_id=r['channel_id'], sku_group_id=r['sku_group_id'],
                target_value=r['target_value'], achieved_value=r['achieved_value'],
                achievement_pct=r['achievement_pct'], gap_to_target=r['gap_to_target'],
                computed_at=now, computation_id=computation_id,
            )
            for r in rows
        ]
        for chunk in _chunks(objs):
            TerritoryAchievement.objects.bulk_create(
                chunk, update_conflicts=True,
                unique_fields=['target_period', 'kpi', 'node', 'channel', 'sku_group'],
                update_fields=_TERRITORY_UPDATE_FIELDS,
            )
        TerritoryAchievement.objects.filter(target_period=period, kpi=kpi).exclude(
            computation_id=computation_id,
        ).delete()
        return len(objs)

    @staticmethod
    def _person_pass(period, kpi, calc, computation_id, type_codes, now, as_of) -> int:
        types = [t for t in type_codes
                 if not kpi.applicable_entity_types or t in kpi.applicable_entity_types]
        # One compute per type code: entities of one level own disjoint territory
        # subtrees, which the calculator's bulk fold requires — mixing levels would
        # credit an owned town to its region's owner only.
        rows = []
        for code in types:
            entities = list(
                Node.objects.filter(
                    entity_type__code=code, is_current=True, is_active=True,
                ).select_related('entity_type')
            )
            if not entities:
                continue
            rows += [r for r in calc.compute_for_kpi(kpi, entities)
                     if r['target_value'] or r['achieved_value']]  # skip zero-zero noise
        if not rows:
            return 0

        # New rows are provisional; the cycle finalize freezes them to non-provisional and
        # a later recompute keeps that (is_provisional isn't in the upsert's update_fields).
        objs = [
            Achievement(
                target_period=period, kpi=kpi,
                entity_id=r['entity_id'], channel_id=r['channel_id'],
                target_value=r['target_value'], achieved_value=r['achieved_value'],
                gross_value=r['gross_value'], returns_value=r['returns_value'],
                achievement_pct=r['achievement_pct'], gap_to_target=r['gap_to_target'],
                daily_run_rate=r['daily_run_rate'], projected_value=r['projected_value'],
                projected_pct=r['projected_pct'], required_run_rate=r['required_run_rate'],
                working_days_elapsed=r['working_days_elapsed'],
                working_days_total=r['working_days_total'],
                ly_value=r['ly_value'], growth_pct=r['growth_pct'],
                is_provisional=True, computed_at=now, computation_id=computation_id,
            )
            for r in rows
        ]
        for chunk in _chunks(objs):
            # update_conflicts + unique_fields -> RETURNING sets pks on updated rows too,
            # which the snapshot pass below relies on.
            Achievement.objects.bulk_create(
                chunk, update_conflicts=True,
                unique_fields=['target_period', 'kpi', 'entity', 'channel'],
                update_fields=_ACHIEVEMENT_UPDATE_FIELDS,
            )

        snaps = [
            AchievementSnapshot(
                achievement_id=a.pk, snapshot_date=as_of,
                achieved_value=r['achieved_value'], achievement_pct=r['achievement_pct'],
                projected_pct=r['projected_pct'],
            )
            for a, r in zip(objs, rows)
        ]
        for chunk in _chunks(snaps):
            AchievementSnapshot.objects.bulk_create(
                chunk, update_conflicts=True,
                unique_fields=['achievement', 'snapshot_date'],
                update_fields=['achieved_value', 'achievement_pct', 'projected_pct', 'updated_at'],
            )
        return len(rows)

    @staticmethod
    def _eligible_type_codes(period) -> set[str]:
        incentive = set(
            NodeType.objects.filter(
                is_current=True, is_active=True, incentive_eligible=True,
            ).values_list('code', flat=True)
        )
        # Types whose entities own a territory carrying a target this period. Targets are
        # geography-anchored, so resolve owners through the Assignment bridge as-of period end.
        node_ids = (
            TargetAllocation.objects.live().filter(target_period=period)
            .exclude(geography_node__isnull=True)
            .values_list('geography_node_id', flat=True)
        )
        owner_ids = AssignmentService.owner_entity_ids_for_scopes(node_ids, on=period.end_date)
        with_targets = set(
            Node.objects.filter(pk__in=owner_ids, is_current=True, is_active=True)
            .values_list('entity_type__code', flat=True)
        )
        return {c for c in (incentive | with_targets) if c}

    @staticmethod
    def _sync_alerts(period, computation_id, as_of, now) -> int:
        qs = Achievement.objects.filter(target_period=period)
        breaches = evaluate_alerts(period, qs, as_of=as_of)
        live_keys = set()
        for b in breaches:
            alert, _ = Alert.objects.update_or_create(
                rule=b['rule'], entity_id=b['entity_id'], target_period=period, kpi_id=b['kpi_id'],
                defaults={
                    'metric_value': b['metric_value'], 'severity': b['severity'],
                    'message': b['message'], 'status': Alert.OPEN,
                    'computed_at': now, 'computation_id': computation_id,
                },
            )
            live_keys.add(alert.id)
        # Resolve previously-open alerts that no longer breach.
        Alert.objects.filter(target_period=period, status=Alert.OPEN).exclude(
            id__in=live_keys,
        ).update(status=Alert.RESOLVED)
        return len(live_keys)

    # ── drilldown ────────────────────────────────────────────────────────────
    @staticmethod
    def drilldown(achievement_id: int, user, *, outlet: str = '', sku: str = ''):
        ach = (
            Achievement.objects
            .select_related('kpi', 'entity', 'target_period', 'channel')
            .get(pk=achievement_id)
        )
        if not requester_can_reach_entity(user, _VIEW_PERM, ach.entity):
            raise BusinessError('You do not have access to this achievement.', code='forbidden')

        # External KPIs have no transactions behind them — drill into the metric
        # fact rows instead (person-grain: the entity's own rows; territory-grain:
        # the owned subtree, like transactions). Outlet/SKU filters don't apply.
        if ach.kpi.kpi_type == KPIDefinition.EXTERNAL:
            return ach, AchievementService._external_drill_rows(ach), 'metric_values'

        # Sales attach to geography: drill into the territories this entity owns.
        from apps.assignments.services import AssignmentService
        node_ids = AssignmentService.scope_node_ids_for_entity(
            ach.entity.id, on=ach.target_period.end_date,
        )
        txns = Transaction.objects.filter(
            is_active=True, attributed_node_id__in=node_ids,
            transaction_date__gte=ach.target_period.start_date,
            transaction_date__lte=ach.target_period.end_date,
        )
        if ach.kpi.channel_filter:
            txns = txns.filter(channel_code__in=ach.kpi.channel_filter)
        if outlet := (outlet or '').strip():
            txns = txns.filter(outlet_code__icontains=outlet)
        if sku := (sku or '').strip():
            txns = txns.filter(sku_code__icontains=sku)
        txns = scope_transactions_by_territory(txns, user, _VIEW_PERM).order_by('-transaction_date', '-id')
        return ach, txns, 'transactions'

    # ── territory grid (plan tracking) ───────────────────────────────────────
    @staticmethod
    def territory_grid(kpi, period, *, parent_id=None, channel_code=None, channel_id=None,
                       sku_group_id=None, children_qs=None, page: int = 1, page_size: int = 100) -> dict:
        """One geography level of the plan-tracking grid: ``parent``'s child nodes with
        target/actual/%/gap from ``TerritoryAchievement`` (the run-rate-needed column is
        derived from the period's remaining working days). Lazy and paginated exactly like
        the planning grid; ``children_qs`` carries the territory-RBAC scope."""
        from datetime import date as _date

        from apps.hierarchy.models import GeographyNode
        from apps.kpi_engine import periods as _periods

        if children_qs is None:
            children_qs = GeographyNode.objects.filter(is_active=True)
        if parent_id:
            children_qs = children_qs.filter(parent_id=parent_id)
        else:
            children_qs = children_qs.filter(parent__isnull=True)
        children_qs = children_qs.filter(is_active=True).order_by('name', 'id')

        page = max(1, page)
        page_size = min(max(1, page_size), 500)
        total = children_qs.count()
        offset = (page - 1) * page_size
        children = list(children_qs[offset:offset + page_size].values('id', 'name', 'code', 'level'))
        child_ids = [c['id'] for c in children]

        # Match the committed allocation dimension: a specific channel (by id or code), or the
        # all-channel (NULL) row when neither is given.
        if channel_id is not None:
            channel_filter = {'channel_id': channel_id}
        elif channel_code:
            channel_filter = {'channel__code': channel_code}
        else:
            channel_filter = {'channel__isnull': True}
        facts = {
            f.node_id: f for f in TerritoryAchievement.objects.filter(
                target_period=period, kpi=kpi, node_id__in=child_ids,
                sku_group_id=sku_group_id, **channel_filter,
            )
        } if child_ids else {}
        # The target column reads the live committed axis, not the fact snapshot: a fresh
        # publish has targets before any compute, and an override must show immediately.
        live_targets = {
            a.geography_node_id: a.effective_target
            for a in TargetAllocation.objects.live().filter(
                target_period=period, kpi=kpi, geography_node_id__in=child_ids,
                sku_group_id=sku_group_id, **channel_filter,
            )
        } if child_ids else {}
        child_counts = {
            r['parent_id']: r['n'] for r in GeographyNode.objects.filter(
                parent_id__in=child_ids, is_active=True,
            ).values('parent_id').annotate(n=Count('id'))
        } if child_ids else {}

        # Remaining working days → run-rate needed (flat, working-day aware).
        total_wd = period.working_days or _periods.working_days_between(period.start_date, period.end_date)
        today = _date.today()
        if today < period.start_date:
            elapsed = 0
        elif today > period.end_date:
            elapsed = total_wd
        else:
            elapsed = min(total_wd, _periods.working_days_between(period.start_date, today))
        remaining = max(0, total_wd - elapsed)

        rows = []
        for c in children:
            f = facts.get(c['id'])
            target = live_targets.get(c['id'], f.target_value if f else None)
            actual = f.achieved_value if f else None
            if target is not None and actual is not None and target > 0:
                # Recompute against the live target so the row stays internally consistent
                # even when an override moved the target after the last compute.
                pct = _pct(actual, target)
                gap = target - actual
            else:
                pct = f.achievement_pct if f else None
                gap = f.gap_to_target if f else None
            rr = (gap / remaining) if (remaining > 0 and gap and gap > 0) else None
            rows.append({
                'node_id': c['id'], 'name': c['name'], 'code': c['code'], 'level': c['level'],
                'children_count': child_counts.get(c['id'], 0),
                'target': str(target) if target is not None else None,
                'actual': str(actual) if actual is not None else None,
                'achievement_pct': str(pct) if pct is not None else None,
                'gap': str(gap) if gap is not None else None,
                'run_rate_needed': str(rr.quantize(Decimal('0.0001'))) if rr is not None else None,
            })
        return {'parent': parent_id, 'rows': rows, 'page': page, 'page_size': page_size,
                'total': total}

    @staticmethod
    def _external_drill_rows(ach):
        cfg = ach.kpi.external_config or {}
        metric = ExternalMetric.objects.filter(code=cfg.get('metric_code')).first()
        if metric is None:
            return ExternalMetricValue.objects.none()
        qs = ExternalMetricValue.objects.filter(
            metric=metric, is_active=True,
            measured_on__gte=ach.target_period.start_date,
            measured_on__lte=ach.target_period.end_date,
        ).select_related('metric')
        if metric.granularity == ExternalMetric.ENTITY:
            return qs.filter(entity_id=ach.entity_id).order_by('-measured_on', '-id')
        from apps.assignments.services import AssignmentService
        node_ids = AssignmentService.scope_node_ids_for_entity(
            ach.entity_id, on=ach.target_period.end_date,
        )
        return qs.filter(node_id__in=node_ids).order_by('-measured_on', '-id')


class DashboardService:
    @staticmethod
    def build(user, target_period, entity=None) -> dict:
        home = DashboardService._resolve_home(user, entity)
        if home is None:
            return DashboardService._empty(target_period)

        own = list(
            Achievement.objects
            .filter(target_period=target_period, entity=home)
            .select_related('kpi', 'channel')
            .order_by('-target_value')
        )
        children = list(home.get_direct_children().select_related('entity_type', 'channel'))

        # Incentive overlay (cross-app via services): estimated payout, per-KPI
        # multiplier/weight, per-child payouts. Gracefully empty before any run.
        from apps.incentives.services import PayoutService
        payout_info = PayoutService.dashboard_info(
            target_period, home, [c.id for c in children], user=user,
        )

        kpi_cards = [DashboardService._kpi_card(a, payout_info['kpi_lines']) for a in own]
        child_ranking = (
            DashboardService._rank_children(target_period, children,
                                            payout_info['child_payouts'])
            if children else None
        )

        return {
            'entity': {'id': home.id, 'name': home.name, 'code': home.code,
                       'type': home.entity_type.code if home.entity_type else None},
            'summary': DashboardService._summary(
                user, home, target_period, own,
                estimated_payout=payout_info['estimated_payout'],
                payout_kind=payout_info.get('payout_kind'),
            ),
            'kpi_cards': kpi_cards,
            'child_ranking': child_ranking,
            'trend': DashboardService._trend(own),
            'channel_mix': DashboardService._channel_mix(target_period, home),
            'alerts': DashboardService._alerts(home, target_period),
            'modules': {'incentives': payout_info['available'], 'exceptions': True},
        }

    # ── resolution ───────────────────────────────────────────────────────────
    @staticmethod
    def _resolve_home(user, entity):
        if entity is not None:
            if not requester_can_reach_entity(user, _VIEW_PERM, entity):
                raise BusinessError('You do not have access to this entity.', code='forbidden')
            return entity
        if getattr(user, 'entity', None):
            return user.entity
        # Unscoped admin / superuser → default to a root entity (national view).
        return Node.objects.filter(
            is_current=True, is_active=True, depth=0,
        ).order_by('id').first()

    # ── sections ─────────────────────────────────────────────────────────────
    @staticmethod
    def _kpi_card(a, kpi_lines=None) -> dict:
        line = (kpi_lines or {}).get(a.kpi.code) or {}
        return {
            'id': a.id, 'kpi_code': a.kpi.code, 'kpi_name': a.kpi.name, 'unit': a.kpi.unit,
            'weight_pct': line.get('weight_pct'),
            'target': str(a.target_value), 'achieved': str(a.achieved_value),
            'pct': str(a.achievement_pct), 'projected_pct': str(a.projected_pct),
            'required_run_rate': str(a.required_run_rate), 'gap': str(a.gap_to_target),
            'growth_pct': str(a.growth_pct) if a.growth_pct is not None else None,
            'multiplier': line.get('multiplier'),
            'is_provisional': a.is_provisional,
        }

    @staticmethod
    def _summary(user, home, period, own, estimated_payout=None, payout_kind=None) -> dict:
        # Only targeted rows score: a row with achieved value but no target (e.g. an
        # untargeted tracking KPI) would inflate the numerator against nothing.
        scored = [a for a in own if a.target_value]
        tgt = sum((a.target_value for a in scored), Decimal('0'))
        ach = sum((a.achieved_value for a in scored), Decimal('0'))
        proj = sum((a.projected_value for a in scored), Decimal('0'))
        primary = own[0] if own else None  # highest-target KPI is the primary proxy
        primary_target = str(primary.target_value) if primary else '0'
        primary_achieved = str(primary.achieved_value) if primary else '0'
        primary_name = primary.kpi.name if primary else None
        if not own:
            # No own facts (unplaced admin at a national root, or a pure manager seat):
            # the tiles reflect the direct children instead — disjoint rollups, so their
            # sum is the network total.
            per_kpi = list(
                Achievement.objects.filter(
                    target_period=period, entity__parent=home, target_value__gt=0,
                )
                .values('kpi__name')
                .annotate(t=Sum('target_value'), a=Sum('achieved_value'), p=Sum('projected_value'))
                .order_by('-t')
            )
            tgt = sum((r['t'] for r in per_kpi), Decimal('0'))
            ach = sum((r['a'] for r in per_kpi), Decimal('0'))
            proj = sum((r['p'] for r in per_kpi), Decimal('0'))
            if per_kpi:
                primary_target = str(per_kpi[0]['t'])
                primary_achieved = str(per_kpi[0]['a'])
                primary_name = per_kpi[0]['kpi__name']
        subtree = Node.objects.filter(
            path__startswith=home.path, is_current=True, is_active=True,
        ).exclude(pk=home.pk).count()
        open_alerts = Alert.objects.filter(
            target_period=period, status=Alert.OPEN, entity__path__startswith=home.path,
        ).count()
        return {
            'overall_achievement_pct': str(_pct(ach, tgt)),
            'projected_pct': str(_pct(proj, tgt)),
            'primary_target': primary_target,
            'primary_achieved': primary_achieved,
            'primary_kpi_name': primary_name,
            'estimated_payout': estimated_payout,
            'payout_kind': payout_kind,
            'active_entities': subtree,
            'open_alerts': open_alerts,
        }

    @staticmethod
    def _rank_children(period, children, child_payouts=None) -> list[dict]:
        child_payouts = child_payouts or {}
        child_ids = [c.id for c in children]
        # target_value > 0: untargeted rows must not score (achieved against no target).
        agg = {
            row['entity_id']: row for row in
            Achievement.objects.filter(
                target_period=period, entity_id__in=child_ids, target_value__gt=0,
            )
            .values('entity_id')
            .annotate(t=Sum('target_value'), a=Sum('achieved_value'), p=Sum('projected_value'))
        }
        rows = []
        for c in children:
            row = agg.get(c.id, {})
            t, a, p = row.get('t') or Decimal('0'), row.get('a') or Decimal('0'), row.get('p') or Decimal('0')
            rows.append({
                'entity_id': c.id, 'entity_name': c.name, 'entity_code': c.code,
                'entity_type': c.entity_type.code if c.entity_type else None,
                'channel': c.channel.code if c.channel_id else None,
                'achievement_pct': _pct(a, t), 'projected_pct': _pct(p, t),
                'payout': child_payouts.get(c.id),
            })
        rows.sort(key=lambda r: r['achievement_pct'], reverse=True)
        for i, r in enumerate(rows, start=1):
            r['rank'] = i
            r['achievement_pct'] = str(r['achievement_pct'])
            r['projected_pct'] = str(r['projected_pct'])
        return rows

    @staticmethod
    def _trend(own) -> list[dict]:
        if not own:
            return []
        primary = own[0]
        snaps = primary.snapshots.order_by('snapshot_date')
        return [
            {'label': s.snapshot_date.isoformat(),
             'target': str(primary.target_value),
             'achieved': str(s.achieved_value),
             'pct': str(s.achievement_pct)}
            for s in snaps
        ]

    @staticmethod
    def _channel_mix(period, home) -> list[dict]:
        # A manager's achievement already rolls up its subtree, so counting every
        # channel-bearing row would double-count each level. Leaf rows only.
        parents = Node.objects.filter(
            is_current=True, is_active=True,
            path__startswith=home.path, parent__isnull=False,
        ).values('parent_id')
        rows = (
            Achievement.objects.filter(
                target_period=period, entity__path__startswith=home.path, channel__isnull=False,
            )
            .exclude(entity_id__in=parents)
            .values('channel__code')
            .annotate(a=Sum('achieved_value'))
        )
        total = sum((r['a'] or Decimal('0') for r in rows), Decimal('0'))
        if not total:
            return []
        return [
            {'channel': r['channel__code'], 'pct': str(_pct(r['a'] or Decimal('0'), total))}
            for r in rows
        ]

    @staticmethod
    def _alerts(home, period) -> list[dict]:
        alerts = (
            Alert.objects.filter(
                target_period=period, status=Alert.OPEN, entity__path__startswith=home.path,
            )
            .select_related('rule', 'entity', 'kpi')
        )
        items = [{
            'id': al.id, 'entity_name': al.entity.name, 'rule_code': al.rule.code,
            'severity': al.severity, 'metric': al.rule.metric,
            'metric_value': str(al.metric_value), 'message': al.message,
            'kpi_code': al.kpi.code if al.kpi_id else None,
        } for al in alerts]
        items.sort(key=lambda i: _SEVERITY_ORDER.get(i['severity'], 9))
        return items[:20]

    @staticmethod
    def _empty(period) -> dict:
        return {
            'entity': None,
            'summary': {'overall_achievement_pct': '0.00', 'projected_pct': '0.00',
                        'primary_target': '0', 'primary_achieved': '0', 'primary_kpi_name': None,
                        'estimated_payout': None, 'payout_kind': None,
                        'active_entities': 0, 'open_alerts': 0},
            'kpi_cards': [], 'child_ranking': None, 'trend': [], 'channel_mix': [],
            'alerts': [], 'modules': {'incentives': False, 'exceptions': True},
        }


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if not denominator:
        return Decimal('0.00')
    # ROUND_HALF_UP to match the calculator's percentages exactly.
    return (numerator / denominator * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
