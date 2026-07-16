"""Sibling rebalance — the parent-sum invariant must survive rounding and reverts."""
from datetime import date
from decimal import Decimal

import pytest

from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod, TargetRevision
from apps.targets.services import TargetService

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='G', code='G', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='R', code='R', level='region')
    towns = [GeographyNode.objects.create(geography_type=gt, name=f'T{i}', code=f'T{i}',
                                          level='town', parent=region) for i in range(1, 5)]
    kpi = KPIDefinition.objects.create(
        code='K', name='K', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'})
    period = TargetPeriod.objects.create(
        code='P', name='P', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), status=TargetPeriod.PUBLISHED)
    allocs = [TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=t, target_value=Decimal('5000'),
        original_target_value=Decimal('5000'), status=TargetAllocation.APPROVED) for t in towns]
    return {'period': period, 'kpi': kpi, 'allocs': allocs}


def total(world):
    return sum(a.effective_target for a in TargetAllocation.objects.filter(
        target_period=world['period'], kpi=world['kpi']))


def test_uneven_split_sums_exactly_at_db_precision(world):
    # 4 towns of 5000. Edit T1 +1000 → three siblings absorb thirds (a non-terminating
    # division). Shares must be quantized to the column scale BEFORE saving, or the DB
    # rounds each row independently and the parent total drifts by dust.
    TargetService.modify_allocation(world['allocs'][0], Decimal('6000'), reason='r', rebalance=True)
    assert total(world) == Decimal('20000')


def test_pending_sibling_is_never_rebalanced(world):
    # T2 has its own open escalation (optimistic override awaiting a checker). A later
    # rebalance must not overwrite it: when T2's escalation is rejected, T2 reverts to
    # its pre-edit value — a rebalance written on top would be clobbered and the parent
    # sum permanently broken.
    a1, a2 = world['allocs'][0], world['allocs'][1]
    TargetService.modify_allocation(a2, Decimal('6000'), reason='mine', rebalance=False)
    a2.refresh_from_db()
    assert a2.status == TargetAllocation.PENDING

    TargetService.modify_allocation(a1, Decimal('5500'), reason='push', rebalance=True)
    a2.refresh_from_db()
    assert a2.effective_target == Decimal('6000')  # untouched — absorbed by T3/T4 only
    assert not TargetRevision.objects.filter(
        allocation=a2, source=TargetRevision.REBALANCE).exists()
    assert total(world) == Decimal('21000')  # 5500 + 6000 (optimistic) + 9500

    TargetService.reject_allocation(a2, reason='no')
    assert total(world) == Decimal('20000')  # T2's +1000 cleanly gone, invariant intact
