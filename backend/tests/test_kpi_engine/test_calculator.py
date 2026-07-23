"""KPICalculator correctness — exact Decimal assertions.

Two trees:
  Organisation:  ASM1 (manager) ─ owns ─▶ REGION
                   ├── ASE1 (leaf) ─ owns ─▶ TOWN1
                   └── ASE2 (leaf) ─ owns ─▶ TOWN2
  Geography:     REGION ─┬─ TOWN1
                         └─ TOWN2

Sales attach to GEOGRAPHY (Transaction.attributed_node_id). An entity's value is the
calculator's aggregate over the territory it owns (via assignments): the manager owns
the region, so its value rolls up both towns. ``mk_txn(ase.id, …)`` resolves the org
entity's owned leaf territory automatically, so the test bodies read unchanged.
Period under test is June 2026.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.services import KPIService

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)
_FROM = date(2025, 1, 1)  # assignments effective well before the period (and last-year window)


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def etype(db):
    return NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town1 = GeographyNode.objects.create(geography_type=gt, name='Town1', code='TOWN1', level='town', parent=region)
    town2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town', parent=region)
    return {'region': region, 'town1': town1, 'town2': town2}


def _own(entity, node):
    AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=_FROM)


@pytest.fixture
def manager(db, etype, geo):
    m = Node.objects.create(entity_type=etype, name='ASM', code='ASM1', effective_from=date.today())
    _own(m, geo['region'])
    return m


@pytest.fixture
def ase1(db, etype, manager, geo):
    e = Node.objects.create(
        entity_type=etype, name='ASE1', code='ASE1', parent=manager, effective_from=date.today(),
    )
    _own(e, geo['town1'])
    return e


@pytest.fixture
def ase2(db, etype, manager, geo):
    e = Node.objects.create(
        entity_type=etype, name='ASE2', code='ASE2', parent=manager, effective_from=date.today(),
    )
    _own(e, geo['town2'])
    return e


def mk_txn(entity_id, **kw):
    """Create a transaction attributed to the geography leaf the org entity owns."""
    a = Assignment.objects.filter(assignee_id=entity_id, role_in_scope='owner', is_active=True).first()
    node_id = a.scope_id if a else entity_id
    defaults = dict(
        transaction_date=date(2026, 6, 10), transaction_type=Transaction.SALE,
        transaction_level=Transaction.SECONDARY, channel_code='GT',
        gross_amount=Decimal('0'), net_amount=Decimal('0'), quantity=Decimal('0'),
    )
    defaults.update(kw)
    return Transaction.objects.create(attributed_node_id=node_id, **defaults)


def mk_kpi(**kw):
    kw.setdefault('effective_from', date.today())
    kw.setdefault('code', 'K')
    kw.setdefault('name', 'K')
    return KPIDefinition.objects.create(**kw)


def compute(kpi, entity_id):
    return KPICalculator(kpi, PERIOD_START, PERIOD_END).compute_for_entity(entity_id)


# ── value + net logic ────────────────────────────────────────────────────────
def test_value_sales_minus_returns(ase1):
    mk_txn(ase1.id, net_amount=Decimal('1000'))
    mk_txn(ase1.id, net_amount=Decimal('2000'))
    mk_txn(ase1.id, net_amount=Decimal('3000'))
    mk_txn(ase1.id, transaction_type=Transaction.RETURN, net_amount=Decimal('500'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns',
    })
    assert compute(kpi, ase1.id) == Decimal('5500.00')


def test_value_gross_only_ignores_returns(ase1):
    mk_txn(ase1.id, net_amount=Decimal('1000'))
    mk_txn(ase1.id, net_amount=Decimal('2000'))
    mk_txn(ase1.id, net_amount=Decimal('3000'))
    mk_txn(ase1.id, transaction_type=Transaction.RETURN, net_amount=Decimal('500'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
    })
    assert compute(kpi, ase1.id) == Decimal('6000.00')


def test_zero_transactions(ase1):
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns',
    })
    assert compute(kpi, ase1.id) == Decimal('0.00')


# ── count / count_distinct ───────────────────────────────────────────────────
def test_count_distinct_outlets(ase1):
    mk_txn(ase1.id, outlet_code='OUT1', net_amount=Decimal('100'))
    mk_txn(ase1.id, outlet_code='OUT1', net_amount=Decimal('100'))
    mk_txn(ase1.id, outlet_code='OUT2', net_amount=Decimal('100'))
    kpi = mk_kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only',
    })
    assert compute(kpi, ase1.id) == Decimal('2')


def test_count_distinct_over_amount_field_is_rejected_not_crashed(ase1):
    # The builder used to carry measure_field across an aggregation switch, so a distinct count
    # could arrive naming a decimal column. Excluding '' on it raised decimal.InvalidOperation
    # (a 500 from preview). Now it fails validation, and the calculator degrades to a number.
    cfg = {'measure_field': 'net_amount', 'aggregation': 'count_distinct', 'net_logic': 'gross_only',
           'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}}
    errors = KPIService.validate_kpi_config(
        {'kpi_type': KPIDefinition.COUNT_DISTINCT, 'measure_config': cfg})
    assert any('count_distinct' in e for e in errors)

    mk_txn(ase1.id, outlet_code='OUT1', net_amount=Decimal('100'))
    kpi = mk_kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config=cfg)
    assert compute(kpi, ase1.id) == Decimal('1')


def test_count_rows(ase1):
    for _ in range(3):
        mk_txn(ase1.id, net_amount=Decimal('100'))
    mk_txn(ase1.id, transaction_type=Transaction.RETURN, net_amount=Decimal('100'))
    kpi = mk_kpi(kpi_type=KPIDefinition.COUNT, decimal_places=0, measure_config={
        'measure_field': 'id', 'aggregation': 'count', 'net_logic': 'gross_only',
    })
    assert compute(kpi, ase1.id) == Decimal('3')


# ── ratio ────────────────────────────────────────────────────────────────────
def test_ratio_drop_size(ase1):
    mk_txn(ase1.id, bill_ref='B1', net_amount=Decimal('1000'))
    mk_txn(ase1.id, bill_ref='B1', net_amount=Decimal('2000'))
    mk_txn(ase1.id, bill_ref='B2', net_amount=Decimal('3000'))
    mk_txn(ase1.id, bill_ref='B2', transaction_type=Transaction.RETURN, net_amount=Decimal('500'))
    kpi = mk_kpi(kpi_type=KPIDefinition.RATIO, decimal_places=2, ratio_config={
        'numerator': {'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
        'denominator': {'measure_field': 'bill_ref', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'},
    })
    # numerator = 6000 − 500 = 5500 ; denominator = 2 bills → 2750.00
    assert compute(kpi, ase1.id) == Decimal('2750.00')


# ── growth ───────────────────────────────────────────────────────────────────
def test_growth_vs_last_year(ase1):
    mk_txn(ase1.id, transaction_date=date(2026, 6, 15), net_amount=Decimal('6000'))
    mk_txn(ase1.id, transaction_date=date(2026, 6, 16),
           transaction_type=Transaction.RETURN, net_amount=Decimal('500'))  # current net = 5500
    mk_txn(ase1.id, transaction_date=date(2025, 6, 15), net_amount=Decimal('4000'))  # base = 4000
    kpi = mk_kpi(kpi_type=KPIDefinition.GROWTH, decimal_places=2, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns',
    }, growth_config={'basis': 'last_year_same_period', 'output': 'growth_pct'})
    # (5500 − 4000) / 4000 * 100 = 37.50
    assert compute(kpi, ase1.id) == Decimal('37.50')


# ── boolean ──────────────────────────────────────────────────────────────────
def test_boolean_threshold(ase1):
    for sku in ('S1', 'S2', 'S3', 'S4'):
        mk_txn(ase1.id, sku_code=sku, net_amount=Decimal('100'))
    met = mk_kpi(code='MSL_OK', kpi_type=KPIDefinition.BOOLEAN, decimal_places=0, measure_config={
        'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only',
    }, boolean_config={'operator': 'gte', 'threshold': 3})
    not_met = mk_kpi(code='MSL_NO', kpi_type=KPIDefinition.BOOLEAN, decimal_places=0, measure_config={
        'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only',
    }, boolean_config={'operator': 'gte', 'threshold': 5})
    assert compute(met, ase1.id) == Decimal('1')
    assert compute(not_met, ase1.id) == Decimal('0')


# ── composite ────────────────────────────────────────────────────────────────
def test_composite_expression(ase1):
    mk_txn(ase1.id, net_amount=Decimal('1000'))
    mk_txn(ase1.id, net_amount=Decimal('2000'))
    mk_txn(ase1.id, net_amount=Decimal('3000'))  # A = 6000, 3 rows → B = 3
    mk_kpi(code='A', kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
    })
    mk_kpi(code='B', kpi_type=KPIDefinition.COUNT, measure_config={
        'measure_field': 'id', 'aggregation': 'count', 'net_logic': 'gross_only',
    })
    comp = mk_kpi(code='C', kpi_type=KPIDefinition.COMPOSITE, decimal_places=2, composite_config={
        'expression': 'A + 10 * B', 'components': [{'kpi_code': 'A'}, {'kpi_code': 'B'}],
    })
    # 6000 + 10 * 3 = 6030.00
    assert compute(comp, ase1.id) == Decimal('6030.00')


# ── subtree rollup (the key correctness property) ────────────────────────────
def test_value_rolls_up_as_sum(manager, ase1, ase2):
    mk_txn(ase1.id, net_amount=Decimal('1000'))
    mk_txn(ase2.id, net_amount=Decimal('3000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
    })
    assert compute(kpi, ase1.id) == Decimal('1000.00')
    assert compute(kpi, ase2.id) == Decimal('3000.00')
    assert compute(kpi, manager.id) == Decimal('4000.00')  # subtree sum


def test_ratio_recomputed_at_each_level_not_averaged(manager, ase1, ase2):
    # ASE1: 1 sku, 1 bill → 1.0 ; ASE2: 2 skus, 2 bills → 1.0
    mk_txn(ase1.id, sku_code='S1', bill_ref='B1', net_amount=Decimal('100'))
    mk_txn(ase2.id, sku_code='S1', bill_ref='B2', net_amount=Decimal('100'))
    mk_txn(ase2.id, sku_code='S2', bill_ref='B3', net_amount=Decimal('100'))
    kpi = mk_kpi(kpi_type=KPIDefinition.RATIO, decimal_places=4, ratio_config={
        'numerator': {'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'},
        'denominator': {'measure_field': 'bill_ref', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'},
    })
    assert compute(kpi, ase1.id) == Decimal('1.0000')
    assert compute(kpi, ase2.id) == Decimal('1.0000')
    # Manager: distinct skus {S1,S2}=2 ÷ distinct bills {B1,B2,B3}=3 = 0.6667 — NOT the
    # average of the children's 1.0/1.0. This is the "recompute at each level" guarantee.
    assert compute(kpi, manager.id) == Decimal('0.6667')


# ── filters ──────────────────────────────────────────────────────────────────
def test_channel_filter_excludes(db, ase1):
    Channel.objects.create(name='Modern Trade', code='MT')
    mk_txn(ase1.id, channel_code='GT', net_amount=Decimal('1000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, channel_filter=['MT'], measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
    })
    assert compute(kpi, ase1.id) == Decimal('0.00')


def test_transaction_level_isolation(ase1):
    mk_txn(ase1.id, transaction_level=Transaction.SECONDARY, net_amount=Decimal('5000'))
    mk_txn(ase1.id, transaction_level=Transaction.PRIMARY, net_amount=Decimal('9000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
        'transaction_level': Transaction.PRIMARY,
    })
    assert compute(kpi, ase1.id) == Decimal('9000.00')


def test_effective_coverage_net_positive_per_outlet(ase1):
    # Outlet A nets +1000, B nets 0 (sale 500 − return 500), C nets +200.
    mk_txn(ase1.id, outlet_code='A', net_amount=Decimal('1000'))
    mk_txn(ase1.id, outlet_code='B', net_amount=Decimal('500'))
    mk_txn(ase1.id, outlet_code='B', transaction_type=Transaction.RETURN, net_amount=Decimal('500'))
    mk_txn(ase1.id, outlet_code='C', net_amount=Decimal('200'))
    ec = mk_kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'all',
        'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0},
    })
    # EC counts only A and C — B nets zero and is excluded.
    assert compute(ec, ase1.id) == Decimal('2')
    # A plain "outlets billed" (no having) would count all three.
    billed = mk_kpi(code='BILLED', kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only',
    })
    assert compute(billed, ase1.id) == Decimal('3')


def test_effective_coverage_rolls_up_subtree(manager, ase1, ase2):
    mk_txn(ase1.id, outlet_code='A', net_amount=Decimal('1000'))
    mk_txn(ase2.id, outlet_code='B', net_amount=Decimal('500'))
    mk_txn(ase2.id, outlet_code='B', transaction_type=Transaction.RETURN, net_amount=Decimal('500'))
    ec = mk_kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'all',
        'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0},
    })
    # Manager subtree: A nets +1000 (count), B nets 0 (skip) → 1.
    assert compute(ec, manager.id) == Decimal('1')


def test_sku_group_attribute_filter(db, ase1):
    from apps.master_data.models import SKU, SKUGroup
    SKU.objects.create(code='F1', name='Large pack', attributes={'pack_size': 'large'})
    SKU.objects.create(code='N1', name='Small pack', attributes={'pack_size': 'small'})
    SKUGroup.objects.create(code='LARGE', name='Large packs', filter_type=SKUGroup.FILTER_RULE,
                            filter_rules={'attributes': {'pack_size': 'large'}})
    mk_txn(ase1.id, sku_code='F1', net_amount=Decimal('1000'))
    mk_txn(ase1.id, sku_code='N1', net_amount=Decimal('4000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, sku_filter={'type': 'group', 'group_code': 'LARGE'},
                 measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert compute(kpi, ase1.id) == Decimal('1000.00')


def test_sku_group_filter(db, ase1):
    from apps.master_data.models import SKU, SKUGroup
    SKU.objects.create(code='F1', name='Focus', is_focus=True)
    SKU.objects.create(code='N1', name='Normal', is_focus=False)
    SKUGroup.objects.create(code='FOCUS', name='Focus', filter_type=SKUGroup.FILTER_RULE,
                            filter_rules={'is_focus': True})
    mk_txn(ase1.id, sku_code='F1', net_amount=Decimal('1000'))
    mk_txn(ase1.id, sku_code='N1', net_amount=Decimal('4000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, sku_filter={'type': 'group', 'group_code': 'FOCUS'},
                 measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert compute(kpi, ase1.id) == Decimal('1000.00')


# ── bulk ─────────────────────────────────────────────────────────────────────
def test_compute_bulk_leaves(manager, ase1, ase2):
    mk_txn(ase1.id, net_amount=Decimal('1000'))
    mk_txn(ase2.id, net_amount=Decimal('3000'))
    kpi = mk_kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
    })
    result = KPICalculator(kpi, PERIOD_START, PERIOD_END).compute_bulk([ase1.id, ase2.id])
    assert result == {ase1.id: Decimal('1000.00'), ase2.id: Decimal('3000.00')}
