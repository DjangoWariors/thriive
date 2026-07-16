"""Pure payout-engine tests — no DB. Every assertion is an exact Decimal.

Canonical fixture: VP 100,000.00; KPIs PRIMARY (sales, w50), ECO (execution, w30),
MSL (execution, w20); shared tier grid [0,50)→0, [50,80)→0.5, [80,100)→0.8,
[100,120)→1.0, [120,∞)→1.3. Baseline achievements: PRIMARY 85%, ECO 60%, MSL 90%.
"""
from decimal import Decimal

from apps.incentives.payout_engine import (
    AchievementInput,
    GateInput,
    NodeInput,
    ExceptionInput,
    SchemeInput,
    SchemeKPIInput,
    TierInput,
    compute_entity,
    match_tier,
    validate_tiers,
)

D = Decimal

GRID = (
    TierInput(D('0'), D('50'), D('0.000')),
    TierInput(D('50'), D('80'), D('0.500')),
    TierInput(D('80'), D('100'), D('0.800')),
    TierInput(D('100'), D('120'), D('1.000')),
    TierInput(D('120'), None, D('1.300')),
)


def mk_kpi(code, category, weight, tiers=GRID, min_qualifying=None, cap=None):
    return SchemeKPIInput(
        kpi_code=code, category=category, weightage=D(weight),
        min_qualifying_pct=D(min_qualifying) if min_qualifying is not None else None,
        multiplier_cap=D(cap) if cap is not None else None,
        tiers=tiers,
    )


def mk_scheme(kpis=None, vp_basis='100', overall_cap=None,
              gk_kpi=None, gk_threshold=None, gk_action='zero_payout'):
    if kpis is None:
        kpis = (
            mk_kpi('PRIMARY', 'sales', '50.00'),
            mk_kpi('ECO', 'execution', '30.00'),
            mk_kpi('MSL', 'execution', '20.00'),
        )
    return SchemeInput(
        code='FF_TEST', vp_basis_pct=D(vp_basis),
        overall_cap_pct=D(overall_cap) if overall_cap is not None else None,
        gates=(GateInput(gk_kpi, 'gte', D(gk_threshold)),) if gk_kpi is not None else (),
        gatekeeper_action=gk_action, kpis=kpis,
    )


def mk_achievements(primary='85', eco='60', msl='90'):
    out = {}
    for code, pct in (('PRIMARY', primary), ('ECO', eco), ('MSL', msl)):
        if pct is not None:
            out[code] = AchievementInput(D(pct), D('100000'), D(pct) * D('1000'))
    return out


def mk_entity(achievements=None, vp='100000.00', eligible_days=None,
              period_days=20, exception=None):
    return NodeInput(
        entity_id=1, variable_pay=D(vp), eligible_working_days=eligible_days,
        period_working_days=period_days,
        achievements=achievements if achievements is not None else mk_achievements(),
        exception=exception,
    )


# ---------------------------------------------------------------- T1 normal
def test_t1_normal_three_kpis():
    r = compute_entity(mk_scheme(), mk_entity())
    assert [line.line_payout for line in r.lines] == [
        D('40000.00'), D('15000.00'), D('16000.00'),
    ]
    assert r.gross_payout == D('71000.00')
    assert r.total_payout == D('71000.00')
    assert r.total_multiplier == D('0.7100')
    assert r.gatekeeper_status == 'not_applicable'
    assert all(line.treatment == 'actual' for line in r.lines)


# ----------------------------------------------------------- T2 overachiever
def test_t2_overachiever():
    r = compute_entity(mk_scheme(), mk_entity(mk_achievements('128', '105', '110')))
    assert [line.line_payout for line in r.lines] == [
        D('65000.00'), D('30000.00'), D('20000.00'),
    ]
    assert r.total_payout == D('115000.00')


# ---------------------------------------------------- T3 exception default_1x
def test_t3_exception_sales_default_1x():
    exc = ExceptionInput('default_1x', 'actual_performance', 'no_exemption')
    r = compute_entity(mk_scheme(), mk_entity(exception=exc))
    primary = r.lines[0]
    assert primary.treatment == 'default_1x'
    assert primary.applied_multiplier == D('1.000')
    assert primary.line_payout == D('50000.00')
    assert r.total_payout == D('81000.00')


# --------------------------------------------------------- T4 exception zero
def test_t4_exception_all_zero():
    exc = ExceptionInput('zero', 'zero', 'no_exemption')
    r = compute_entity(mk_scheme(), mk_entity(exception=exc))
    assert r.total_payout == D('0.00')
    assert len(r.lines) == 3
    assert all(line.treatment == 'zero' and line.line_payout == D('0.00') for line in r.lines)


# -------------------------------------------------------- T5 gatekeeper fail
def test_t5_gatekeeper_fail_zero_payout():
    scheme = mk_scheme(gk_kpi='MSL', gk_threshold='80')
    r = compute_entity(scheme, mk_entity(mk_achievements(msl='75')))
    # Lines retained for transparency: 40000 + 15000 + (0.5 × 20%) 10000
    assert r.gross_payout == D('65000.00')
    assert r.total_payout == D('0.00')
    assert r.gatekeeper_status == 'failed'


# --------------------------------------------------- T6 gatekeeper exempted
def test_t6_gatekeeper_exempted():
    scheme = mk_scheme(gk_kpi='MSL', gk_threshold='80')
    exc = ExceptionInput('actual_performance', 'actual_performance', 'exempted')
    r = compute_entity(scheme, mk_entity(mk_achievements(msl='75'), exception=exc))
    assert r.total_payout == D('65000.00')
    assert r.gatekeeper_status == 'exempted'


# ----------------------------------------------- gatekeeper cap_at_1x action
def test_gatekeeper_fail_cap_at_1x():
    scheme = mk_scheme(gk_kpi='MSL', gk_threshold='80', gk_action='cap_at_1x')
    r = compute_entity(scheme, mk_entity(mk_achievements('128', '105', '75')))
    # PRIMARY 1.3 → capped to 1.0; ECO 1.0 stays; MSL 0.5 stays
    assert r.lines[0].applied_multiplier == D('1.000')
    assert r.lines[0].treatment == 'capped'
    assert r.total_payout == D('50000.00') + D('30000.00') + D('10000.00')
    assert r.gatekeeper_status == 'failed'


# ----------------------------------------------------------- T8 zero VP
def test_t8_zero_variable_pay():
    r = compute_entity(mk_scheme(), mk_entity(vp='0.00'))
    assert r.eligible_vp == D('0.00')
    assert r.total_payout == D('0.00')


# ------------------------------------------------- T9 last tier unlimited
def test_t9_last_tier_unlimited():
    r = compute_entity(mk_scheme(), mk_entity(mk_achievements(primary='250')))
    assert r.lines[0].base_multiplier == D('1.300')
    assert r.lines[0].line_payout == D('65000.00')
    assert r.lines[0].tier_min == D('120')
    assert r.lines[0].tier_max is None


# ----------------------------------------------------- T11 per-KPI cap
def test_t11_per_kpi_multiplier_cap():
    kpis = (
        mk_kpi('PRIMARY', 'sales', '50.00', cap='1.200'),
        mk_kpi('ECO', 'execution', '30.00'),
        mk_kpi('MSL', 'execution', '20.00'),
    )
    r = compute_entity(mk_scheme(kpis), mk_entity(mk_achievements(primary='128')))
    primary = r.lines[0]
    assert primary.base_multiplier == D('1.300')
    assert primary.applied_multiplier == D('1.200')
    assert primary.treatment == 'capped'
    assert primary.line_payout == D('60000.00')


# ----------------------------------------------------- T12 overall cap
def test_t12_overall_cap():
    scheme = mk_scheme(overall_cap='110.00')
    r = compute_entity(scheme, mk_entity(mk_achievements('128', '105', '110')))
    assert r.gross_payout == D('115000.00')
    assert r.total_payout == D('110000.00')
    assert r.capped is True


# ------------------------------------------- T13 min qualifying threshold
def test_t13_min_qualifying_threshold():
    # ECO at 55% would pay 0.5 normally; threshold at 60 zeroes it
    kpis = (
        mk_kpi('PRIMARY', 'sales', '50.00'),
        mk_kpi('ECO', 'execution', '30.00', min_qualifying='60'),
        mk_kpi('MSL', 'execution', '20.00'),
    )
    r = compute_entity(mk_scheme(kpis), mk_entity(mk_achievements(eco='55')))
    eco = r.lines[1]
    assert eco.treatment == 'below_threshold'
    assert eco.applied_multiplier == D('0')
    assert eco.line_payout == D('0.00')
    assert r.total_payout == D('56000.00')


# ----------------------------------------------------------- T14 proration
def test_t14_proration_half_period():
    r = compute_entity(mk_scheme(), mk_entity(eligible_days=10, period_days=20))
    assert r.proration_factor == D('0.5000')
    assert r.eligible_vp == D('50000.00')
    assert r.total_payout == D('35500.00')


# ---------------------------------------------------------- T15 vp basis
def test_t15_vp_basis_pct():
    r = compute_entity(mk_scheme(vp_basis='70.00'), mk_entity())
    assert r.eligible_vp == D('70000.00')
    assert r.total_payout == D('49700.00')


# ------------------------------------------------- T16 rounding determinism
def test_t16_line_level_half_up_rounding():
    grid = (TierInput(D('0'), None, D('0.450')),)
    kpis = (
        mk_kpi('A', 'sales', '50.00', tiers=grid),
        mk_kpi('B', 'sales', '50.00', tiers=grid),
    )
    achievements = {
        'A': AchievementInput(D('90'), D('0'), D('0')),
        'B': AchievementInput(D('90'), D('0'), D('0')),
    }
    r = compute_entity(mk_scheme(kpis), mk_entity(achievements, vp='10001.00'))
    # 10001 × 0.45 × 0.50 = 2250.225 → HALF_UP 2250.23 per line (HALF_EVEN would give .22)
    assert [line.line_payout for line in r.lines] == [D('2250.23'), D('2250.23')]
    assert r.total_payout == D('4500.46')


# -------------------------------------------------- T20 missing achievement
def test_t20_missing_achievement_warns_and_zeroes():
    achievements = mk_achievements(eco=None)
    r = compute_entity(mk_scheme(), mk_entity(achievements))
    eco = r.lines[1]
    assert eco.achievement_pct == D('0')
    assert eco.line_payout == D('0.00')
    assert r.total_payout == D('56000.00')
    assert any('ECO' in w for w in r.warnings)


def test_missing_gatekeeper_achievement_fails_gate():
    scheme = mk_scheme(gk_kpi='MSL', gk_threshold='80')
    achievements = mk_achievements(msl=None)
    r = compute_entity(scheme, mk_entity(achievements))
    assert r.gatekeeper_status == 'failed'
    assert r.total_payout == D('0.00')
    assert any('gate' in w.lower() for w in r.warnings)


# ------------------------------------------------------- tier matching edges
def test_match_tier_boundaries():
    assert match_tier(GRID, D('0')).multiplier == D('0.000')
    assert match_tier(GRID, D('49.99')).multiplier == D('0.000')
    assert match_tier(GRID, D('50')).multiplier == D('0.500')   # min inclusive
    assert match_tier(GRID, D('99.99')).multiplier == D('0.800')
    assert match_tier(GRID, D('100')).multiplier == D('1.000')
    assert match_tier(GRID, D('120')).multiplier == D('1.300')  # unlimited tier
    assert match_tier(GRID, D('9999')).multiplier == D('1.300')


# ------------------------------------------------------ validate_tiers (T10)
def test_validate_tiers_accepts_canonical_grid():
    assert validate_tiers(GRID) == []


def test_validate_tiers_rejects_bad_grids():
    # First tier not at 0
    assert validate_tiers((TierInput(D('10'), None, D('1')),))
    # Gap: [0,80) then [90,∞)
    gap = (TierInput(D('0'), D('80'), D('0')), TierInput(D('90'), None, D('1')))
    assert any('contiguous' in e for e in validate_tiers(gap))
    # Overlap: [0,80) then [70,∞)
    overlap = (TierInput(D('0'), D('80'), D('0')), TierInput(D('70'), None, D('1')))
    assert any('contiguous' in e for e in validate_tiers(overlap))
    # Last tier bounded
    bounded = (TierInput(D('0'), D('100'), D('0.5')), TierInput(D('100'), D('120'), D('1')))
    assert any('unbounded' in e for e in validate_tiers(bounded))
    # Negative multiplier
    neg = (TierInput(D('0'), None, D('-1')),)
    assert any('negative' in e for e in validate_tiers(neg))
    # Empty
    assert validate_tiers(()) == ['At least one tier is required.']
