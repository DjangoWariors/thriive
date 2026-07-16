"""Plan runs (P3) — staging isolation, atomic commit, override handling, realign invariant.

World: India → 2 zones → 2 towns each. Plans are monthly (Jun'26); LY history (Jun'25,
the plan's LY-same-period window): A1=1000, A2=3000, B1=2000, B2=2000 → zones 4000/4000.
"""
import time
from datetime import date
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.audit.models import ComputationLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.master_data.models import SKUGroup
from apps.targets.models import (
    AllocationRecipe,
    PlanRun,
    RunAllocation,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
)
from apps.targets.plan_services import PlanService
from apps.targets.services import TargetService

pytestmark = pytest.mark.django_db


def mk_txn(node, amount, when=date(2025, 6, 15), sku=''):
    Transaction.objects.create(
        attributed_node_id=node.id, transaction_date=when, transaction_type=Transaction.SALE,
        transaction_level=Transaction.SECONDARY, net_amount=Decimal(str(amount)), sku_code=sku,
    )


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO', levels=['nation', 'zone', 'town'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    za = GeographyNode.objects.create(geography_type=gt, name='ZoneA', code='ZA', level='zone', parent=nation)
    zb = GeographyNode.objects.create(geography_type=gt, name='ZoneB', code='ZB', level='zone', parent=nation)
    a1 = GeographyNode.objects.create(geography_type=gt, name='A1', code='A1', level='town', parent=za,
                                      attributes={'outlet_count': 100})
    a2 = GeographyNode.objects.create(geography_type=gt, name='A2', code='A2', level='town', parent=za,
                                      attributes={'outlet_count': 300})
    b1 = GeographyNode.objects.create(geography_type=gt, name='B1', code='B1', level='town', parent=zb,
                                      attributes={'outlet_count': 200})
    b2 = GeographyNode.objects.create(geography_type=gt, name='B2', code='B2', level='town', parent=zb,
                                      attributes={'outlet_count': 200})
    for node, amount in ((a1, 1000), (a2, 3000), (b1, 2000), (b2, 2000)):
        mk_txn(node, amount)

    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )
    annual = TargetPeriod.objects.create(
        code='FY27', name='FY 2026-27', period_type=TargetPeriod.ANNUAL,
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    jun = TargetPeriod.objects.create(code='FY27-M06', name='Jun', period_type=TargetPeriod.MONTHLY,
                                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), parent=annual)
    recipe = AllocationRecipe.objects.create(
        name='By contribution', code='CONTRIB', effective_from=date.today(),
        weight_components=[{'source': 'contribution', 'weight': 100}],
        base_window={'basis': 'ly_same_period'}, rounding={'unit': 1},
    )
    return {'nation': nation, 'za': za, 'zb': zb, 'a1': a1, 'a2': a2, 'b1': b1, 'b2': b2,
            'kpi': kpi, 'annual': annual, 'jun': jun, 'recipe': recipe}


@pytest.fixture
def plan(world):
    return PlanService.create_plan(
        {'name': 'Jun 2026 Plan', 'code': 'PLAN-JUN27', 'period_id': world['jun'].id,
         'root_geography_id': world['nation'].id, 'product_scope': ['CORE', 'NPI']},
        kpis=[{'kpi_id': world['kpi'].id, 'recipe_id': world['recipe'].id,
               'top_value': '10000',
               'baseline_spec': {'components': [{'basis': 'ly_same_period', 'weight': 100}]},
               'product_split': {'mode': 'fixed', 'mix': {'NPI': 20}}}],
    )


def staged(run, node):
    return RunAllocation.objects.get(run=run, geography_node=node)


def committed(plan, node, period=None, sku_group=None):
    return TargetAllocation.objects.get(
        plan=plan, geography_node=node, target_period=period or plan.period, sku_group=sku_group)


def run_spatial(plan):
    run = PlanService.start_run(plan, PlanRun.SPATIAL)
    assert run.status == PlanRun.STAGED, run.job.errors if run.job else 'no job'
    return run


# ── spatial: staging + reconciliation ─────────────────────────────────────────
def test_spatial_run_stages_and_reconciles(world, plan):
    run = run_spatial(plan)
    assert staged(run, world['nation']).value == Decimal('10000')
    assert staged(run, world['za']).value == Decimal('5000')   # 4000:4000 history
    assert staged(run, world['zb']).value == Decimal('5000')
    assert staged(run, world['a1']).value == Decimal('1250')   # 1000:3000 within zone A
    assert staged(run, world['a2']).value == Decimal('3750')
    # Staging is invisible to the committed axis.
    assert TargetAllocation.objects.count() == 0
    # Explain names the contribution component and its share.
    ex = staged(run, world['a2']).explain
    assert ex['components'][0]['source'] == 'contribution'
    assert ex['components'][0]['share_pct'] == '75.00'


def test_spatial_requires_top_number(world, plan):
    pk = plan.plan_kpis.get()
    pk.top_value = None
    pk.save()
    with pytest.raises(BusinessError, match='top number'):
        PlanService.start_run(plan, PlanRun.SPATIAL)


# ── commit ────────────────────────────────────────────────────────────────────
def test_commit_creates_allocations_and_snapshot(world, plan):
    run = run_spatial(plan)
    stats = PlanService.commit_run(run)
    assert stats['created'] == 7  # nation + 2 zones + 4 towns
    a2 = committed(plan, world['a2'])
    assert a2.target_value == Decimal('3750')
    assert a2.status == TargetAllocation.APPROVED  # draft plan → approved
    assert a2.plan_id == plan.id
    log = ComputationLog.objects.get(computation_type='plan_run_commit')
    assert log.config_snapshot['kpis'][0]['recipe'] == 'CONTRIB'
    assert log.result_snapshot['created'] == 7
    run.refresh_from_db()
    assert run.status == PlanRun.COMMITTED
    assert run.allocations.count() == 7  # staging kept for explain


def test_rerun_does_not_touch_committed(world, plan):
    PlanService.commit_run(run_spatial(plan))
    PlanService.set_top_number(plan, world['kpi'], '20000')
    run2 = run_spatial(plan)
    assert staged(run2, world['za']).value == Decimal('10000')
    assert committed(plan, world['za']).effective_target == Decimal('5000')  # untouched until commit


def test_baseline_run_cannot_commit(world, plan):
    run = PlanService.start_run(plan, PlanRun.BASELINE)
    assert run.status == PlanRun.STAGED
    with pytest.raises(BusinessError, match='reference data'):
        PlanService.commit_run(run)


def test_discard_clears_staging(world, plan):
    run = run_spatial(plan)
    PlanService.discard_run(run)
    run.refresh_from_db()
    assert run.status == PlanRun.DISCARDED
    assert run.allocations.count() == 0


# ── overrides: preview surfaces them, commit never wipes silently ─────────────
def _override_a1(world, plan, value='2000'):
    a1 = committed(plan, world['a1'])
    return TargetService.modify_allocation(a1, Decimal(value), reason='local push', rebalance=False)


def test_preview_reports_collisions_and_deltas(world, plan):
    PlanService.commit_run(run_spatial(plan))
    _override_a1(world, plan)
    PlanService.set_top_number(plan, world['kpi'], '20000')
    run2 = run_spatial(plan)
    preview = PlanService.preview_run(run2)
    assert preview['override_collision_count'] == 1
    assert preview['override_collisions'][0]['geography_node'] == 'A1'
    assert preview['changed'] + preview['unchanged'] + preview['new'] == 7
    assert preview['top_deltas'][0]['delta'] != '0'


def test_commit_keep_strategy_retains_override(world, plan):
    PlanService.commit_run(run_spatial(plan))
    _override_a1(world, plan)
    run2 = run_spatial(plan)
    stats = PlanService.commit_run(run2, override_strategy='keep')
    assert stats['overrides_kept'] == 1
    a1 = committed(plan, world['a1'])
    assert a1.override_value == Decimal('2000')
    assert a1.effective_target == Decimal('2000')


def test_commit_drop_strategy_clears_override(world, plan):
    PlanService.commit_run(run_spatial(plan))
    _override_a1(world, plan)
    PlanService.set_top_number(plan, world['kpi'], '20000')
    run2 = run_spatial(plan)
    stats = PlanService.commit_run(run2, override_strategy='drop')
    assert stats['overrides_dropped'] == 1
    a1 = committed(plan, world['a1'])
    assert a1.override_value is None
    assert a1.effective_target == Decimal('2500')  # the new system number


# ── realign: scoped re-split holds the scope total ────────────────────────────
def test_realign_holds_scope_total_and_leaves_rest_alone(world, plan):
    PlanService.commit_run(run_spatial(plan))
    # Mid-year: a new town appears under zone A. No history — realign with a blended
    # recipe so the driver component gives it a share.
    gt = world['nation'].geography_type
    a3 = GeographyNode.objects.create(geography_type=gt, name='A3', code='A3', level='town',
                                      parent=world['za'], attributes={'outlet_count': 400})
    recipe = world['recipe']
    recipe.weight_components = [{'source': 'contribution', 'weight': 50},
                                {'source': 'attribute', 'key': 'outlet_count', 'weight': 50}]
    recipe.save()

    run = PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])
    assert run.status == PlanRun.STAGED
    # Zone A's committed total is held fixed; its towns re-split under it.
    assert staged(run, world['za']).value == Decimal('5000')
    town_sum = sum((staged(run, t).value for t in (world['a1'], world['a2'], a3)), Decimal('0'))
    assert town_sum == Decimal('5000')
    assert staged(run, a3).value > 0  # the new town earned a share from outlet_count
    # Zone B is outside the scope — nothing staged for it.
    assert RunAllocation.objects.filter(run=run, geography_node=world['zb']).count() == 0

    PlanService.commit_run(run)
    assert committed(plan, world['zb']).effective_target == Decimal('5000')  # untouched
    assert committed(plan, world['za']).effective_target == Decimal('5000')


def test_realign_requires_committed_scope(world, plan):
    with pytest.raises(BusinessError, match='no committed target'):
        PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])


def test_realign_after_publish_preserves_change_cap_baseline(world, plan):
    """Past draft, ``original_target_value`` is the anti-drift anchor for change caps —
    a realign re-split must update the target without re-baselining it."""
    PlanService.commit_run(run_spatial(plan))
    PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
    mk_txn(world['a1'], 2000)  # LY history shifts: A1 3000 vs A2 3000 → 50:50 within zone A

    run = PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])
    PlanService.commit_run(run)
    a1 = committed(plan, world['a1'])
    assert a1.target_value == Decimal('2500')                 # re-split applied
    assert a1.original_target_value == Decimal('1250')        # baseline survives


# ── monthly-only target setting ────────────────────────────────────────────────
def test_plan_rejects_non_monthly_period(world):
    """Targets are always set monthly — a plan cannot anchor to an annual period."""
    with pytest.raises(BusinessError, match='set monthly'):
        PlanService.create_plan(
            {'name': 'FY27 AOP', 'code': 'AOP-FY27', 'period_id': world['annual'].id,
             'root_geography_id': world['nation'].id},
            kpis=[{'kpi_id': world['kpi'].id, 'recipe_id': world['recipe'].id,
                   'top_value': '10000'}],
        )


# ── wedged runs ────────────────────────────────────────────────────────────────
def test_running_run_is_discardable(world, plan):
    run = PlanRun.objects.create(plan=plan, kind=PlanRun.SPATIAL, status=PlanRun.RUNNING)
    assert PlanService.discard_run(run).status == PlanRun.DISCARDED


def test_execute_does_not_resurrect_a_discarded_run(world, plan, monkeypatch):
    real = PlanService._run_spatial

    def discard_mid_flight(run, job=None):
        stats = real(run, job)
        PlanRun.objects.filter(pk=run.pk).update(status=PlanRun.DISCARDED)
        return stats

    monkeypatch.setattr(PlanService, '_run_spatial', staticmethod(discard_mid_flight))
    run = PlanService.start_run(plan, PlanRun.SPATIAL)
    run.refresh_from_db()
    assert run.status == PlanRun.DISCARDED
    assert run.allocations.count() == 0  # staged rows cleaned up, nothing committed


# ── product: the rest of the pipeline ──────────────────────────────────────────
def test_product_split_at_grain(world, plan):
    SKUGroup.objects.create(name='Core', code='CORE')
    SKUGroup.objects.create(name='NPI', code='NPI')
    PlanService.commit_run(run_spatial(plan))
    run = PlanService.start_run(plan, PlanRun.PRODUCT)
    assert run.status == PlanRun.STAGED, run.job.errors if run.job else 'no job'
    PlanService.commit_run(run)

    core = SKUGroup.objects.get(code='CORE')
    npi = SKUGroup.objects.get(code='NPI')
    a2_total = committed(plan, world['a2']).target_value
    a2_npi = committed(plan, world['a2'], sku_group=npi).target_value
    a2_core = committed(plan, world['a2'], sku_group=core).target_value
    assert a2_total == Decimal('3750')
    assert a2_npi == Decimal('750')                      # fixed 20%
    assert a2_core + a2_npi == a2_total                  # reconciles exactly
    # Materialised at the grain only — no product rows on the zone.
    assert not TargetAllocation.objects.filter(
        plan=plan, geography_node=world['za'], sku_group__isnull=False).exists()


# ── baseline ──────────────────────────────────────────────────────────────────
def test_baseline_computes_bases_and_derived_top(world, plan):
    recipe = world['recipe']
    recipe.growth = {'default_pct': 25}
    recipe.save()
    run = PlanService.start_run(plan, PlanRun.BASELINE)
    assert run.status == PlanRun.STAGED
    assert staged(run, world['a2']).value == Decimal('3000')  # LY history as base
    pk = plan.plan_kpis.get()
    pk.refresh_from_db()
    assert pk.derived_top_value == Decimal('10000')  # towns 8000 × 1.25


# ── lifecycle guards ──────────────────────────────────────────────────────────
def test_runs_blocked_outside_draft(world, plan):
    PlanService.commit_run(run_spatial(plan))
    PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)
    with pytest.raises(BusinessError, match='cannot start'):
        PlanService.start_run(plan, PlanRun.SPATIAL)
    # …but realign works on a live plan (mid-period churn).
    PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
    run = PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])
    assert run.status == PlanRun.STAGED
    # Published-plan commits land pending (governance), not approved.
    PlanService.commit_run(run)
    assert committed(plan, world['a1']).status == TargetAllocation.PENDING


def test_plan_transitions_guarded(plan):
    with pytest.raises(BusinessError, match='Cannot move'):
        PlanService.transition_plan(plan, TargetPlan.LOCKED)


def test_locked_period_blocks_realign_and_publish(world, plan):
    # Once the payout cycle locks the month, its targets are the paid base: no run may
    # start, and no other plan may publish new live numbers into it.
    PlanService.commit_run(run_spatial(plan))
    PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
    TargetService.advance_period(world['jun'], TargetPeriod.LOCKED)
    with pytest.raises(BusinessError, match='payout cycle'):
        PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])

    late = PlanService.create_plan(
        {'name': 'Late', 'code': 'PLAN-LATE', 'period_id': world['jun'].id,
         'root_geography_id': world['zb'].id},
        kpis=[{'kpi_id': world['kpi'].id, 'recipe_id': world['recipe'].id, 'top_value': '100'}],
    )
    with pytest.raises(BusinessError, match='payout cycle'):
        PlanService.transition_plan(late, TargetPlan.PUBLISHED)


def test_locked_period_blocks_commit_of_prestaged_run(world, plan):
    # A realign staged just before the cycle finalized must refuse to commit after.
    PlanService.commit_run(run_spatial(plan))
    PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
    run = PlanService.start_run(plan, PlanRun.REALIGN, scope_node=world['za'])
    TargetService.advance_period(world['jun'], TargetPeriod.LOCKED)
    with pytest.raises(BusinessError, match='payout cycle'):
        PlanService.commit_run(run)
    assert committed(plan, world['a1']).status == TargetAllocation.LOCKED  # untouched


# ── scale ─────────────────────────────────────────────────────────────────────
def test_10k_node_split_reconciles_fast(db):
    gt = GeographyType.objects.create(name='G', code='G10K', levels=['nation', 'zone', 'town'])
    root = GeographyNode.objects.create(geography_type=gt, name='R', code='R', level='nation')
    zones = GeographyNode.objects.bulk_create([
        GeographyNode(geography_type=gt, name=f'Z{i}', code=f'Z{i}', level='zone',
                      parent=root, path=f'{root.path}Z{i}/', depth=1)
        for i in range(10)
    ])
    towns = []
    for zi, zone in enumerate(zones):
        towns.extend(GeographyNode(
            geography_type=gt, name=f'T{zi}-{t}', code=f'T{zi}-{t}', level='town',
            parent=zone, path=f'{zone.path}T{zi}-{t}/', depth=2,
        ) for t in range(1000))
    GeographyNode.objects.bulk_create(towns, batch_size=2000)

    kpi = KPIDefinition.objects.create(
        code='K10', name='K', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'all'})
    period = TargetPeriod.objects.create(code='P10K', name='P', period_type=TargetPeriod.MONTHLY,
                                         start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
    recipe = AllocationRecipe.objects.create(
        name='Equal', code='EQ10K', effective_from=date.today(),
        weight_components=[{'source': 'equal'}], rounding={'unit': 1})
    plan = PlanService.create_plan(
        {'name': 'Scale', 'code': 'SCALE10K', 'period_id': period.id, 'root_geography_id': root.id},
        kpis=[{'kpi_id': kpi.id, 'recipe_id': recipe.id, 'top_value': '12000000'}])

    run = PlanRun.objects.create(plan=plan, kind=PlanRun.SPATIAL)
    started = time.monotonic()
    PlanService.execute_run(run.id)
    elapsed = time.monotonic() - started
    assert elapsed < 60, f'10k-node split took {elapsed:.1f}s'

    run.refresh_from_db()
    assert run.status == PlanRun.STAGED
    assert run.allocations.count() == 10_011  # root + 10 zones + 10k towns
    town_total = RunAllocation.objects.filter(
        run=run, geography_node__level='town').aggregate(s=Sum('value'))['s']
    assert town_total == Decimal('12000000')
