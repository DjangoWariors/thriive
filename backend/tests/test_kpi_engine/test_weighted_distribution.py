"""Weighted Distribution — outlets weighted by total throughput, not just counted (ND)."""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.services import KPIService
from apps.master_data.models import SKU, SKUGroup

PERIOD = (date(2026, 6, 1), date(2026, 6, 30))


@pytest.fixture
def entity(db):
    et = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    e = Node.objects.create(entity_type=et, name='ASE', code='ASE1', effective_from=date.today())
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['town'])
    node = GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN1', level='town')
    AssignmentService.create(assignee_id=e.id, scope_id=node.id, effective_from=date(2025, 1, 1))
    return e


def _node(eid):
    """The geography node the org entity owns (sales attach there, not to the person)."""
    a = Assignment.objects.filter(assignee_id=eid, role_in_scope='owner', is_active=True).first()
    return a.scope_id if a else eid


def mk_txn(eid, outlet, sku, amount):
    Transaction.objects.create(attributed_node_id=_node(eid), transaction_date=date(2026, 6, 10),
                               transaction_type=Transaction.SALE,
                               outlet_code=outlet, sku_code=sku, net_amount=Decimal(str(amount)))


def test_weighted_distribution_vs_numeric(entity):
    # Outlet throughput: O1=100 (focus), O2=200 (non-focus), O3=700 (focus).
    SKU.objects.create(code='F1', name='Focus', is_focus=True)
    SKU.objects.create(code='N1', name='Normal', is_focus=False)
    SKUGroup.objects.create(code='FOCUS', name='Focus', filter_type=SKUGroup.FILTER_RULE,
                            filter_rules={'is_focus': True})
    mk_txn(entity.id, 'O1', 'F1', 100)
    mk_txn(entity.id, 'O2', 'N1', 200)
    mk_txn(entity.id, 'O3', 'F1', 700)

    focus_measure = {'aggregation': 'weighted_distinct', 'group_field': 'outlet_code',
                     'weight_field': 'net_amount', 'weight_scope': 'all', 'net_logic': 'gross_only',
                     'sku_filter': {'type': 'group', 'group_code': 'FOCUS'}}
    all_measure = {'aggregation': 'weighted_distinct', 'group_field': 'outlet_code',
                   'weight_field': 'net_amount', 'weight_scope': 'all', 'net_logic': 'gross_only',
                   'sku_filter': {'type': 'all'}}

    wd = KPIDefinition.objects.create(
        code='WD', name='Weighted Distribution', kpi_type=KPIDefinition.RATIO, decimal_places=2,
        effective_from=date.today(), ratio_config={'numerator': focus_measure, 'denominator': all_measure},
    )
    # WD = (100 + 700) / (100 + 200 + 700) = 800/1000 = 0.80  — vs ND = 2/3 ≈ 0.67
    assert KPICalculator(wd, *PERIOD).compute_for_entity(entity.id) == Decimal('0.80')


def test_numeric_distribution_for_contrast(entity):
    SKU.objects.create(code='F1', name='Focus', is_focus=True)
    SKUGroup.objects.create(code='FOCUS', name='Focus', filter_type=SKUGroup.FILTER_RULE, filter_rules={'is_focus': True})
    mk_txn(entity.id, 'O1', 'F1', 100)
    mk_txn(entity.id, 'O3', 'F1', 700)
    Transaction.objects.create(attributed_node_id=_node(entity.id), transaction_date=date(2026, 6, 10),
                               transaction_type=Transaction.SALE, outlet_code='O2', sku_code='N1', net_amount=Decimal('200'))
    nd = KPIDefinition.objects.create(
        code='ND', name='Numeric coverage', kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0,
        effective_from=date.today(), sku_filter={'type': 'group', 'group_code': 'FOCUS'},
        measure_config={'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'})
    assert KPICalculator(nd, *PERIOD).compute_for_entity(entity.id) == Decimal('2')  # O1, O3


def test_validate_allows_weighted_distinct_for_count_distinct(db):
    errors = KPIService.validate_kpi_config({
        'kpi_type': KPIDefinition.COUNT_DISTINCT,
        'measure_config': {
            'aggregation': 'weighted_distinct', 'group_field': 'outlet_code',
            'weight_field': 'net_amount', 'measure_field': 'outlet_code', 'net_logic': 'gross_only',
        },
    })
    assert errors == []


def test_validate_rejects_weighted_distinct_for_value(db):
    errors = KPIService.validate_kpi_config({
        'kpi_type': KPIDefinition.VALUE,
        'measure_config': {
            'aggregation': 'weighted_distinct', 'group_field': 'outlet_code',
            'weight_field': 'net_amount', 'net_logic': 'gross_only',
        },
    })
    assert any('sum' in e for e in errors)


def test_weighted_distinct_bulk_matches_per_entity(entity):
    # weighted_distinct can't be folded from per-leaf counts, so compute_bulk must fall
    # back to the per-entity path and produce the same number.
    mk_txn(entity.id, 'O1', 'F1', 100)
    mk_txn(entity.id, 'O2', 'N1', 200)
    kpi = KPIDefinition.objects.create(
        code='WDC', name='WD count', kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=2,
        effective_from=date.today(),
        measure_config={
            'aggregation': 'weighted_distinct', 'group_field': 'outlet_code',
            'weight_field': 'net_amount', 'weight_scope': 'all', 'net_logic': 'gross_only',
        },
    )
    calc = KPICalculator(kpi, *PERIOD)
    per_entity = calc.compute_for_entity(entity.id)
    assert per_entity == Decimal('300.00')  # O1 (100) + O2 (200), both qualify; weight = total
    assert calc.compute_bulk([entity.id]) == {entity.id: per_entity}
