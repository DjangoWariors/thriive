"""TargetService — override/rebalance, lifecycle guards, approvals, bulk import."""
from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod
from apps.targets.services import TargetService

JUN_START, JUN_END = date(2026, 6, 1), date(2026, 6, 30)


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town_a = GeographyNode.objects.create(geography_type=gt, name='TownA', code='TOWNA', level='town', parent=region)
    town_b = GeographyNode.objects.create(geography_type=gt, name='TownB', code='TOWNB', level='town', parent=region)
    return {'region': region, 'town_a': town_a, 'town_b': town_b}


@pytest.fixture
def kpi(db):
    return KPIDefinition.objects.create(
        code='K', name='Secondary NSV', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        code='P1', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=JUN_START, end_date=JUN_END, status=TargetPeriod.DRAFT,
    )


def put_alloc(period, kpi, node, value, status=TargetAllocation.APPROVED):
    return TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=node,
        target_value=Decimal(str(value)), original_target_value=Decimal(str(value)), status=status,
    )


def alloc(period, kpi, node):
    return TargetAllocation.objects.get(target_period=period, kpi=kpi, geography_node=node)


# ── override + sibling rebalance ─────────────────────────────────────────────
def test_override_rebalances_siblings(period, kpi, geo):
    put_alloc(period, kpi, geo['region'], '10000')
    a = put_alloc(period, kpi, geo['town_a'], '5000')
    put_alloc(period, kpi, geo['town_b'], '5000')
    TargetService.modify_allocation(a, Decimal('6000'), reason='push A', rebalance=True)
    assert alloc(period, kpi, geo['town_a']).effective_target == Decimal('6000')
    assert alloc(period, kpi, geo['town_b']).effective_target == Decimal('4000')  # parent sum preserved


def test_rebalance_rejects_overflow(period, kpi, geo):
    put_alloc(period, kpi, geo['region'], '10000')
    a = put_alloc(period, kpi, geo['town_a'], '5000')
    put_alloc(period, kpi, geo['town_b'], '5000')
    with pytest.raises(BusinessError, match='siblings cannot absorb'):
        TargetService.modify_allocation(a, Decimal('11000'), rebalance=True)


# ── lifecycle guards ─────────────────────────────────────────────────────────
def test_locked_period_rejects_edits(period, kpi, geo):
    a = put_alloc(period, kpi, geo['town_a'], '5000')
    TargetService.advance_period(period, TargetPeriod.PUBLISHED)
    TargetService.advance_period(period, TargetPeriod.LOCKED)
    a.refresh_from_db()
    with pytest.raises(BusinessError):
        TargetService.modify_allocation(a, Decimal('6000'))


def test_lock_freezes_allocations(period, kpi, geo):
    put_alloc(period, kpi, geo['town_a'], '5000')
    # Skipping published is legal: a cycle can finalize a month no plan ever published.
    TargetService.advance_period(period, TargetPeriod.LOCKED)
    assert alloc(period, kpi, geo['town_a']).status == TargetAllocation.LOCKED


def test_advance_is_forward_only_and_idempotent(period):
    TargetService.advance_period(period, TargetPeriod.LOCKED)
    # Repeat and backward events are no-ops, never errors (events can replay out of order).
    TargetService.advance_period(period, TargetPeriod.LOCKED)
    TargetService.advance_period(period, TargetPeriod.PUBLISHED)
    period.refresh_from_db()
    assert period.status == TargetPeriod.LOCKED


# ── approvals ────────────────────────────────────────────────────────────────
def test_approve_all_pending(period, kpi, geo):
    TargetService.advance_period(period, TargetPeriod.PUBLISHED)
    put_alloc(period, kpi, geo['town_a'], '5000', status=TargetAllocation.PENDING)
    put_alloc(period, kpi, geo['town_b'], '5000', status=TargetAllocation.PENDING)
    result = TargetService.approve_all_pending(period)
    assert result['approved'] == 2
    assert alloc(period, kpi, geo['town_a']).status == TargetAllocation.APPROVED


def test_policy_tiebreak_is_deterministic(period, kpi, geo):
    from apps.targets.models import RevisionPolicy
    a = put_alloc(period, kpi, geo['town_a'], '5000')
    RevisionPolicy.objects.create(name='A', code='APOL', effective_from=date.today(),
                                  auto_approve_within_pct=Decimal('5'))
    RevisionPolicy.objects.create(name='B', code='BPOL', effective_from=date.today(),
                                  auto_approve_within_pct=Decimal('50'))
    # Equal specificity → highest (code, version) wins, regardless of DB return order.
    assert TargetService._resolve_revision_policy(a).code == 'BPOL'


# ── bulk import idempotency ──────────────────────────────────────────────────
def test_bulk_import_idempotent(period, kpi, geo):
    child_a = geo['town_a']
    csv = (
        'period_code,kpi_code,geography_node_code,target_value\n'
        f'{period.code},{kpi.code},{child_a.code},5000\n'
    )
    first = TargetService.bulk_import_allocations(csv)
    assert first['created'] == 1
    row = TargetAllocation.objects.get(target_period=period, kpi=kpi, geography_node=child_a)
    assert row.status == TargetAllocation.APPROVED  # fresh row = initial load
    second = TargetService.bulk_import_allocations(csv)
    assert second['updated'] == 1 and second['created'] == 0
    row.refresh_from_db()
    assert row.status == TargetAllocation.PENDING  # overwriting a live number = an edit, needs a checker
    assert TargetAllocation.objects.filter(target_period=period, kpi=kpi, geography_node=child_a).count() == 1


def test_bulk_import_reports_bad_rows(period, kpi, geo):
    csv = (
        'period_code,kpi_code,geography_node_code,target_value\n'
        f'{period.code},{kpi.code},NO_SUCH_NODE,5000\n'
    )
    result = TargetService.bulk_import_allocations(csv)
    assert result['status'] == 'validation_failed'
    assert result['errors'][0]['row'] == 2
