"""Exhaustive calculation revalidation — every KPI type, net-logic, filter and engine
entry point, with exact Decimal expectations derived by hand.

Complements test_calculator.py (which covers the common paths) by sweeping the whole
surface: all 8 kpi_types, all 4 net_logics, all 5 boolean operators, all 4 external
aggregations, every filter, and — critically — **cross-path agreement**: for the same
KPI + entity, ``compute_for_entity``, ``compute_bulk`` and ``compute_for_subtrees`` must
return the same number. A disagreement between paths is always a bug (it shipped one:
distinct counts were folded by sum across geography nodes).

Same two-tree fixture shape as test_calculator.py: ASM owns REGION, ASE1/ASE2 own TOWN1/TOWN2.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import (
    ExternalMetric, ExternalMetricValue, KPIDefinition, Transaction,
)
from apps.master_data.models import SKU, SKUGroup

START, END = date(2026, 6, 1), date(2026, 6, 30)
_FROM = date(2025, 1, 1)


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def etype(db):
    return NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    t1 = GeographyNode.objects.create(geography_type=gt, name='Town1', code='TOWN1', level='town', parent=region)
    t2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town', parent=region)
    return {'region': region, 'town1': t1, 'town2': t2}


def _own(entity, node):
    AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=_FROM)


@pytest.fixture
def tree(db, etype, geo):
    m = Node.objects.create(entity_type=etype, name='ASM', code='ASM1', effective_from=date.today())
    _own(m, geo['region'])
    a1 = Node.objects.create(entity_type=etype, name='ASE1', code='ASE1', parent=m, effective_from=date.today())
    _own(a1, geo['town1'])
    a2 = Node.objects.create(entity_type=etype, name='ASE2', code='ASE2', parent=m, effective_from=date.today())
    _own(a2, geo['town2'])
    return {'mgr': m, 'a1': a1, 'a2': a2, **geo}


def txn(node, **kw):
    d = dict(transaction_date=date(2026, 6, 10), transaction_type=Transaction.SALE,
             transaction_level=Transaction.SECONDARY, channel_code='GT',
             gross_amount=Decimal('0'), net_amount=Decimal('0'), quantity=Decimal('0'))
    d.update(kw)
    return Transaction.objects.create(attributed_node_id=node.id, **d)


def kpi(**kw):
    kw.setdefault('effective_from', date.today())
    kw.setdefault('code', 'K')
    kw.setdefault('name', 'K')
    return KPIDefinition.objects.create(**kw)


def calc(k):
    return KPICalculator(k, START, END)


# ═════════════════════════════════════════════════════════════════════════════
# A. VALUE × every net_logic
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize('net_logic,expected', [
    ('gross_only', '1000'),            # sales only
    ('returns_only', '300'),           # returns only
    ('sales_minus_returns', '700'),    # 1000 - 300
    ('all', '1300'),                   # unsigned sum of every row
])
def test_value_all_net_logics(tree, net_logic, expected):
    txn(tree['town1'], net_amount=Decimal('1000'))
    txn(tree['town1'], net_amount=Decimal('300'), transaction_type=Transaction.RETURN)
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': net_logic})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(expected + '.00')


def test_value_sums_gross_and_quantity_fields(tree):
    txn(tree['town1'], net_amount=Decimal('100'), gross_amount=Decimal('120'), quantity=Decimal('7'))
    for field, exp in [('gross_amount', '120.00'), ('quantity', '7.00'), ('net_amount', '100.00')]:
        k = kpi(code=f'K_{field}', kpi_type=KPIDefinition.VALUE, measure_config={
            'measure_field': field, 'aggregation': 'sum', 'net_logic': 'gross_only'})
        assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(exp)


# ═════════════════════════════════════════════════════════════════════════════
# B. COUNT / COUNT_DISTINCT incl. the `having` boundary
# ═════════════════════════════════════════════════════════════════════════════
def test_count_counts_rows_not_values(tree):
    for _ in range(3):
        txn(tree['town1'], net_amount=Decimal('10'))
    k = kpi(kpi_type=KPIDefinition.COUNT, decimal_places=0, measure_config={
        'aggregation': 'count', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('3')


def test_count_distinct_ignores_blank_keys(tree):
    txn(tree['town1'], outlet_code='A', net_amount=Decimal('10'))
    txn(tree['town1'], outlet_code='', net_amount=Decimal('10'))   # blank must not count
    k = kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('1')


@pytest.mark.parametrize('sale,ret,expected', [
    ('100', '0', '1'),      # clearly positive → counts
    ('100', '99', '1'),      # net +1 → counts
    ('100', '100', '0'),     # net exactly 0 → excluded (operator is >)
    ('100', '150', '0'),     # net negative → excluded
])
def test_effective_coverage_having_boundary(tree, sale, ret, expected):
    """EC counts outlets whose NET clears the threshold — the returns>sales exclusion."""
    txn(tree['town1'], outlet_code='O1', net_amount=Decimal(sale))
    if ret != '0':
        txn(tree['town1'], outlet_code='O1', net_amount=Decimal(ret), transaction_type=Transaction.RETURN)
    k = kpi(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'all',
        'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(expected)


# ═════════════════════════════════════════════════════════════════════════════
# C. RATIO / GROWTH / BOOLEAN — including the divide-by-zero guards
# ═════════════════════════════════════════════════════════════════════════════
def test_ratio_and_zero_denominator(tree):
    txn(tree['town1'], sku_code='S1', bill_ref='B1', net_amount=Decimal('100'))
    txn(tree['town1'], sku_code='S2', bill_ref='B1', net_amount=Decimal('100'))
    k = kpi(kpi_type=KPIDefinition.RATIO, decimal_places=4, ratio_config={
        'numerator': {'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'},
        'denominator': {'measure_field': 'bill_ref', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'}})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('2.0000')   # 2 skus / 1 bill
    # No rows for ASE2 → denominator 0 → guarded to 0, never ZeroDivisionError
    assert calc(k).compute_for_entity(tree['a2'].id) == Decimal('0.0000')


@pytest.mark.parametrize('output,expected', [
    ('growth_pct', '50.00'),        # (150-100)/100*100
    ('growth_absolute', '50.00'),   # 150-100
    ('index', '150.00'),            # 150/100*100
])
def test_growth_outputs(tree, output, expected):
    txn(tree['town1'], net_amount=Decimal('150'))                                  # current June
    txn(tree['town1'], net_amount=Decimal('100'), transaction_date=date(2025, 6, 10))  # LY June
    k = kpi(kpi_type=KPIDefinition.GROWTH, decimal_places=2,
            measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'},
            growth_config={'basis': 'last_year_same_period', 'output': output})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(expected)


def test_growth_with_zero_base_is_zero_not_infinite(tree):
    txn(tree['town1'], net_amount=Decimal('500'))   # current only, no last-year row
    k = kpi(kpi_type=KPIDefinition.GROWTH, decimal_places=2,
            measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'},
            growth_config={'basis': 'last_year_same_period', 'output': 'growth_pct'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('0.00')


@pytest.mark.parametrize('op,threshold,expected', [
    ('gte', '100', '1'),   # 100 >= 100 → met (boundary)
    ('gt', '100', '0'),    # 100 > 100  → not met (boundary)
    ('lte', '100', '1'),
    ('lt', '100', '0'),
    ('eq', '100', '1'),
    ('gte', '101', '0'),
])
def test_boolean_all_operators_at_the_boundary(tree, op, threshold, expected):
    txn(tree['town1'], net_amount=Decimal('100'))
    k = kpi(kpi_type=KPIDefinition.BOOLEAN, decimal_places=0,
            measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'},
            boolean_config={'operator': op, 'threshold': threshold})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(expected)


# ═════════════════════════════════════════════════════════════════════════════
# D. COMPOSITE + EXTERNAL
# ═════════════════════════════════════════════════════════════════════════════
def test_composite_weights_component_kpis(tree):
    txn(tree['town1'], net_amount=Decimal('1000'))
    kpi(code='A_VAL', name='A', kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    comp = kpi(code='COMP', name='Comp', kpi_type=KPIDefinition.COMPOSITE, decimal_places=2,
               composite_config={'components': [{'kpi_code': 'A_VAL'}], 'expression': '0.6 * A_VAL'})
    assert calc(comp).compute_for_entity(tree['a1'].id) == Decimal('600.00')


def test_composite_missing_component_is_zero_not_error(tree):
    comp = kpi(code='COMP2', name='Comp2', kpi_type=KPIDefinition.COMPOSITE, decimal_places=2,
               composite_config={'components': [{'kpi_code': 'NOPE'}], 'expression': 'NOPE + 5'})
    assert calc(comp).compute_for_entity(tree['a1'].id) == Decimal('5.00')


@pytest.mark.parametrize('agg,expected', [
    ('sum', '30.00'), ('avg', '15.00'), ('max', '20.00'), ('latest', '20.00'),
])
def test_external_metric_aggregations(tree, agg, expected):
    m = ExternalMetric.objects.create(code='TLSD', name='TLSD', granularity=ExternalMetric.GEOGRAPHY_NODE,
                                      default_aggregation=ExternalMetric.SUM)
    ExternalMetricValue.objects.create(metric=m, node_id=tree['town1'].id,
                                       measured_on=date(2026, 6, 5), value=Decimal('10'))
    ExternalMetricValue.objects.create(metric=m, node_id=tree['town1'].id,
                                       measured_on=date(2026, 6, 20), value=Decimal('20'))
    k = kpi(kpi_type=KPIDefinition.EXTERNAL, decimal_places=2,
            external_config={'metric_code': 'TLSD', 'aggregation': agg})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal(expected)


def test_person_grain_external_metric_never_rolls_up_to_a_manager(tree):
    """A person-grain score (RCPA %) is that person's own number; averaging it up a
    manager is not a business figure, so a manager reads 0 unless they have own rows."""
    m = ExternalMetric.objects.create(code='RCPA', name='RCPA', granularity=ExternalMetric.ENTITY,
                                      default_aggregation=ExternalMetric.SUM)
    ExternalMetricValue.objects.create(metric=m, entity_id=tree['a1'].id,
                                       measured_on=date(2026, 6, 5), value=Decimal('42'))
    k = kpi(kpi_type=KPIDefinition.EXTERNAL, decimal_places=2,
            external_config={'metric_code': 'RCPA', 'aggregation': 'sum'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('42.00')
    assert calc(k).compute_for_entity(tree['mgr'].id) == Decimal('0.00')


# ═════════════════════════════════════════════════════════════════════════════
# E. Filters
# ═════════════════════════════════════════════════════════════════════════════
def test_transaction_level_and_source_filters(tree):
    txn(tree['town1'], net_amount=Decimal('100'), transaction_level=Transaction.SECONDARY, source='dms_sync')
    txn(tree['town1'], net_amount=Decimal('900'), transaction_level=Transaction.PRIMARY, source='api_push')
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
        'transaction_level': 'secondary'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('100.00')
    k2 = kpi(code='K2', kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only',
        'source_filter': ['api_push']})
    assert calc(k2).compute_for_entity(tree['a1'].id) == Decimal('900.00')


def test_sku_group_filter_restricts_to_group_members(tree):
    Channel.objects.create(name='GT', code='GT')
    SKU.objects.create(code='F1', name='Focus1', is_focus=True)
    SKU.objects.create(code='N1', name='Normal1', is_focus=False)
    g = SKUGroup.objects.create(code='FOCUS', name='Focus', filter_type=SKUGroup.FILTER_RULE,
                                filter_rules={'is_focus': True})
    txn(tree['town1'], sku_code='F1', net_amount=Decimal('100'))
    txn(tree['town1'], sku_code='N1', net_amount=Decimal('900'))
    k = kpi(kpi_type=KPIDefinition.VALUE, sku_filter={'type': 'group', 'group_code': g.code},
            measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('100.00')


def test_date_window_excludes_rows_outside_the_period(tree):
    txn(tree['town1'], net_amount=Decimal('100'), transaction_date=date(2026, 5, 31))  # before
    txn(tree['town1'], net_amount=Decimal('200'), transaction_date=date(2026, 6, 1))   # first day
    txn(tree['town1'], net_amount=Decimal('400'), transaction_date=date(2026, 6, 30))  # last day
    txn(tree['town1'], net_amount=Decimal('800'), transaction_date=date(2026, 7, 1))   # after
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('600.00')  # inclusive both ends


def test_inactive_transactions_are_ignored(tree):
    txn(tree['town1'], net_amount=Decimal('100'))
    txn(tree['town1'], net_amount=Decimal('900'), is_active=False)
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(tree['a1'].id) == Decimal('100.00')


# ═════════════════════════════════════════════════════════════════════════════
# F. CROSS-PATH AGREEMENT — the invariant that caught the distinct-count bug
# ═════════════════════════════════════════════════════════════════════════════
def _all_kpi_shapes():
    return [
        ('value', dict(kpi_type=KPIDefinition.VALUE, measure_config={
            'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'})),
        ('count', dict(kpi_type=KPIDefinition.COUNT, decimal_places=0, measure_config={
            'aggregation': 'count', 'net_logic': 'gross_only'})),
        ('count_distinct_sku', dict(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
            'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'})),
        ('count_distinct_outlet', dict(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
            'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'})),
        ('ec_having', dict(kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
            'measure_field': 'outlet_code', 'aggregation': 'count_distinct', 'net_logic': 'all',
            'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}})),
        ('ratio', dict(kpi_type=KPIDefinition.RATIO, decimal_places=4, ratio_config={
            'numerator': {'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'},
            'denominator': {'measure_field': 'bill_ref', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'}})),
    ]


@pytest.mark.parametrize('label,cfg', _all_kpi_shapes())
def test_every_engine_path_agrees_for_the_same_kpi_and_entity(tree, label, cfg):
    """compute_for_entity / compute_bulk / compute_for_subtrees must return the same
    number. The two towns deliberately SHARE sku and outlet codes so any additive fold
    of a distinct count double-counts and is caught here."""
    txn(tree['town1'], sku_code='S1', outlet_code='O1', bill_ref='B1', net_amount=Decimal('100'))
    txn(tree['town2'], sku_code='S1', outlet_code='O1', bill_ref='B2', net_amount=Decimal('300'))
    txn(tree['town2'], sku_code='S2', outlet_code='O2', bill_ref='B2', net_amount=Decimal('50'),
        transaction_type=Transaction.RETURN)
    k = kpi(code=f'X_{label}', name=label, **cfg)
    c = calc(k)
    mgr = tree['mgr'].id
    single = c.compute_for_entity(mgr)
    bulk = c.compute_bulk([mgr])[mgr]
    nodes = AssignmentService.scope_node_ids_for_entity(mgr, on=END)
    subtree = c.compute_for_subtrees({mgr: nodes})[mgr]
    assert single == bulk, f'{label}: compute_for_entity {single} != compute_bulk {bulk}'
    assert single == subtree, f'{label}: compute_for_entity {single} != compute_for_subtrees {subtree}'


@pytest.mark.parametrize('label,cfg', _all_kpi_shapes())
def test_node_axis_matches_entity_axis_for_the_same_territory(tree, label, cfg):
    """compute_bulk_for_nodes over the region must equal the manager's value — the org
    axis and the geography axis measure the same territory."""
    txn(tree['town1'], sku_code='S1', outlet_code='O1', bill_ref='B1', net_amount=Decimal('100'))
    txn(tree['town2'], sku_code='S1', outlet_code='O1', bill_ref='B2', net_amount=Decimal('300'))
    k = kpi(code=f'Y_{label}', name=label, **cfg)
    c = calc(k)
    by_entity = c.compute_for_entity(tree['mgr'].id)
    by_node = c.compute_bulk_for_nodes([tree['region'].id])[tree['region'].id]
    assert by_entity == by_node, f'{label}: entity {by_entity} != node {by_node}'


def test_subtree_value_equals_sum_of_children_for_additive_kpis_only(tree):
    """VALUE folds by sum; a distinct count does not (shared codes across towns)."""
    txn(tree['town1'], sku_code='S1', net_amount=Decimal('100'))
    txn(tree['town2'], sku_code='S1', net_amount=Decimal('300'))
    val = kpi(code='V', kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    c = calc(val)
    assert c.compute_for_entity(tree['mgr'].id) == Decimal('400.00')          # additive
    dist = kpi(code='D', kpi_type=KPIDefinition.COUNT_DISTINCT, decimal_places=0, measure_config={
        'measure_field': 'sku_code', 'aggregation': 'count_distinct', 'net_logic': 'gross_only'})
    cd = calc(dist)
    assert cd.compute_for_entity(tree['a1'].id) == Decimal('1')
    assert cd.compute_for_entity(tree['a2'].id) == Decimal('1')
    assert cd.compute_for_entity(tree['mgr'].id) == Decimal('1')              # NOT 1+1


# ═════════════════════════════════════════════════════════════════════════════
# G. Ownership / attribution boundaries
# ═════════════════════════════════════════════════════════════════════════════
def test_entity_owning_no_territory_reads_zero(tree, etype):
    txn(tree['town1'], net_amount=Decimal('100'))
    orphan = Node.objects.create(entity_type=etype, name='Orphan', code='ORP', effective_from=date.today())
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    assert calc(k).compute_for_entity(orphan.id) == Decimal('0.00')


def test_sales_are_scoped_to_the_owned_territory_only(tree):
    txn(tree['town1'], net_amount=Decimal('100'))
    txn(tree['town2'], net_amount=Decimal('900'))
    k = kpi(kpi_type=KPIDefinition.VALUE, measure_config={
        'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'gross_only'})
    c = calc(k)
    assert c.compute_for_entity(tree['a1'].id) == Decimal('100.00')   # own town only
    assert c.compute_for_entity(tree['a2'].id) == Decimal('900.00')
    assert c.compute_for_entity(tree['mgr'].id) == Decimal('1000.00')  # both
