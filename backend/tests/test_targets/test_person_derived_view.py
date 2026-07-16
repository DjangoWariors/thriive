"""derive_entity_targets — a person's target is the rollup of the geography they directly own.

Two trees:
  Organisation:  MGR ─ owns ─▶ REGION
                   ├── ASE1 ─ owns ─▶ TOWN1
                   └── ASE2 ─ owns ─▶ TOWN2
  Geography:     REGION ─┬─ TOWN1
                         └─ TOWN2
Targets are geography-anchored; the per-entity number is derived through the Assignment bridge.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod
from apps.targets.services import TargetService

JUN_START, JUN_END = date(2026, 6, 1), date(2026, 6, 30)
_FROM = date(2025, 1, 1)


@pytest.fixture
def etype(db):
    return NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sgeo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town1 = GeographyNode.objects.create(geography_type=gt, name='Town1', code='TOWN1', level='town', parent=region)
    town2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town', parent=region)
    return {'region': region, 'town1': town1, 'town2': town2}


def _own(entity, node, on=_FROM):
    AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=on)


@pytest.fixture
def mgr(db, etype, geo):
    e = Node.objects.create(entity_type=etype, name='MGR', code='MGR', effective_from=date.today())
    _own(e, geo['region'])
    return e


@pytest.fixture
def ase1(db, etype, mgr, geo):
    e = Node.objects.create(entity_type=etype, name='ASE1', code='ASE1', parent=mgr, effective_from=date.today())
    _own(e, geo['town1'])
    return e


@pytest.fixture
def ase2(db, etype, mgr, geo):
    e = Node.objects.create(entity_type=etype, name='ASE2', code='ASE2', parent=mgr, effective_from=date.today())
    _own(e, geo['town2'])
    return e


@pytest.fixture
def kpi(db):
    return KPIDefinition.objects.create(
        code='K', name='NSV', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        code='P1', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=JUN_START, end_date=JUN_END, status=TargetPeriod.DRAFT,
    )


def _alloc(period, kpi, node, value):
    return TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=node, target_value=Decimal(value),
        original_target_value=Decimal(value),
    )


def _derive(period, kpi, *entities):
    return TargetService.derive_entity_targets(period, kpi, [e.id for e in entities])


# ── no double count: manager owns REGION whose descendants also carry allocations ──
def test_no_double_count_when_descendants_have_allocations(period, kpi, geo, mgr, ase1, ase2):
    _alloc(period, kpi, geo['region'], '10000')
    _alloc(period, kpi, geo['town1'], '4000')
    _alloc(period, kpi, geo['town2'], '6000')
    out = _derive(period, kpi, mgr, ase1, ase2)
    assert out[mgr.id] == Decimal('10000')   # REGION's own allocation, not 10000+4000+6000
    assert out[ase1.id] == Decimal('4000')
    assert out[ase2.id] == Decimal('6000')


# ── fallback: owned node with no allocation rolls up its subtree leaves ────────
def test_fallback_rolls_up_leaf_allocations(period, kpi, geo, mgr):
    # REGION (the owned node) has no allocation; only the towns beneath it do.
    _alloc(period, kpi, geo['town1'], '4000')
    _alloc(period, kpi, geo['town2'], '6000')
    out = _derive(period, kpi, mgr)
    assert out[mgr.id] == Decimal('10000')


# ── effective dating: a transfer moves which person's rollup a territory lands in ──
def test_rollup_respects_effective_dating(period, kpi, geo, mgr, ase1, ase2):
    _alloc(period, kpi, geo['town1'], '4000')
    _alloc(period, kpi, geo['town2'], '6000')
    # Hand TOWN1 from ASE1 to ASE2 on Jun 15.
    AssignmentService.transfer(scope_id=geo['town1'].id, new_assignee_id=ase2.id,
                               effective_from=date(2026, 6, 15))
    before = TargetService.derive_entity_targets(
        period, kpi, [ase1.id, ase2.id], on=date(2026, 6, 10))
    after = TargetService.derive_entity_targets(
        period, kpi, [ase1.id, ase2.id], on=date(2026, 6, 20))
    assert before[ase1.id] == Decimal('4000') and before[ase2.id] == Decimal('6000')
    assert after[ase1.id] == Decimal('0') and after[ase2.id] == Decimal('10000')


# ── an entity that owns no territory derives to zero ──────────────────────────
def test_unplaced_entity_is_zero(period, kpi, etype):
    orphan = Node.objects.create(entity_type=etype, name='X', code='X', effective_from=date.today())
    out = TargetService.derive_entity_targets(period, kpi, [orphan.id])
    assert out[orphan.id] == Decimal('0')
