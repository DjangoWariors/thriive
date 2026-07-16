"""Constraint clamping — growth floors/caps that clamp a part yet still reconcile exactly.

``apply_constraints`` is the pure engine the plan-run spatial stage (P3) feeds; the
negative-override guard is service-level.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition
from apps.targets import disaggregator
from apps.targets.models import TargetAllocation, TargetPeriod
from apps.targets.services import TargetService


# ── pure clamp + reconcile ────────────────────────────────────────────────────
def test_growth_cap_clamps_and_reconciles():
    # Raw split pushes B to 2400 off a 1000 base (+140%); cap growth at +100% (max 2000).
    split = {'A': Decimal('600'), 'B': Decimal('2400')}
    out = disaggregator.apply_constraints(
        split, ['A', 'B'], bases={'A': Decimal('1000'), 'B': Decimal('1000')},
        constraints={'max_growth_pct': 100}, total=Decimal('3000'), unit=1,
    )
    assert out['B'] == Decimal('2000')          # clamped to base × 2
    assert out['A'] == Decimal('1000')          # absorbs the 400
    assert sum(out.values(), Decimal('0')) == Decimal('3000')


def test_min_growth_floor_lifts_and_reconciles():
    split = {'A': Decimal('500'), 'B': Decimal('2500')}
    out = disaggregator.apply_constraints(
        split, ['A', 'B'], bases={'A': Decimal('1000'), 'B': Decimal('1000')},
        constraints={'min_growth_pct': 0}, total=Decimal('3000'), unit=1,
    )
    assert out['A'] == Decimal('1000')          # lifted to its base (0% growth floor)
    assert out['B'] == Decimal('2000')
    assert sum(out.values(), Decimal('0')) == Decimal('3000')


def test_all_clamped_last_absorbs():
    # Both parts hit the cap → the delta has nowhere free to go; the last part absorbs it
    # (documented escape hatch: an infeasible constraint set never loses the total).
    split = {'A': Decimal('1500'), 'B': Decimal('1500')}
    out = disaggregator.apply_constraints(
        split, ['A', 'B'], bases={'A': Decimal('1000'), 'B': Decimal('1000')},
        constraints={'max_growth_pct': 0}, total=Decimal('3000'), unit=1,
    )
    assert out['A'] == Decimal('1000')
    assert sum(out.values(), Decimal('0')) == Decimal('3000')


def test_no_constraints_is_identity():
    split = {'A': Decimal('1'), 'B': Decimal('2')}
    assert disaggregator.apply_constraints(split, ['A', 'B'], {}, None, Decimal('3')) == split


# ── service-level guard ───────────────────────────────────────────────────────
@pytest.fixture
def setup(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town = GeographyNode.objects.create(geography_type=gt, name='TownA', code='TOWNA', level='town', parent=region)
    kpi = KPIDefinition.objects.create(code='K', name='K', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
                                       measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'all'})
    period = TargetPeriod.objects.create(code='P', name='P', period_type=TargetPeriod.MONTHLY,
                                         start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
    alloc = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=town,
        target_value=Decimal('10000'), original_target_value=Decimal('10000'),
        status=TargetAllocation.APPROVED,
    )
    return alloc


def test_negative_override_rejected(setup):
    with pytest.raises(BusinessError):
        TargetService.modify_allocation(setup, Decimal('-100'))
