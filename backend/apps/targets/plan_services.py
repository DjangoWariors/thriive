"""PlanService — the plan aggregate: lifecycle, stage runs, staging → commit.

A ``TargetPlan`` owns its configuration (``PlanKpi``), its simulation runs (``PlanRun`` →
``RunAllocation`` staging) and its committed numbers (``TargetAllocation``). Every stage
computes into staging and only an explicit, atomic commit touches the committed axis that
achievements/incentives read — so a re-run can never clobber live targets, and manual
overrides are kept or dropped deliberately, never silently.

Data flow per stage: this service fetches the inputs (history via the KPI engine, geography
attributes, external metrics), the pure engines (engines.py + disaggregator.py) do the math,
and the results land in staging with a per-node explain payload (the RFP's "logics must be
explained"). Heavy runs execute through Celery (see tasks.execute_plan_run_task).
"""
import copy
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Case, Count, DecimalField, F, Q, Sum, When
from django.utils import timezone

from apps.assignments.services import AssignmentService
from apps.audit.models import ComputationLog
from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Channel, GeographyNode
from apps.kpi_engine import periods
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import ExternalMetricValue, KPIDefinition
from apps.master_data.models import SKUGroup

from . import disaggregator, engines
from .services import TargetService
from .models import (
    AllocationRecipe,
    PlanKpi,
    PlanRun,
    RunAllocation,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
)

_CHUNK = 2000

_PLAN_TRANSITIONS = {
    TargetPlan.DRAFT: {TargetPlan.IN_REVIEW, TargetPlan.PUBLISHED},
    TargetPlan.IN_REVIEW: {TargetPlan.PUBLISHED, TargetPlan.DRAFT},
    TargetPlan.PUBLISHED: {TargetPlan.LOCKED},
    TargetPlan.LOCKED: {TargetPlan.PUBLISHED, TargetPlan.CLOSED},
    TargetPlan.CLOSED: set(),
}

# Which stages may run in which plan states. Draft is the sandbox; realign is the one
# stage that must also work on a live plan (mid-period territory churn).
_RUNNABLE_IN = {
    PlanRun.BASELINE: {TargetPlan.DRAFT},
    PlanRun.SPATIAL: {TargetPlan.DRAFT},
    PlanRun.PRODUCT: {TargetPlan.DRAFT},
    PlanRun.REALIGN: {TargetPlan.DRAFT, TargetPlan.IN_REVIEW, TargetPlan.PUBLISHED},
}


def _dec(value) -> Decimal:
    return Decimal(str(value))


def _assert_period_open(period):
    """Once the payout cycle locks a month its targets are the paid base — no plan
    activity (run, commit, publish) may write into it, ever. Reads the status fresh:
    the cycle finalizes concurrently with plan work, so an in-memory copy can be stale."""
    status = TargetPeriod.objects.values_list('status', flat=True).get(pk=period.pk)
    if status in (TargetPeriod.LOCKED, TargetPeriod.CLOSED):
        raise BusinessError(
            f'{period.name} is {status} — the payout cycle has frozen its targets, '
            'so plans can no longer change this month.')


_EFFECTIVE = Case(
    When(override_value__isnull=False, then=F('override_value')),
    default=F('target_value'),
    output_field=DecimalField(max_digits=18, decimal_places=4),
)

_PCT_Q = Decimal('0.01')


def _pct_of(part, whole):
    if part is None or not whole:
        return None
    return str((part / whole * 100).quantize(_PCT_Q, rounding=ROUND_HALF_UP))


class PlanService:

    # ── plan lifecycle ───────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def create_plan(data: dict, kpis: list[dict], actor=None) -> TargetPlan:
        """``data`` = plan fields (period_id, root_geography_id, …); ``kpis`` = one dict per
        KPI: {kpi_id, recipe_id?, baseline_spec?, product_split?, top_value?}."""
        if not kpis:
            raise BusinessError('A plan needs at least one KPI.')
        if TargetPlan.objects.filter(code=data.get('code')).exists():
            raise BusinessError(f'A plan with code "{data.get("code")}" already exists.')

        period = TargetPeriod.objects.get(pk=data['period_id'])
        if period.period_type != TargetPeriod.MONTHLY:
            raise BusinessError(
                f'Targets are set monthly — "{period.code}" is a {period.period_type} period. '
                'Pick a monthly period.')
        plan = TargetPlan.objects.create(
            name=data['name'], code=data['code'],
            period=period,
            root_geography=GeographyNode.objects.get(pk=data['root_geography_id']),
            channel=Channel.objects.filter(pk=data['channel_id']).first() if data.get('channel_id') else None,
            planning_grain=data.get('planning_grain', ''),
            review_levels=data.get('review_levels', []),
            product_scope=data.get('product_scope', []),
            settings=data.get('settings', {}),
            owner=actor if getattr(actor, 'pk', None) else None,
        )
        for spec in kpis:
            PlanKpi.objects.create(
                plan=plan,
                kpi=KPIDefinition.objects.get(pk=spec['kpi_id']),
                recipe=AllocationRecipe.objects.filter(pk=spec['recipe_id']).first() if spec.get('recipe_id') else None,
                baseline_spec=spec.get('baseline_spec', {}),
                product_split=spec.get('product_split', {}),
                top_value=_dec(spec['top_value']) if spec.get('top_value') is not None else None,
            )
        AuditService.log('create', 'targets.TargetPlan', plan.id, actor,
                         {'code': plan.code, 'kpis': len(kpis)})
        return plan

    @staticmethod
    @transaction.atomic
    def transition_plan(plan: TargetPlan, new_status: str, actor=None,
                        force_over_budget: bool = False) -> TargetPlan:
        from .review_services import ReviewService

        if new_status not in _PLAN_TRANSITIONS.get(plan.status, set()):
            raise BusinessError(f'Cannot move a {plan.status} plan to {new_status}.')
        old = plan.status

        if new_status == TargetPlan.PUBLISHED:
            # Gate 0: never publish live numbers into a month the payout cycle has frozen.
            _assert_period_open(plan.period)
            # Gate 1: the cascade must be answered (or explicitly force-closed, audited).
            open_tasks = ReviewService.open_task_count(plan)
            if open_tasks:
                raise BusinessError(
                    f'{open_tasks} review task(s) are still open — wait for the field, '
                    'or force-close the review (audited).')
            # Gate 2: cost of plan vs budget (finance sanity check). Opt-in via settings.
            budget = (plan.settings or {}).get('payout_budget')
            if budget is not None:
                cost = PlanService.cost_preview(plan)
                at_100 = Decimal(cost['scenarios']['100'])
                if at_100 > _dec(budget) and not force_over_budget:
                    raise BusinessError(
                        f'Projected payout at 100% achievement ({at_100}) exceeds the plan '
                        f'budget ({budget}). Review the cost preview, or publish with an '
                        'explicit over-budget override.', code='over_budget')

        plan.status = new_status
        plan.save(update_fields=['status', 'updated_at'])
        if new_status == TargetPlan.PUBLISHED:
            # Rows committed past draft land pending; publish is the HO sign-off, so approve
            # them — except rows with an open escalated revision (maker-checker still owns those).
            plan.allocations.filter(status=TargetAllocation.PENDING).exclude(
                revisions__status=TargetRevision.PENDING,
            ).update(status=TargetAllocation.APPROVED)
            # The month's status is derived from its plans/cycle, never hand-set.
            TargetService.advance_period(plan.period, TargetPeriod.PUBLISHED, actor=actor,
                                         source=f'plan {plan.code} published')
        if old == TargetPlan.DRAFT and new_status == TargetPlan.IN_REVIEW:
            ReviewService.open_cascade(plan, actor=actor)
            if plan.review_levels and not plan.review_tasks.exists():
                raise BusinessError(
                    'No owned territories exist at the review level(s) '
                    f'{", ".join(plan.review_levels)} under {plan.root_geography.name} — '
                    'assign owners there, or clear the plan\'s review levels.')
        if old == TargetPlan.IN_REVIEW and new_status == TargetPlan.DRAFT:
            ReviewService.cancel_cascade(plan, actor=actor)
        if new_status == TargetPlan.LOCKED:
            plan.allocations.update(status=TargetAllocation.LOCKED)
        AuditService.log('update', 'targets.TargetPlan', plan.id, actor,
                         {'status': {'from': old, 'to': new_status},
                          **({'over_budget_override': True} if force_over_budget else {})})
        return plan

    # ── cost of plan (publish gate 2) ────────────────────────────────────────
    @staticmethod
    def cost_preview(plan: TargetPlan, scenarios=(95, 100, 105)) -> dict:
        """Projected payout through the real payout engine at flat achievement scenarios —
        the finance check every FMCG runs before targets go live. For each active scheme
        (channel-matching), every eligible entity's VariablePay inside the plan period is
        priced with synthetic achievements of X% on every scheme + gate KPI."""
        from apps.incentives import payout_engine as engine
        from apps.incentives.models import IncentiveScheme, VariablePay
        from apps.incentives.services import SchemeService

        schemes = IncentiveScheme.objects.filter(is_current=True, is_active=True).select_related(
            'target_entity_type', 'channel')
        if plan.channel_id:
            schemes = schemes.filter(Q(channel__isnull=True) | Q(channel_id=plan.channel_id))
        totals = {str(x): Decimal('0.00') for x in scenarios}
        per_scheme = []
        for scheme in schemes:
            scheme_input = SchemeService.build_engine_input(scheme)
            kpi_codes = {k.kpi_code for k in scheme_input.kpis} | {g.kpi_code for g in scheme_input.gates}
            vps = list(VariablePay.objects.filter(
                target_period=plan.period, is_active=True,
                entity__entity_type__code=scheme.target_entity_type.code,
            ).select_related('target_period'))
            if not vps:
                continue
            row = {'scheme': scheme.code, 'entities': len(vps), 'scenarios': {}}
            for x in scenarios:
                achievements = {code: engine.AchievementInput(Decimal(x), Decimal('0'), Decimal('0'))
                                for code in kpi_codes}
                total = Decimal('0.00')
                for vp in vps:
                    result = engine.compute_entity(scheme_input, engine.NodeInput(
                        entity_id=vp.entity_id, variable_pay=vp.amount,
                        eligible_working_days=vp.eligible_working_days,
                        period_working_days=vp.target_period.working_days or 26,
                        achievements=achievements, exception=None,
                    ))
                    total += result.total_payout
                row['scenarios'][str(x)] = str(total)
                totals[str(x)] += total
            per_scheme.append(row)

        budget = (plan.settings or {}).get('payout_budget')
        at_100 = totals.get('100', Decimal('0.00'))
        return {
            'plan': plan.code,
            'scenarios': {k: str(v) for k, v in totals.items()},
            'per_scheme': per_scheme,
            'budget': str(budget) if budget is not None else None,
            'over_budget_at_100': bool(budget is not None and at_100 > _dec(budget)),
        }

    @staticmethod
    @transaction.atomic
    def set_top_number(plan: TargetPlan, kpi, value, actor=None) -> PlanKpi:
        """Stage 2: the committed top number (typed from the AOP letter, or the accepted
        derived suggestion). The derived value stays alongside as the sanity anchor."""
        if plan.status != TargetPlan.DRAFT:
            raise BusinessError('The top number is set while the plan is in draft.')
        plan_kpi = PlanKpi.objects.filter(plan=plan, kpi=kpi).first()
        if plan_kpi is None:
            raise BusinessError('That KPI is not part of this plan.')
        value = _dec(value)
        if value < 0:
            raise BusinessError('A top number cannot be negative.')
        old = plan_kpi.top_value
        plan_kpi.top_value = value
        plan_kpi.save(update_fields=['top_value', 'updated_at'])
        AuditService.log('update', 'targets.PlanKpi', plan_kpi.id, actor,
                         {'top_value': {'from': str(old) if old is not None else None, 'to': str(value)}})
        return plan_kpi

    # ── runs: orchestration ──────────────────────────────────────────────────
    @staticmethod
    def start_run(plan: TargetPlan, kind: str, actor=None, scope_node=None) -> PlanRun:
        """Validate + create a pending run, then dispatch it (Celery or inline)."""
        if kind not in _RUNNABLE_IN:
            raise BusinessError(f'Unknown run kind "{kind}".')
        if plan.status not in _RUNNABLE_IN[kind]:
            raise BusinessError(f'A {kind} run cannot start while the plan is {plan.status}.')
        if kind != PlanRun.BASELINE:  # baseline is reference data, never committed
            _assert_period_open(plan.period)
        PlanService._validate_run(plan, kind, scope_node)

        run = PlanRun.objects.create(
            plan=plan, kind=kind, scope_node=scope_node,
            config_snapshot=PlanService._config_snapshot(plan, kind, scope_node),
        )
        from apps.jobs.dispatch import run_or_dispatch
        from apps.jobs.models import BulkJob
        from apps.jobs.services import JobService
        from apps.targets.tasks import execute_plan_run_task

        job = JobService.create(BulkJob.JobType.PLAN_RUN, actor if getattr(actor, 'pk', None) else None)
        run.job = job
        run.save(update_fields=['job', 'updated_at'])
        run_or_dispatch(execute_plan_run_task, job, run.id)
        run.refresh_from_db()
        AuditService.log('create', 'targets.PlanRun', run.id, actor, {'kind': kind, 'plan': plan.code})
        return run

    @staticmethod
    def _validate_run(plan, kind, scope_node):
        plan_kpis = list(plan.plan_kpis.select_related('kpi', 'recipe'))
        if kind in (PlanRun.SPATIAL, PlanRun.REALIGN):
            missing = [pk.kpi.code for pk in plan_kpis if pk.recipe is None]
            if missing:
                raise BusinessError(f'These KPIs have no allocation recipe: {", ".join(missing)}.')
        if kind == PlanRun.SPATIAL:
            untopped = [pk.kpi.code for pk in plan_kpis if pk.top_value is None]
            if untopped:
                raise BusinessError(f'Set a top number first for: {", ".join(untopped)}.')
        if kind == PlanRun.PRODUCT:
            if not plan.product_scope:
                raise BusinessError('The plan has no product scope (SKU groups) configured.')
        if kind == PlanRun.REALIGN:
            if scope_node is None:
                raise BusinessError('A realignment run needs the changed subtree\'s root node.')
            if not plan.allocations.filter(geography_node=scope_node, sku_group=None).exists():
                raise BusinessError('That node has no committed target to re-split.')

    @staticmethod
    def _config_snapshot(plan, kind, scope_node) -> dict:
        return {
            'kind': kind,
            'plan': {'code': plan.code, 'period': plan.period.code,
                     'root_geography': plan.root_geography.code,
                     'planning_grain': plan.planning_grain, 'product_scope': plan.product_scope},
            'scope_node': scope_node.code if scope_node else None,
            'kpis': [{
                'kpi': pk.kpi.code, 'kpi_version': pk.kpi.version,
                'recipe': pk.recipe.code if pk.recipe else None,
                'recipe_version': pk.recipe.version if pk.recipe else None,
                'recipe_config': {
                    'weight_components': pk.recipe.weight_components,
                    'base_window': pk.recipe.base_window,
                    'growth': pk.recipe.growth,
                    'constraints': pk.recipe.constraints,
                    'rounding': pk.recipe.rounding,
                } if pk.recipe else None,
                'baseline_spec': pk.baseline_spec,
                'product_split': pk.product_split,
                'top_value': str(pk.top_value) if pk.top_value is not None else None,
            } for pk in plan.plan_kpis.select_related('kpi', 'recipe')],
        }

    @staticmethod
    def execute_run(run_id: int, job=None) -> PlanRun:
        """Task entry point: compute the stage into staging. Never touches committed rows."""
        run = PlanRun.objects.select_related(
            'plan', 'plan__period', 'plan__root_geography', 'plan__channel', 'scope_node').get(pk=run_id)
        run.status = PlanRun.RUNNING
        run.save(update_fields=['status', 'updated_at'])
        try:
            run.allocations.all().delete()  # re-execute is idempotent on its own staging
            handler = {
                PlanRun.BASELINE: PlanService._run_baseline,
                PlanRun.SPATIAL: PlanService._run_spatial,
                PlanRun.PRODUCT: PlanService._run_product,
                PlanRun.REALIGN: PlanService._run_spatial,  # same math, scoped root + fixed total
            }[run.kind]
            stats = handler(run, job)
        except Exception:
            run.status = PlanRun.FAILED
            run.save(update_fields=['status', 'updated_at'])
            raise
        # An admin may have discarded the run while it computed — don't resurrect it.
        current = PlanRun.objects.values_list('status', flat=True).get(pk=run.pk)
        if current == PlanRun.DISCARDED:
            run.allocations.all().delete()
            run.status = PlanRun.DISCARDED
            return run
        run.stats = stats
        run.status = PlanRun.STAGED
        run.save(update_fields=['stats', 'status', 'updated_at'])
        return run

    # ── plan geography scope ─────────────────────────────────────────────────
    @staticmethod
    def _plan_levels(plan, root=None) -> list[list[dict]]:
        """The plan's slice of the geography tree, as levels from the root down to the
        planning grain: ``[[root], [children…], …]``. Each node dict carries id/parent_id/
        level/code/attributes. One indexed prefix query, no recursion."""
        root = root or plan.root_geography
        rows = list(
            GeographyNode.objects.filter(path__startswith=root.path, is_active=True)
            .values('id', 'parent_id', 'level', 'code', 'depth', 'attributes')
            .order_by('depth', 'id')
        )
        grain = plan.planning_grain
        levels, current = [], [root.id]
        by_parent: dict = {}
        node_by_id = {r['id']: r for r in rows}
        for r in rows:
            by_parent.setdefault(r['parent_id'], []).append(r)
        if root.id not in node_by_id:  # root row (depth filter) — fetch its own values
            node_by_id[root.id] = {'id': root.id, 'parent_id': root.parent_id, 'level': root.level,
                                   'code': root.code, 'depth': root.depth, 'attributes': root.attributes}
        levels.append([node_by_id[root.id]])
        while True:
            next_level = []
            for pid in current:
                if grain and node_by_id[pid]['level'] == grain:
                    continue  # the grain is the floor — don't descend past it
                next_level.extend(by_parent.get(pid, []))
            if not next_level:
                break
            levels.append(next_level)
            current = [n['id'] for n in next_level]
        return levels

    @staticmethod
    def _grain_node_ids(levels) -> list[int]:
        """The floor of the plan: nodes with no children inside the plan scope."""
        parents = {n['parent_id'] for level in levels for n in level}
        return [n['id'] for level in levels for n in level if n['id'] not in parents]

    # ── input fetchers (ORM side of the pure engines) ────────────────────────
    @staticmethod
    def _basis_window(basis: str, start, end):
        """Map a baseline/recipe basis code to a date window + an annualising scale
        (plan-period value ≈ window value × scale)."""
        plan_months = (end.year - start.year) * 12 + end.month - start.month + 1
        if basis in ('ly_same_period', periods.LAST_YEAR_SAME_PERIOD):
            b = periods.resolve_comparison_window(start, end, periods.LAST_YEAR_SAME_PERIOD)
            return b[0], b[1], Decimal('1')
        if basis in ('previous_period', periods.PREVIOUS_PERIOD):
            b = periods.resolve_comparison_window(start, end, periods.PREVIOUS_PERIOD)
            return b[0], b[1], Decimal('1')
        if basis in ('l3m_avg', 'l6m_avg'):
            months = 3 if basis == 'l3m_avg' else 6
            b_start = periods._shift_months(start, -months)
            b_end = start - timedelta(days=1)
            return b_start, b_end, Decimal(plan_months) / Decimal(months)
        raise BusinessError(f'Unknown baseline basis "{basis}".')

    @staticmethod
    def _history_by_level(kpi, window, levels) -> dict:
        """KPI value per node over ``window``, computed level-by-level (a level's nodes are
        disjoint subtrees, which compute_bulk_for_nodes requires)."""
        start, end, scale = window
        out = {}
        for level in levels:
            ids = [n['id'] for n in level]
            values = KPICalculator(kpi, start, end).compute_bulk_for_nodes(ids)
            for nid, v in values.items():
                out[nid] = v * scale
        return out

    @staticmethod
    def _metric_latest(metric_code: str, node_ids, on) -> dict:
        """Latest external-metric value per node as of ``on`` (market index, census feeds)."""
        rows = (
            ExternalMetricValue.objects
            .filter(metric__code=metric_code, is_active=True, node_id__in=node_ids, measured_on__lte=on)
            .order_by('node_id', '-measured_on', '-id')
            .values_list('node_id', 'value')
        )
        out = {}
        for nid, value in rows:
            out.setdefault(nid, value)
        return out

    @staticmethod
    def _component_inputs(recipe, plan, children, contribution: dict) -> list:
        """One raw-value map per recipe component for one sibling set."""
        inputs = []
        for component in recipe.weight_components:
            source = component.get('source', 'equal')
            if source == AllocationRecipe.CONTRIBUTION:
                inputs.append({c['id']: contribution.get(c['id'], Decimal('0')) for c in children})
            elif source == AllocationRecipe.ATTRIBUTE:
                key = component.get('key', '')
                inputs.append({c['id']: (c['attributes'] or {}).get(key, 0) for c in children})
            elif source == AllocationRecipe.EXTERNAL_METRIC:
                inputs.append(PlanService._metric_latest(
                    component.get('key', ''), [c['id'] for c in children], plan.period.end_date))
            else:  # equal
                inputs.append(None)
        return inputs

    @staticmethod
    def _growth_for(recipe, children) -> dict:
        growth = recipe.growth or {}
        default = growth.get('default_pct', 0)
        per_level = growth.get('per_level_pct', {})
        return {c['id']: per_level.get(c['level'], {}).get(c['code'], default) for c in children}

    # ── stage: baseline ──────────────────────────────────────────────────────
    @staticmethod
    def _run_baseline(run, job=None) -> dict:
        """Per-node blended base for every plan KPI, plus the derived top suggestion
        (Σ grain bases × (1 + default growth)). Reference data — never committed."""
        plan = run.plan
        levels = PlanService._plan_levels(plan)
        staged = 0
        for plan_kpi in plan.plan_kpis.select_related('kpi', 'recipe'):
            spec = plan_kpi.baseline_spec or {'components': [{'basis': 'ly_same_period', 'weight': 100}]}
            components = spec.get('components') or [{'basis': 'ly_same_period', 'weight': 100}]
            per_basis = {}
            for c in components:
                window = PlanService._basis_window(
                    c.get('basis', 'ly_same_period'), plan.period.start_date, plan.period.end_date)
                per_basis[c.get('basis', 'ly_same_period')] = PlanService._history_by_level(
                    plan_kpi.kpi, window, levels)
            bases = engines.blend_baselines(components, per_basis)

            rows = [RunAllocation(
                run=run, kpi=plan_kpi.kpi, target_period=plan.period, geography_node_id=node['id'],
                channel=plan.channel, value=bases.get(node['id'], Decimal('0')),
                base_value=bases.get(node['id'], Decimal('0')),
                explain={'baseline_components': components},
            ) for level in levels for node in level]
            staged += PlanService._flush(rows, job)

            default_growth = _dec((plan_kpi.recipe.growth or {}).get('default_pct', 0)) if plan_kpi.recipe else Decimal('0')
            grain_total = sum((bases.get(nid, Decimal('0')) for nid in PlanService._grain_node_ids(levels)),
                              Decimal('0'))
            plan_kpi.derived_top_value = grain_total * (1 + default_growth / 100)
            plan_kpi.save(update_fields=['derived_top_value', 'updated_at'])
        return {'staged_rows': staged, 'kpis': plan.plan_kpis.count()}

    # ── stage: spatial split (and realign) ───────────────────────────────────
    @staticmethod
    def _run_spatial(run, job=None) -> dict:
        """Cascade each KPI's total down the geography tree, parent by parent: blended
        recipe weights → growth tilt → exact split → constraint clamp. A realign run is the
        same math rooted at ``scope_node`` with its committed total held fixed."""
        plan = run.plan
        realign = run.kind == PlanRun.REALIGN
        root = run.scope_node if realign else plan.root_geography
        levels = PlanService._plan_levels(plan, root=root)
        staged = 0

        for plan_kpi in plan.plan_kpis.select_related('kpi', 'recipe'):
            recipe = plan_kpi.recipe
            unit = (recipe.rounding or {}).get('unit')
            top = PlanService._top_for(plan, plan_kpi, root, realign)

            # Contribution history per level, once (a level's nodes are disjoint).
            contribution = {}
            if any(c.get('source') == AllocationRecipe.CONTRIBUTION for c in recipe.weight_components):
                window = PlanService._basis_window(
                    (recipe.base_window or {}).get('basis', 'ly_same_period'),
                    plan.period.start_date, plan.period.end_date)
                contribution = PlanService._history_by_level(plan_kpi.kpi, window, levels)

            values = {root.id: top}
            rows = [RunAllocation(
                run=run, kpi=plan_kpi.kpi, target_period=plan.period, geography_node_id=root.id,
                channel=plan.channel, value=top, base_value=contribution.get(root.id),
                explain={'top_number': str(top), 'source': 'realign_committed' if realign else 'plan_top_value'},
            )]

            children_by_parent: dict = {}
            for level in levels[1:]:
                for n in level:
                    children_by_parent.setdefault(n['parent_id'], []).append(n)

            for level in levels:
                for parent in level:
                    children = children_by_parent.get(parent['id'])
                    if not children or parent['id'] not in values:
                        continue
                    parent_value = values[parent['id']]
                    keys = [c['id'] for c in children]
                    inputs = PlanService._component_inputs(recipe, plan, children, contribution)
                    weights, explain = engines.resolve_weights(recipe.weight_components, inputs, keys)
                    tilted = engines.apply_growth(weights, PlanService._growth_for(recipe, children))
                    split = disaggregator.split_by_weights(parent_value, [(k, tilted[k]) for k in keys], unit=unit)
                    split = disaggregator.apply_constraints(
                        split, keys, {k: contribution.get(k) for k in keys},
                        recipe.constraints or None, parent_value, unit)
                    for child in children:
                        cid = child['id']
                        values[cid] = split[cid]
                        rows.append(RunAllocation(
                            run=run, kpi=plan_kpi.kpi, target_period=plan.period, geography_node_id=cid,
                            channel=plan.channel, value=split[cid], base_value=contribution.get(cid),
                            explain=explain[cid],
                        ))
                staged += PlanService._flush(rows, job)
                rows = []
        return {'staged_rows': staged, 'kpis': plan.plan_kpis.count(),
                'root': root.code, 'realign': realign}

    @staticmethod
    def _top_for(plan, plan_kpi, root, realign) -> Decimal:
        if not realign:
            if plan_kpi.top_value is None:
                raise BusinessError(f'KPI {plan_kpi.kpi.code} has no top number.')
            return plan_kpi.top_value
        committed = TargetAllocation.objects.filter(
            plan=plan, kpi=plan_kpi.kpi, geography_node=root,
            target_period=plan.period, sku_group=None,
        ).first()
        if committed is None:
            raise BusinessError(
                f'No committed target on {root.code} for {plan_kpi.kpi.code} — nothing to re-split.')
        return committed.effective_target

    # ── stage: product split ─────────────────────────────────────────────────
    @staticmethod
    def _run_product(run, job=None) -> dict:
        """Split each committed grain-node total across the plan's SKU groups by local
        product-mix history, with fixed percentages (NPI seeding) off the top.
        Materialised only at the planning grain — group rollups are computed on read."""
        plan = run.plan
        groups = list(plan.product_scope)
        group_objs = {g.code: g for g in SKUGroup.objects.filter(code__in=groups, is_active=True)}
        missing = [g for g in groups if g not in group_objs]
        if missing:
            raise BusinessError(f'Unknown SKU groups in product scope: {", ".join(missing)}.')

        levels = PlanService._plan_levels(plan)
        grain_ids = set(PlanService._grain_node_ids(levels))

        staged = 0
        for plan_kpi in plan.plan_kpis.select_related('kpi', 'recipe'):
            split_spec = plan_kpi.product_split or {}
            fixed_mix = split_spec.get('mix', {}) if split_spec.get('mode') == 'fixed' else \
                {g: p for g, p in (split_spec.get('fixed_mix') or {}).items()}

            # Local mix history: this KPI restricted to each group, per grain node, over LY.
            # The group filter deliberately REPLACES any KPI-level sku_filter here — the totals
            # being split already reflect the KPI's own filter; group history is only the
            # weighting signal (e.g. a focus-SKU KPI split across FOCUS/NPI/ENO groups).
            window = PlanService._basis_window('ly_same_period', plan.period.start_date, plan.period.end_date)
            history_by_group = {}
            for gcode in groups:
                if gcode in fixed_mix:
                    continue  # fixed groups don't need history
                scoped = copy.copy(plan_kpi.kpi)
                scoped.sku_filter = {'type': 'group', 'group_code': gcode}
                history_by_group[gcode] = PlanService._history_by_level(scoped, window, [
                    [{'id': nid} for nid in grain_ids]])

            source = TargetAllocation.objects.filter(
                plan=plan, kpi=plan_kpi.kpi, sku_group=None,
                target_period=plan.period, geography_node_id__in=grain_ids,
            ).values_list('geography_node_id', 'target_period_id', 'target_value', 'override_value')
            rows = []
            for node_id, period_id, value, override in source.iterator(chunk_size=_CHUNK):
                total = override if override is not None else value
                history = {g: history_by_group.get(g, {}).get(node_id, Decimal('0')) for g in groups}
                unit = (plan_kpi.recipe.rounding or {}).get('unit') if plan_kpi.recipe else None
                split = engines.split_product_mix(total, groups, history, fixed_mix=fixed_mix, unit=unit)
                for gcode, amount in split.items():
                    rows.append(RunAllocation(
                        run=run, kpi=plan_kpi.kpi, target_period_id=period_id, geography_node_id=node_id,
                        channel=plan.channel, sku_group=group_objs[gcode], value=amount,
                        explain={'product_split': {'mode': split_spec.get('mode', 'history'),
                                                   'fixed_mix': {k: str(_dec(v)) for k, v in fixed_mix.items()}}},
                    ))
                if len(rows) >= _CHUNK:
                    staged += PlanService._flush(rows, job)
                    rows = []
            staged += PlanService._flush(rows, job)
        return {'staged_rows': staged, 'groups': groups}

    # ── staging → committed ──────────────────────────────────────────────────
    @staticmethod
    def preview_run(run: PlanRun, limit: int = 20) -> dict:
        """Staged vs committed, before anyone commits: totals, what changes, and — the
        contract — every override the commit would collide with."""
        if run.status != PlanRun.STAGED:
            raise BusinessError('Only a staged run can be previewed.')
        existing = PlanService._existing_for(run)
        new = changed = unchanged = 0
        staged_total = Decimal('0')
        collisions, deltas = [], []
        for row in run.allocations.select_related('geography_node', 'kpi').iterator(chunk_size=_CHUNK):
            staged_total += row.value
            key = (row.kpi_id, row.target_period_id, row.geography_node_id, row.channel_id, row.sku_group_id)
            current = existing.get(key)
            if current is None:
                new += 1
                continue
            current_target, current_override, node_code = current
            effective = current_override if current_override is not None else current_target
            if current_override is not None and row.value != effective:
                collisions.append({'geography_node': row.geography_node.code, 'kpi': row.kpi.code,
                                   'override': str(current_override), 'staged': str(row.value)})
            if row.value == effective:
                unchanged += 1
            else:
                changed += 1
                deltas.append({'geography_node': row.geography_node.code, 'kpi': row.kpi.code,
                               'from': str(effective), 'to': str(row.value),
                               'delta': str(row.value - effective)})
        deltas.sort(key=lambda d: abs(Decimal(d['delta'])), reverse=True)
        return {
            'run_id': run.id, 'kind': run.kind,
            'staged_rows': new + changed + unchanged, 'staged_total': str(staged_total),
            'new': new, 'changed': changed, 'unchanged': unchanged,
            'override_collisions': collisions[:limit], 'override_collision_count': len(collisions),
            'top_deltas': deltas[:limit],
        }

    @staticmethod
    def _existing_for(run) -> dict:
        # Compare against ALL committed rows on the staged dimensions (not just this plan's) —
        # commit upserts by dimension, so a plan-less bulk-imported row collides too.
        rows = TargetAllocation.objects.filter(
            kpi_id__in=run.allocations.values_list('kpi_id', flat=True).distinct(),
            target_period_id__in=run.allocations.values_list('target_period_id', flat=True).distinct(),
        ).select_related('geography_node').values_list(
            'kpi_id', 'target_period_id', 'geography_node_id', 'channel_id', 'sku_group_id',
            'target_value', 'override_value', 'geography_node__code',
        )
        return {(k, p, g, c, s): (tv, ov, code) for k, p, g, c, s, tv, ov, code in rows}

    @staticmethod
    @transaction.atomic
    def commit_run(run: PlanRun, actor=None, override_strategy: str = 'keep') -> dict:
        """Copy staging → ``TargetAllocation`` atomically and snapshot the full config into
        ``ComputationLog``. Overrides are kept (default) or dropped explicitly — never wiped
        as a side effect. Draft-plan commits land approved; later states land pending."""
        if run.status != PlanRun.STAGED:
            raise BusinessError('Only a staged run can be committed.')
        if run.kind == PlanRun.BASELINE:
            raise BusinessError('A baseline run is reference data — there is nothing to commit.')
        _assert_period_open(run.plan.period)
        if override_strategy not in ('keep', 'drop'):
            raise BusinessError('override_strategy must be "keep" or "drop".')

        plan = run.plan
        status = TargetAllocation.APPROVED if plan.status == TargetPlan.DRAFT else TargetAllocation.PENDING
        stats = {'created': 0, 'updated': 0, 'overrides_kept': 0, 'overrides_dropped': 0}

        # In draft every commit re-baselines original_target_value (iterating on the split is
        # the point); past draft (realign) the original is the change-cap anchor and must survive.
        rebaseline = plan.status == TargetPlan.DRAFT
        for row in run.allocations.iterator(chunk_size=_CHUNK):
            defaults = {'target_value': row.value, 'base_value': row.base_value, 'plan': plan,
                        'source': TargetAllocation.SYSTEM, 'status': status}
            if rebaseline:
                defaults['original_target_value'] = row.value
            allocation, created = TargetAllocation.objects.update_or_create(
                target_period_id=row.target_period_id, kpi_id=row.kpi_id,
                geography_node_id=row.geography_node_id,
                channel_id=row.channel_id, sku_group_id=row.sku_group_id,
                defaults=defaults, create_defaults={**defaults, 'original_target_value': row.value},
            )
            stats['created' if created else 'updated'] += 1
            if not created and allocation.override_value is not None:
                if override_strategy == 'drop':
                    allocation.override_value = None
                    allocation.is_modified = False
                    allocation.modification_reason = ''
                    allocation.save(update_fields=['override_value', 'is_modified',
                                                   'modification_reason', 'updated_at'])
                    stats['overrides_dropped'] += 1
                else:
                    stats['overrides_kept'] += 1

        ComputationLog.objects.create(
            computation_type='plan_run_commit', entity_id=plan.root_geography_id,
            period_id=plan.period_id, triggered_by_id=getattr(actor, 'pk', None),
            config_snapshot={**run.config_snapshot, 'run_id': run.id,
                             'override_strategy': override_strategy},
            result_snapshot=stats,
        )
        run.status = PlanRun.COMMITTED
        run.committed_by = actor if getattr(actor, 'pk', None) else None
        run.committed_at = timezone.now()
        run.save(update_fields=['status', 'committed_by', 'committed_at', 'updated_at'])
        AuditService.log('update', 'targets.PlanRun', run.id, actor,
                         {'committed': stats, 'kind': run.kind})
        return stats

    @staticmethod
    @transaction.atomic
    def discard_run(run: PlanRun, actor=None) -> PlanRun:
        # RUNNING is discardable too — a crashed worker must not wedge the stage forever;
        # execute_run re-checks status before staging so a live worker can't resurrect it.
        if run.status not in (PlanRun.STAGED, PlanRun.FAILED, PlanRun.PENDING, PlanRun.RUNNING):
            raise BusinessError(f'A {run.status} run cannot be discarded.')
        run.allocations.all().delete()
        run.status = PlanRun.DISCARDED
        run.save(update_fields=['status', 'updated_at'])
        AuditService.log('update', 'targets.PlanRun', run.id, actor, {'discarded': True})
        return run

    @staticmethod
    def explain(run: PlanRun, geography_node_id: int) -> list[dict]:
        """Why did this node get these numbers — straight from staging (RFP requirement)."""
        return [{
            'kpi': r.kpi.code, 'period': r.target_period.code,
            'sku_group': r.sku_group.code if r.sku_group else None,
            'value': str(r.value),
            'base_value': str(r.base_value) if r.base_value is not None else None,
            'explain': r.explain,
        } for r in run.allocations.filter(geography_node_id=geography_node_id)
            .select_related('kpi', 'target_period', 'sku_group')]

    # ── planning grid (lazy, one level per call — scales to 2L nodes) ────────
    @staticmethod
    def default_grid_parent(plan: TargetPlan, user):
        """Where the grid opens when no parent is asked for. Unplaced operators start at
        the plan root. A placed persona starts at THEIR subtree: the parent of their
        shallowest owned territory inside the plan, so their own node(s) appear as rows
        (numbers, share-of-parent, edit) under a masked parent — an ASM two levels below
        the root would otherwise land on a masked root with zero visible rows.
        A disjoint multi-territory owner lands on the shallowest branch; the rest is
        reachable via the territory jump."""
        root = plan.root_geography
        home = getattr(user, 'entity', None)
        if home is None:
            return root
        tops = AssignmentService.owned_top_scopes_for_entity(home.pk)
        if any(root.path.startswith(t.path) for t in tops):
            return root  # they own the plan root (or above): full grid, unmasked
        tops_in_plan = [t for t in tops if t.path.startswith(root.path)]
        if not tops_in_plan:
            return root  # plan doesn't cover their territory: masked root, empty grid
        shallowest = tops_in_plan[0]
        return shallowest.parent if shallowest.parent_id else shallowest

    @staticmethod
    def grid(plan: TargetPlan, kpi, parent=None, period=None, children_qs=None,
             page: int = 1, page_size: int = 100, mask_parent: bool = False) -> dict:
        """One level of the planning grid: ``parent``'s children with the planner-context
        columns (base, growth %, share of parent, bottom-up rollup, review status). The
        caller expands level by level, so no response ever carries a whole subtree.
        ``children_qs`` lets the view pass a territory-scoped queryset (RBAC);
        ``mask_parent`` blanks the parent row's numbers when the parent is outside the
        requester's territories (its totals would span siblings they cannot see)."""
        parent = parent or plan.root_geography
        period = period or plan.period
        if children_qs is None:
            children_qs = GeographyNode.objects.filter(is_active=True)
        children_qs = children_qs.filter(parent_id=parent.id, is_active=True).order_by('name', 'id')

        page = max(1, page)
        page_size = min(max(1, page_size), 500)
        total = children_qs.count()
        offset = (page - 1) * page_size
        children = list(children_qs[offset:offset + page_size].values('id', 'name', 'code', 'level'))
        child_ids = [c['id'] for c in children]

        allocs = {
            a.geography_node_id: a for a in TargetAllocation.objects.filter(
                target_period=period, kpi=kpi, channel=plan.channel, sku_group=None,
                geography_node_id__in=child_ids + [parent.id], is_active=True,
            )
        }
        bottom_up = {
            r['geography_node__parent_id']: r['v'] for r in TargetAllocation.objects.filter(
                target_period=period, kpi=kpi, channel=plan.channel, sku_group=None,
                geography_node__parent_id__in=child_ids, is_active=True,
            ).values('geography_node__parent_id').annotate(v=Sum(_EFFECTIVE))
        }
        child_counts = {
            r['parent_id']: r['n'] for r in GeographyNode.objects.filter(
                parent_id__in=child_ids, is_active=True,
            ).values('parent_id').annotate(n=Count('id'))
        }
        reviews = dict(plan.review_tasks.filter(
            node_id__in=child_ids + [parent.id]).values_list('node_id', 'status'))

        # Who is accountable for each row today: the direct owner, else the nearest
        # ancestor's owner (owning a territory implies owning everything beneath it).
        ancestor_ids = [a.id for a in parent.get_ancestors()]  # deepest first
        owners = AssignmentService.owners_for_scopes(child_ids + [parent.id] + ancestor_ids)
        parent_fallback = next((owners[i] for i in ancestor_ids if i in owners), None)
        child_fallback = owners.get(parent.id) or parent_fallback

        def owner_payload(node_id):
            direct = owners.get(node_id)
            fallback = parent_fallback if node_id == parent.id else child_fallback
            entity, inherited = (direct, False) if direct else (fallback, True)
            if entity is None:
                return None
            return {'entity_id': entity.id, 'name': entity.name, 'code': entity.code,
                    'type': entity.entity_type.name, 'inherited': inherited}

        parent_alloc = allocs.get(parent.id)
        parent_effective = parent_alloc.effective_target if parent_alloc else None

        def row(node_id, name, code, level):
            a = allocs.get(node_id)
            effective = a.effective_target if a else None
            base = a.base_value if a else None
            growth = None
            if effective is not None and base:
                growth = str(((effective / base - 1) * 100).quantize(_PCT_Q, rounding=ROUND_HALF_UP))
            bu = bottom_up.get(node_id)
            return {
                'geography_node_id': node_id, 'name': name, 'code': code, 'level': level,
                'children_count': child_counts.get(node_id, 0),
                'allocation_id': a.id if a else None,
                'target': str(effective) if effective is not None else None,
                'original': str(a.original_target_value) if a else None,
                'override': str(a.override_value) if a and a.override_value is not None else None,
                'base': str(base) if base is not None else None,
                'growth_pct': growth,
                'share_pct': _pct_of(effective, parent_effective),
                'bottom_up': str(bu) if bu is not None else None,
                'gap': str(bu - effective) if bu is not None and effective is not None else None,
                'status': a.status if a else None,
                'is_modified': a.is_modified if a else False,
                'review_status': reviews.get(node_id),
                'owner': owner_payload(node_id),
            }

        parent_row = row(parent.id, parent.name, parent.code, parent.level)
        parent_row['children_count'] = total
        if mask_parent:
            for key in ('allocation_id', 'target', 'original', 'override', 'base',
                        'growth_pct', 'share_pct', 'bottom_up', 'gap', 'status'):
                parent_row[key] = None
        else:
            # The parent's bottom-up spans ALL its children (not just this page).
            parent_bu = TargetAllocation.objects.filter(
                target_period=period, kpi=kpi, channel=plan.channel, sku_group=None,
                geography_node__parent_id=parent.id, is_active=True,
            ).aggregate(v=Sum(_EFFECTIVE))['v']
            parent_row['bottom_up'] = str(parent_bu) if parent_bu is not None else None
            if parent_bu is not None and parent_effective is not None:
                parent_row['gap'] = str(parent_bu - parent_effective)
        return {
            'plan': plan.id, 'kpi': kpi.code, 'period': period.code,
            'parent': parent_row,
            'rows': [row(c['id'], c['name'], c['code'], c['level']) for c in children],
            'page': page, 'page_size': page_size, 'total': total,
        }

    # ── shared ───────────────────────────────────────────────────────────────
    @staticmethod
    def _flush(rows, job) -> int:
        if not rows:
            return 0
        RunAllocation.objects.bulk_create(rows, batch_size=_CHUNK)
        if job is not None:
            from apps.jobs.services import JobService
            JobService.update_progress(job, processed=job.processed_rows + len(rows),
                                       success=job.success_count + len(rows), error=job.error_count)
        return len(rows)
