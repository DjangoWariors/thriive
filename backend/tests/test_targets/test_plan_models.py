"""Plan-centric model spine (P1) — the aggregate hangs together and its invariants hold.

Behaviour (runs, staging, commits, cascade) arrives with P2/P3; these tests pin the schema
contracts the later phases build on.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import (
    AllocationRecipe,
    PlanKpi,
    PlanRun,
    ReviewTask,
    RunAllocation,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
)


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO', levels=['nation', 'zone'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    zone = GeographyNode.objects.create(geography_type=gt, name='North', code='NORTH', level='zone', parent=nation)
    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )
    period = TargetPeriod.objects.create(
        code='FY27-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    return {'nation': nation, 'zone': zone, 'kpi': kpi, 'period': period}


@pytest.fixture
def plan(world):
    return TargetPlan.objects.create(
        name='FY 2026-27 GT AOP', code='AOP-FY27-GT', period=world['period'],
        root_geography=world['nation'], planning_grain='zone', review_levels=['zone'],
    )


def test_plan_defaults_to_draft(plan):
    assert plan.status == TargetPlan.DRAFT


def test_plan_kpi_unique_per_plan(plan, world):
    recipe = AllocationRecipe.objects.create(
        name='GT value split', code='GT_VALUE', effective_from=date.today(),
        weight_components=[{'source': 'contribution', 'weight': 70},
                           {'source': 'attribute', 'key': 'outlet_count', 'weight': 30}],
    )
    PlanKpi.objects.create(plan=plan, kpi=world['kpi'], recipe=recipe, top_value=Decimal('1400000000'))
    with pytest.raises(IntegrityError):
        PlanKpi.objects.create(plan=plan, kpi=world['kpi'])


def test_run_stages_to_runallocation_not_committed(plan, world):
    run = PlanRun.objects.create(plan=plan, kind=PlanRun.SPATIAL, status=PlanRun.STAGED)
    RunAllocation.objects.create(
        run=run, kpi=world['kpi'], target_period=world['period'], geography_node=world['zone'],
        value=Decimal('420000000'), base_value=Decimal('380000000'),
        explain={'contribution': '3.04', 'outlet_count': '2.8'},
    )
    # Staging is invisible to the committed axis achievements read.
    assert TargetAllocation.objects.count() == 0
    assert run.allocations.count() == 1


def test_discarding_run_cascades_staging(plan, world):
    run = PlanRun.objects.create(plan=plan, kind=PlanRun.SPATIAL, status=PlanRun.STAGED)
    RunAllocation.objects.create(
        run=run, kpi=world['kpi'], target_period=world['period'], geography_node=world['zone'], value=1,
    )
    run.delete()
    assert RunAllocation.objects.count() == 0


def test_committed_allocation_links_back_to_plan(plan, world):
    a = TargetAllocation.objects.create(
        target_period=world['period'], plan=plan, kpi=world['kpi'], geography_node=world['zone'],
        target_value=Decimal('420000000'), original_target_value=Decimal('420000000'),
    )
    assert plan.allocations.get() == a


def test_review_task_unique_per_plan_node(plan, world):
    ReviewTask.objects.create(plan=plan, node=world['zone'])
    with pytest.raises(IntegrityError):
        ReviewTask.objects.create(plan=plan, node=world['zone'])


def test_recipe_versions_like_other_config(world):
    recipe = AllocationRecipe.objects.create(
        name='GT value split', code='GT_VALUE', effective_from=date.today(),
        weight_components=[{'source': 'equal'}],
    )
    assert recipe.version == 1 and recipe.is_current
