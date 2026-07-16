"""Plan-run engines (P2) — pure math, exact Decimals, edge cases the AOP pipeline relies on."""
from decimal import Decimal

import pytest

from apps.targets import disaggregator, engines


def _sum(d):
    return sum(d.values(), Decimal('0'))


# ── blend_baselines ───────────────────────────────────────────────────────────
def test_baseline_blends_by_normalised_weights():
    per_basis = {
        'ly_same_period': {'A': Decimal('1000'), 'B': Decimal('2000')},
        'l3m_avg': {'A': Decimal('1500'), 'B': Decimal('1500')},
    }
    out = engines.blend_baselines(
        [{'basis': 'ly_same_period', 'weight': 60}, {'basis': 'l3m_avg', 'weight': 40}], per_basis)
    assert out['A'] == Decimal('1200')  # 1000×0.6 + 1500×0.4
    assert out['B'] == Decimal('1800')  # 2000×0.6 + 1500×0.4


def test_baseline_weight_scale_is_irrelevant():
    per_basis = {'x': {'A': Decimal('100')}, 'y': {'A': Decimal('200')}}
    a = engines.blend_baselines([{'basis': 'x', 'weight': 60}, {'basis': 'y', 'weight': 40}], per_basis)
    b = engines.blend_baselines([{'basis': 'x', 'weight': 3}, {'basis': 'y', 'weight': 2}], per_basis)
    assert a == b


def test_baseline_missing_node_in_one_basis_counts_zero():
    # A brand-new territory has L3M history but no LY — it still gets a base.
    per_basis = {'ly': {'A': Decimal('1000')}, 'l3m': {'A': Decimal('1000'), 'NEW': Decimal('500')}}
    out = engines.blend_baselines([{'basis': 'ly', 'weight': 50}, {'basis': 'l3m', 'weight': 50}], per_basis)
    assert out['NEW'] == Decimal('250')


def test_baseline_rejects_empty_or_zero_weights():
    with pytest.raises(ValueError):
        engines.blend_baselines([], {})
    with pytest.raises(ValueError):
        engines.blend_baselines([{'basis': 'x', 'weight': 0}], {'x': {'A': 1}})


# ── resolve_weights ───────────────────────────────────────────────────────────
def test_single_contribution_component_reproduces_history_shares():
    weights, explain = engines.resolve_weights(
        [{'source': 'contribution', 'weight': 100}],
        [{'A': '1000', 'B': '3000'}], ['A', 'B'])
    assert weights == {'A': Decimal('0.25'), 'B': Decimal('0.75')}
    assert explain['A']['components'][0]['share_pct'] == '25.00'


def test_blended_components_mix_shares_not_raw_magnitudes():
    # 70% contribution (₹) + 30% outlet count — scales differ wildly; shares must blend.
    weights, _ = engines.resolve_weights(
        [{'source': 'contribution', 'weight': 70},
         {'source': 'attribute', 'key': 'outlet_count', 'weight': 30}],
        [{'A': '9000000', 'B': '1000000'},   # contribution shares 0.9 / 0.1
         {'A': '100', 'B': '300'}],          # outlet shares 0.25 / 0.75
        ['A', 'B'])
    assert weights['A'] == Decimal('0.9') * Decimal('0.7') + Decimal('0.25') * Decimal('0.3')
    assert weights['B'] == Decimal('0.1') * Decimal('0.7') + Decimal('0.75') * Decimal('0.3')
    assert _sum(weights) == Decimal('1')


def test_zero_history_child_earns_share_from_other_components():
    # The NPI/new-territory case: no history, but outlets exist → the attribute component pays.
    weights, _ = engines.resolve_weights(
        [{'source': 'contribution', 'weight': 50},
         {'source': 'attribute', 'key': 'outlet_count', 'weight': 50}],
        [{'A': '1000', 'NEW': '0'}, {'A': '100', 'NEW': '100'}],
        ['A', 'NEW'])
    assert weights['NEW'] == Decimal('0.25')  # 0×0.5 + 0.5×0.5


def test_no_signal_component_degrades_to_equal_and_is_flagged():
    weights, explain = engines.resolve_weights(
        [{'source': 'attribute', 'key': 'market_index', 'weight': 100}],
        [{'A': '0', 'B': '0'}], ['A', 'B'])
    assert weights == {'A': Decimal('0.5'), 'B': Decimal('0.5')}
    assert explain['A']['components'][0]['no_signal'] is True


def test_equal_component_needs_no_input():
    weights, _ = engines.resolve_weights([{'source': 'equal'}], [None], ['A', 'B', 'C', 'D'])
    assert weights == {k: Decimal('0.25') for k in 'ABCD'}


def test_explain_is_json_safe(tmp_path):
    import json
    _, explain = engines.resolve_weights(
        [{'source': 'contribution', 'weight': 70}, {'source': 'equal', 'weight': 30}],
        [{'A': '1', 'B': '3'}, None], ['A', 'B'])
    json.dumps(explain)  # must not raise — lands in RunAllocation.explain as-is
    assert explain['B']['components'][0]['weight_pct'] == '70.00'


def test_resolve_weights_validates_shape():
    with pytest.raises(ValueError):
        engines.resolve_weights([], [], ['A'])
    with pytest.raises(ValueError):
        engines.resolve_weights([{'source': 'equal'}], [], ['A'])  # inputs not parallel


# ── apply_growth ──────────────────────────────────────────────────────────────
def test_uniform_growth_does_not_change_the_split():
    weights = {'A': Decimal('0.5'), 'B': Decimal('0.5')}
    tilted = engines.apply_growth(weights, {'A': 12, 'B': 12})
    out = disaggregator.split_by_weights(Decimal('1000'), list(tilted.items()), unit=1)
    assert out == {'A': Decimal('500'), 'B': Decimal('500')}


def test_differential_growth_tilts_the_split():
    weights = {'A': Decimal('0.5'), 'B': Decimal('0.5')}
    tilted = engines.apply_growth(weights, {'A': 0, 'B': 100})  # push B twice as hard
    out = disaggregator.split_by_weights(Decimal('3000'), list(tilted.items()), unit=1)
    assert out == {'A': Decimal('1000'), 'B': Decimal('2000')}


def test_growth_below_minus_100_clamps_to_zero():
    tilted = engines.apply_growth({'A': Decimal('0.5')}, {'A': -150})
    assert tilted['A'] == Decimal('0')


# ── split_product_mix ─────────────────────────────────────────────────────────
def test_history_mix_reproduces_local_shares_exactly():
    out = engines.split_product_mix(
        Decimal('10000'), ['CORE', 'FOCUS'], {'CORE': '6000', 'FOCUS': '2000'}, unit=1)
    assert out == {'CORE': Decimal('7500'), 'FOCUS': Decimal('2500')}
    assert _sum(out) == Decimal('10000')


def test_fixed_npi_seeding_comes_off_the_top():
    # NPI has no history; force it 8% and split the rest by local mix.
    out = engines.split_product_mix(
        Decimal('10000'), ['CORE', 'FOCUS', 'NPI'],
        {'CORE': '3000', 'FOCUS': '1000'}, fixed_mix={'NPI': 8}, unit=1)
    assert out['NPI'] == Decimal('800')
    assert out['CORE'] == Decimal('6900')   # 75% of the remaining 9200
    assert out['FOCUS'] == Decimal('2300')  # 25% of the remaining 9200
    assert _sum(out) == Decimal('10000')


def test_fully_fixed_mix_reconciles_on_last_group():
    out = engines.split_product_mix(
        Decimal('10001'), ['A', 'B'], {}, fixed_mix={'A': 50, 'B': 50}, unit=1)
    assert _sum(out) == Decimal('10001')
    assert out['A'] == Decimal('5001') or out['B'] != Decimal('5001')  # remainder went to B
    assert out['B'] == Decimal('10001') - out['A']


def test_no_history_at_all_splits_remainder_equally():
    out = engines.split_product_mix(Decimal('900'), ['A', 'B', 'C'], {}, unit=1)
    assert out == {'A': Decimal('300'), 'B': Decimal('300'), 'C': Decimal('300')}


def test_fixed_mix_validation():
    with pytest.raises(ValueError, match='more than 100'):
        engines.split_product_mix(1000, ['A', 'B'], {}, fixed_mix={'A': 60, 'B': 60})
    with pytest.raises(ValueError, match='outside the plan scope'):
        engines.split_product_mix(1000, ['A'], {}, fixed_mix={'ZZZ': 10})
    with pytest.raises(ValueError):
        engines.split_product_mix(1000, [], {})


def test_product_mix_reconciliation_invariant():
    for total in (Decimal('123456.7890'), Decimal('1'), Decimal('0')):
        out = engines.split_product_mix(
            total, ['A', 'B', 'C'], {'A': '7', 'B': '3'}, fixed_mix={'C': 13},
            unit=Decimal('0.01'))
        assert _sum(out) == total
