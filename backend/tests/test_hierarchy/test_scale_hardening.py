"""P1 scale-hardening behaviors: set-based geography move, DB-side code
autogen, and the _bulk_simple IN-list fallback producing identical results.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.config_services import GeographyNodeService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.hierarchy.services import NodeService

TODAY = date.today()


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(
        name='Geo', code='geo', levels=['nation', 'region', 'town', 'outlet'],
    )
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    north = GeographyNode.objects.create(geography_type=gt, name='North', code='NORTH', level='region', parent=nation)
    south = GeographyNode.objects.create(geography_type=gt, name='South', code='SOUTH', level='region', parent=nation)
    town = GeographyNode.objects.create(geography_type=gt, name='Delhi', code='DEL', level='town', parent=north)
    outlet = GeographyNode.objects.create(geography_type=gt, name='Out 1', code='OUT1', level='outlet', parent=town)
    return {'gt': gt, 'nation': nation, 'north': north, 'south': south, 'town': town, 'outlet': outlet}


# ── B2: set-based geography move ─────────────────────────────────────────────

@pytest.mark.django_db
def test_geo_move_rewrites_descendants_set_based(geo, django_assert_max_num_queries):
    from apps.accounts.models import User
    actor = User.objects.create_user(email='mv@example.com', password='x')

    # Fatten the subtree: with the old per-row bulk_update path, 40 extra
    # descendants would add materialization + update chunks; the set-based
    # rewrite keeps the query count flat regardless of subtree size.
    for i in range(40):
        GeographyNode.objects.create(
            geography_type=geo['gt'], name=f'Out {i}', code=f'OUTX{i}',
            level='outlet', parent=geo['town'],
        )

    with django_assert_max_num_queries(20):
        GeographyNodeService.move(geo['town'].pk, geo['south'].pk, actor=actor)

    town = GeographyNode.objects.get(pk=geo['town'].pk)
    outlet = GeographyNode.objects.get(pk=geo['outlet'].pk)
    assert town.path == '/IN/SOUTH/DEL/'
    assert outlet.path == '/IN/SOUTH/DEL/OUT1/'
    assert outlet.depth == 3
    assert GeographyNode.objects.filter(path__startswith='/IN/SOUTH/DEL/').count() == 42


# ── B4: DB-side code autogen ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_code_autogen_skips_non_numeric_suffixes(db):
    et = NodeType.objects.create(name='ASM', code='ASM', level_order=3, effective_from=TODAY)
    Node.objects.create(entity_type=et, name='A', code='ASM-0007', effective_from=TODAY)
    Node.objects.create(entity_type=et, name='B', code='ASM-EAST', effective_from=TODAY)  # hand-entered
    Node.objects.create(entity_type=et, name='C', code='ASM-0012', effective_from=TODAY)
    assert NodeService._generate_entity_code(et) == 'ASM-0013'


@pytest.mark.django_db
def test_code_autogen_first_of_type(db):
    et = NodeType.objects.create(name='RSM', code='RSM', level_order=2, effective_from=TODAY)
    assert NodeService._generate_entity_code(et) == 'RSM-0001'


# ── B5: _bulk_simple identical above/below the IN-list cap ───────────────────

@pytest.mark.django_db
def test_bulk_simple_fold_identical_without_in_list(geo, monkeypatch):
    from apps.kpi_engine import calculator as calc_mod
    from apps.kpi_engine.calculator import KPICalculator
    from apps.kpi_engine.models import KPIDefinition, Transaction

    et = NodeType.objects.create(name='ASM', code='ASM', level_order=3, effective_from=TODAY)
    anjali = Node.objects.create(entity_type=et, name='Anjali', code='ASM-0001', effective_from=TODAY)
    ravi = Node.objects.create(entity_type=et, name='Ravi', code='ASM-0002', effective_from=TODAY)
    Assignment.objects.create(assignee=anjali, scope=geo['north'], role_in_scope='owner',
                              effective_from=TODAY.replace(day=1))
    Assignment.objects.create(assignee=ravi, scope=geo['south'], role_in_scope='owner',
                              effective_from=TODAY.replace(day=1))

    Transaction.objects.create(attributed_node_id=geo['outlet'].pk, transaction_date=TODAY,
                               transaction_type='sale', transaction_level='secondary',
                               net_amount=Decimal('1000'), gross_amount=Decimal('1000'),
                               quantity=Decimal('1'), source='manual_entry', external_ref='SH-1')
    # A sale on unowned geography must be dropped by the fold in BOTH modes.
    Transaction.objects.create(attributed_node_id=geo['nation'].pk, transaction_date=TODAY,
                               transaction_type='sale', transaction_level='secondary',
                               net_amount=Decimal('777'), gross_amount=Decimal('777'),
                               quantity=Decimal('1'), source='manual_entry', external_ref='SH-2')

    kpi = KPIDefinition.objects.create(
        name='Core', code='CORE', kpi_type=KPIDefinition.VALUE,
        measure_config={'aggregation': 'sum', 'measure_field': 'net_amount', 'net_logic': 'all'},
        effective_from=TODAY,
    )
    start, end = TODAY.replace(day=1), TODAY

    with_in_list = KPICalculator(kpi, start, end).compute_bulk([anjali.pk, ravi.pk])
    monkeypatch.setattr(calc_mod, '_IN_LIST_MAX', 0)  # force the no-IN-list path
    without_in_list = KPICalculator(kpi, start, end).compute_bulk([anjali.pk, ravi.pk])

    assert with_in_list == without_in_list
    assert with_in_list[anjali.pk] == Decimal('1000.00')
    assert with_in_list[ravi.pk] == Decimal('0.00')
