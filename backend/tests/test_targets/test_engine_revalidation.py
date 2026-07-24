"""Exhaustive revalidation of the pure calculation engines — no ORM, no I/O.

Covers period math, the disaggregator's exact-sum invariant (property-based over
randomised inputs), the plan-run engines, and the payout engine end to end including
gates, exceptions, caps and money rounding.
"""
import random
from datetime import date
from decimal import Decimal

import pytest

from apps.kpi_engine import periods
from apps.targets import disaggregator as dis
from apps.targets import engines
from apps.incentives import payout_engine as pe

D = Decimal


# ═════════════════════════════════════════════════════════════════════════════
# 1. Period math
# ═════════════════════════════════════════════════════════════════════════════
def test_working_days_excludes_sundays_only_by_default():
    # June 2026: 1st is a Monday; 30 days, 4 Sundays (7,14,21,28) → 26 working days.
    assert periods.working_days_between(date(2026, 6, 1), date(2026, 6, 30)) == 26


def test_working_days_is_inclusive_of_both_ends_and_zero_when_reversed():
    assert periods.working_days_between(date(2026, 6, 1), date(2026, 6, 1)) == 1   # Monday
    assert periods.working_days_between(date(2026, 6, 7), date(2026, 6, 7)) == 0   # Sunday
    assert periods.working_days_between(date(2026, 6, 30), date(2026, 6, 1)) == 0  # reversed


def test_working_days_respects_a_custom_week_off():
    # Excluding Sat+Sun from a full week leaves 5.
    assert periods.working_days_between(date(2026, 6, 1), date(2026, 6, 7), week_off=(5, 6)) == 5


@pytest.mark.parametrize('elapsed,total,value,expected', [
    (13, 26, '1000', '2000'),   # half the month elapsed → double
    (26, 26, '1000', '1000'),   # fully elapsed → unchanged
    (0, 26, '1000', '1000'),    # nothing elapsed → unchanged, never a divide-by-zero
    (1, 26, '100', '2600'),
])
def test_project_full_period(elapsed, total, value, expected):
    assert periods.project_full_period(D(value), elapsed, total) == D(expected)


def test_last_year_same_period_shifts_exactly_twelve_months():
    assert periods.resolve_comparison_window(
        date(2026, 6, 1), date(2026, 6, 30), periods.LAST_YEAR_SAME_PERIOD,
    ) == (date(2025, 6, 1), date(2025, 6, 30))


def test_month_shift_clamps_to_shorter_months():
    # Mar 31 − 1 month must land on Feb 28 (2026 is not a leap year), not error.
    start, end = periods.resolve_comparison_window(
        date(2026, 3, 31), date(2026, 3, 31), periods.PREVIOUS_MONTH,
    )
    assert (start, end) == (date(2026, 2, 28), date(2026, 2, 28))


def test_previous_period_uses_the_same_window_length():
    # A 30-day window → the 30 days immediately before it.
    assert periods.resolve_comparison_window(
        date(2026, 6, 1), date(2026, 6, 30), periods.PREVIOUS_PERIOD,
    ) == (date(2026, 5, 2), date(2026, 5, 31))


def test_unknown_basis_and_missing_offset_raise():
    with pytest.raises(ValueError):
        periods.resolve_comparison_window(date(2026, 6, 1), date(2026, 6, 30), 'nonsense')
    with pytest.raises(ValueError):
        periods.resolve_comparison_window(
            date(2026, 6, 1), date(2026, 6, 30), periods.CUSTOM_MONTH_OFFSET, offset=0)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Disaggregator — the parts must sum to the whole, always
# ═════════════════════════════════════════════════════════════════════════════
def test_split_is_proportional_to_weight():
    out = dis.split_by_weights(D('1000'), [('a', D('3')), ('b', D('1'))])
    assert out == {'a': D('750'), 'b': D('250')}


def test_split_with_no_signal_falls_back_to_equal_shares():
    out = dis.split_by_weights(D('900'), [('a', D('0')), ('b', D('0')), ('c', D('0'))])
    assert out == {'a': D('300'), 'b': D('300'), 'c': D('300')}


@pytest.mark.parametrize('unit,total', [
    (None, '1000'), (D('1'), '1000'), (D('100'), '1000'), (D('1000'), '100000'),
])
def test_rounding_unit_never_leaks_a_rupee(unit, total):
    parts = [(f'n{i}', D(str(i + 1))) for i in range(7)]
    out = dis.split_by_weights(D(total), parts, unit=unit)
    assert sum(out.values()) == D(total)


def test_split_exact_sum_property_over_randomised_inputs():
    """1000 randomised splits: every one reconciles to the rupee."""
    rnd = random.Random(20260724)
    for _ in range(1000):
        total = D(str(rnd.randint(1, 10_000_000)))
        n = rnd.randint(1, 15)
        parts = [(f'c{i}', D(str(rnd.randint(0, 5000)))) for i in range(n)]
        unit = rnd.choice([None, D('1'), D('10'), D('100'), D('1000')])
        out = dis.split_by_weights(total, parts, unit=unit)
        assert sum(out.values()) == total, (total, n, unit)
        assert len(out) == n


def test_split_edge_cases():
    assert dis.split_by_weights(D('100'), []) == {}
    assert dis.split_by_weights(D('123.45'), [('only', D('9'))]) == {'only': D('123.45')}
    # A zero total still distributes zeros and reconciles.
    out = dis.split_by_weights(D('0'), [('a', D('5')), ('b', D('5'))])
    assert sum(out.values()) == D('0')


def test_constraints_clamp_growth_yet_still_reconcile():
    """A child capped at +40% growth cannot exceed base×1.4; the freed amount moves to
    the others and the total is preserved."""
    bases = {'a': D('100'), 'b': D('100')}
    raw = {'a': D('300'), 'b': D('100')}          # 'a' would be +200% growth
    out = engines_apply(raw, ['a', 'b'], bases, {'max_growth_pct': D('40')}, D('400'))
    assert out['a'] == D('140')                    # clamped to 100 × 1.4
    assert sum(out.values()) == D('400')           # remainder absorbed by the last free part


def engines_apply(split, order, bases, constraints, total, unit=None):
    return dis.apply_constraints(split, order, bases, constraints, total, unit=unit)


def test_constraints_property_always_reconcile():
    rnd = random.Random(4242)
    for _ in range(300):
        keys = [f'n{i}' for i in range(rnd.randint(2, 8))]
        total = D(str(rnd.randint(1000, 5_000_000)))
        bases = {k: D(str(rnd.randint(1, 200_000))) for k in keys}
        raw = dis.split_by_weights(total, [(k, bases[k]) for k in keys], unit=D('1'))
        cons = {'max_growth_pct': D('40'), 'min_growth_pct': D('-20')}
        out = dis.apply_constraints(raw, keys, bases, cons, total, unit=D('1'))
        assert sum(out.values()) == total


# ═════════════════════════════════════════════════════════════════════════════
# 3. Plan-run engines
# ═════════════════════════════════════════════════════════════════════════════
def test_blend_baselines_normalises_weights():
    per_basis = {'ly': {'n1': D('100')}, 'l3m': {'n1': D('200')}}
    comps = [{'basis': 'ly', 'weight': 60}, {'basis': 'l3m', 'weight': 40}]
    assert engines.blend_baselines(comps, per_basis)['n1'] == D('140')   # 100×.6 + 200×.4
    # 3:2 is the same ratio as 60:40
    comps2 = [{'basis': 'ly', 'weight': 3}, {'basis': 'l3m', 'weight': 2}]
    assert engines.blend_baselines(comps2, per_basis)['n1'] == D('140')


def test_blend_baselines_treats_a_missing_basis_as_zero():
    per_basis = {'ly': {'n1': D('100')}, 'l3m': {}}          # no L3M history for n1
    comps = [{'basis': 'ly', 'weight': 50}, {'basis': 'l3m', 'weight': 50}]
    assert engines.blend_baselines(comps, per_basis)['n1'] == D('50')


def test_blend_baselines_rejects_empty_or_zero_weights():
    with pytest.raises(ValueError):
        engines.blend_baselines([], {})
    with pytest.raises(ValueError):
        engines.blend_baselines([{'basis': 'ly', 'weight': 0}], {'ly': {'n': D('1')}})


def test_apply_growth_tilts_and_clamps_at_minus_100():
    weights = {'a': D('100'), 'b': D('100'), 'c': D('100')}
    out = engines.apply_growth(weights, {'a': D('10'), 'b': D('-150')})
    assert out['a'] == D('110')      # +10%
    assert out['b'] == D('0')        # below -100% clamps to 0, never negative
    assert out['c'] == D('100')      # missing key = no tilt


def test_product_mix_takes_fixed_share_off_the_top_then_splits_the_rest():
    out = engines.split_product_mix(
        D('1000'), ['NPI', 'CORE', 'FOCUS'],
        history={'CORE': D('300'), 'FOCUS': D('100')},
        fixed_mix={'NPI': D('20')})
    assert out['NPI'] == D('200')                       # 20% off the top
    assert out['CORE'] + out['FOCUS'] == D('800')       # remainder on local mix 3:1
    assert out['CORE'] == D('600')
    assert sum(out.values()) == D('1000')


def test_product_mix_with_no_history_splits_the_remainder_equally():
    out = engines.split_product_mix(D('900'), ['A', 'B', 'C'], history={})
    assert sum(out.values()) == D('900')
    assert out['A'] == out['B'] == D('300')


def test_product_mix_rejects_impossible_fixed_mix():
    with pytest.raises(ValueError):
        engines.split_product_mix(D('100'), ['A'], history={}, fixed_mix={'B': D('10')})
    with pytest.raises(ValueError):
        engines.split_product_mix(D('100'), ['A', 'B'], history={},
                                  fixed_mix={'A': D('60'), 'B': D('60')})
    with pytest.raises(ValueError):
        engines.split_product_mix(D('100'), [], history={})


# ═════════════════════════════════════════════════════════════════════════════
# 4. Payout engine
# ═════════════════════════════════════════════════════════════════════════════
RFP_TIERS = (
    pe.TierInput(D('0'), D('90'), D('0.0')),
    pe.TierInput(D('90'), D('100'), D('0.9')),
    pe.TierInput(D('100'), D('102'), D('1.0')),
    pe.TierInput(D('102'), D('105'), D('1.5')),
    pe.TierInput(D('105'), None, D('1.8')),
)


@pytest.mark.parametrize('pct,expected', [
    ('0', '0.0'), ('89.99', '0.0'), ('90', '0.9'), ('99.99', '0.9'),
    ('100', '1.0'), ('101.99', '1.0'), ('102', '1.5'), ('104.99', '1.5'),
    ('105', '1.8'), ('1000', '1.8'),
])
def test_tier_boundaries_are_min_inclusive_max_exclusive(pct, expected):
    assert pe.match_tier(RFP_TIERS, D(pct)).multiplier == D(expected)


def test_tier_validation_catches_gaps_overlaps_and_unbounded_middles():
    assert pe.validate_tiers(RFP_TIERS) == []
    assert pe.validate_tiers(()) == ['At least one tier is required.']
    # does not start at 0
    bad = (pe.TierInput(D('10'), None, D('1')),)
    assert any('start at 0' in e for e in pe.validate_tiers(bad))
    # gap between tiers
    gap = (pe.TierInput(D('0'), D('90'), D('0')), pe.TierInput(D('95'), None, D('1')))
    assert any('contiguous' in e for e in pe.validate_tiers(gap))
    # a middle tier left unbounded
    mid = (pe.TierInput(D('0'), None, D('0')), pe.TierInput(D('90'), None, D('1')))
    assert any('only the last tier' in e.lower() for e in pe.validate_tiers(mid))
    # negative multiplier
    neg = (pe.TierInput(D('0'), None, D('-1')),)
    assert any('negative' in e for e in pe.validate_tiers(neg))


def _scheme(**kw):
    base = dict(code='S', vp_basis_pct=D('100'), overall_cap_pct=None, gates=(),
                gatekeeper_action=pe.ACTION_ZERO_PAYOUT,
                kpis=(pe.SchemeKPIInput('K1', 'sales', D('100'), None, None, RFP_TIERS),))
    base.update(kw)
    return pe.SchemeInput(**base)


def _node(ach_pct, vp=D('10000'), eligible_days=None, wd=26, exception=None):
    return pe.NodeInput(
        entity_id=1, variable_pay=vp, eligible_working_days=eligible_days,
        period_working_days=wd,
        achievements={'K1': pe.AchievementInput(D(str(ach_pct)), D('100'), D('100')),
                      'GATE': pe.AchievementInput(D(str(ach_pct)), D('100'), D('100'))},
        exception=exception)


def test_payout_is_vp_times_multiplier_times_weight():
    r = pe.compute_entity(_scheme(), _node('105'))     # 1.8x on 100% weight
    assert r.eligible_vp == D('10000.00')
    assert r.gross_payout == D('18000.00')
    assert r.total_payout == D('18000.00')
    assert r.total_multiplier == D('1.8000')


def test_vp_basis_pct_scales_the_eligible_base():
    r = pe.compute_entity(_scheme(vp_basis_pct=D('80')), _node('100'))
    assert r.eligible_vp == D('8000.00')               # 80% of 10,000
    assert r.total_payout == D('8000.00')              # ×1.0


@pytest.mark.parametrize('days,wd,factor,vp_out', [
    (13, 26, '0.5000', '5000.00'),
    (7, 26, '0.2692', '2692.00'),
    (26, 26, '1.0000', '10000.00'),
    (None, 26, '1.0000', '10000.00'),   # null = full period
])
def test_proration_of_eligible_vp(days, wd, factor, vp_out):
    r = pe.compute_entity(_scheme(), _node('100', eligible_days=days, wd=wd))
    assert r.proration_factor == D(factor)
    assert r.eligible_vp == D(vp_out)


def test_min_qualifying_zeroes_the_line_below_the_floor():
    s = _scheme(kpis=(pe.SchemeKPIInput('K1', 'sales', D('100'), D('95'), None, RFP_TIERS),))
    assert pe.compute_entity(s, _node('94')).total_payout == D('0.00')
    assert pe.compute_entity(s, _node('96')).lines[0].treatment == pe.TREATMENT_ACTUAL


def test_per_kpi_multiplier_cap_applies():
    s = _scheme(kpis=(pe.SchemeKPIInput('K1', 'sales', D('100'), None, D('1.2'), RFP_TIERS),))
    r = pe.compute_entity(s, _node('105'))             # would be 1.8, capped to 1.2
    assert r.lines[0].applied_multiplier == D('1.2')
    assert r.lines[0].treatment == pe.TREATMENT_CAPPED
    assert r.total_payout == D('12000.00')


def test_overall_cap_limits_the_total_not_the_lines():
    s = _scheme(overall_cap_pct=D('150'))
    r = pe.compute_entity(s, _node('105'))             # gross 18,000 → capped at 15,000
    assert r.gross_payout == D('18000.00')
    assert r.capped is True
    assert r.total_payout == D('15000.00')


@pytest.mark.parametrize('op,threshold,pct,passes', [
    ('gte', '85', '85', True), ('gte', '85', '84.99', False),
    ('gt', '85', '85', False), ('gt', '85', '85.01', True),
])
def test_gate_operators_at_the_boundary(op, threshold, pct, passes):
    s = _scheme(gates=(pe.GateInput('GATE', op, D(threshold)),))
    r = pe.compute_entity(s, _node(pct))
    assert (r.gatekeeper_status == pe.GK_PASSED) is passes


def test_failed_gate_zeroes_the_payout_but_keeps_gross_for_explainability():
    s = _scheme(gates=(pe.GateInput('GATE', 'gte', D('85')),))
    r = pe.compute_entity(s, _node('50'))
    assert r.gatekeeper_status == pe.GK_FAILED
    assert r.gross_payout == D('0.00')      # 50% is below the first tier anyway
    assert r.total_payout == D('0.00')


def test_failed_gate_with_cap_at_1x_caps_instead_of_zeroing():
    s = _scheme(gates=(pe.GateInput('GATE', 'gte', D('999')),),   # impossible → always fails
                gatekeeper_action=pe.ACTION_CAP_AT_1X)
    r = pe.compute_entity(s, _node('105'))
    assert r.gatekeeper_status == pe.GK_FAILED
    assert r.lines[0].applied_multiplier == D('1.000')   # 1.8 capped to 1.0
    assert r.total_payout == D('10000.00')


def test_all_gates_must_pass():
    s = _scheme(gates=(pe.GateInput('GATE', 'gte', D('50')), pe.GateInput('MISSING', 'gte', D('50'))))
    r = pe.compute_entity(s, _node('90'))
    assert r.gatekeeper_status == pe.GK_FAILED           # second gate has no achievement → 0%
    assert any('MISSING' in w for w in r.warnings)


def test_exception_can_exempt_the_gate_and_default_a_category_to_1x():
    exc = pe.ExceptionInput(sales_kpi_action=pe.KPI_ACTION_DEFAULT_1X,
                            execution_kpi_action=pe.KPI_ACTION_ACTUAL,
                            gatekeeper_action=pe.GK_ACTION_EXEMPTED)
    s = _scheme(gates=(pe.GateInput('GATE', 'gte', D('999')),))
    r = pe.compute_entity(s, _node('10', exception=exc))
    assert r.gatekeeper_status == pe.GK_EXEMPTED
    assert r.lines[0].applied_multiplier == D('1.000')
    assert r.lines[0].treatment == pe.TREATMENT_DEFAULT_1X
    assert r.total_payout == D('10000.00')


def test_exception_can_zero_a_category():
    exc = pe.ExceptionInput(sales_kpi_action=pe.KPI_ACTION_ZERO,
                            execution_kpi_action=pe.KPI_ACTION_ACTUAL,
                            gatekeeper_action='')
    r = pe.compute_entity(_scheme(), _node('105', exception=exc))
    assert r.lines[0].applied_multiplier == D('0')
    assert r.total_payout == D('0.00')


def test_weighted_lines_sum_to_gross_and_weights_are_respected():
    s = _scheme(kpis=(
        pe.SchemeKPIInput('K1', 'sales', D('70'), None, None, RFP_TIERS),
        pe.SchemeKPIInput('K2', 'execution', D('30'), None, None, RFP_TIERS),
    ))
    node = pe.NodeInput(
        entity_id=1, variable_pay=D('10000'), eligible_working_days=None,
        period_working_days=26,
        achievements={'K1': pe.AchievementInput(D('105'), D('0'), D('0')),   # 1.8
                      'K2': pe.AchievementInput(D('100'), D('0'), D('0'))},  # 1.0
        exception=None)
    r = pe.compute_entity(s, node)
    assert r.lines[0].line_payout == D('12600.00')      # 10000 × 1.8 × 70%
    assert r.lines[1].line_payout == D('3000.00')       # 10000 × 1.0 × 30%
    assert r.gross_payout == D('15600.00')
    assert r.gross_payout == sum(l.line_payout for l in r.lines)
    assert r.total_multiplier == D('1.5600')            # 1.8×.7 + 1.0×.3


def test_missing_achievement_is_treated_as_zero_with_a_warning():
    node = pe.NodeInput(entity_id=1, variable_pay=D('10000'), eligible_working_days=None,
                        period_working_days=26, achievements={}, exception=None)
    r = pe.compute_entity(_scheme(), node)
    assert r.total_payout == D('0.00')
    assert any('K1' in w for w in r.warnings)


def test_money_is_quantised_at_the_line_and_gross_is_their_exact_sum():
    """Rounding happens per line at 2dp; gross is the exact sum of those, never
    re-derived from the display multiplier."""
    s = _scheme(kpis=(
        pe.SchemeKPIInput('K1', 'sales', D('33.33'), None, None, RFP_TIERS),
        pe.SchemeKPIInput('K2', 'sales', D('33.33'), None, None, RFP_TIERS),
        pe.SchemeKPIInput('K3', 'sales', D('33.34'), None, None, RFP_TIERS),
    ))
    node = pe.NodeInput(entity_id=1, variable_pay=D('10000'), eligible_working_days=None,
                        period_working_days=26,
                        achievements={c: pe.AchievementInput(D('100'), D('0'), D('0'))
                                      for c in ('K1', 'K2', 'K3')},
                        exception=None)
    r = pe.compute_entity(s, node)
    for line in r.lines:
        assert line.line_payout == line.line_payout.quantize(D('0.01'))
    assert r.gross_payout == sum(l.line_payout for l in r.lines)
    assert r.gross_payout == D('10000.00')
