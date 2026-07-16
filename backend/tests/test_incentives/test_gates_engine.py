"""Multi-condition gate criteria — all gates must pass; one combined consequence.

RFP Expert-SIP shape: RCPA ≥ 85, geofenced coverage ≥ 85, iQuest ≥ 80, clean
compliance (boolean KPI scored 0/100). Exact Decimal assertions throughout.
"""
from decimal import Decimal

from apps.incentives.payout_engine import (
    AchievementInput,
    ExceptionInput,
    GateInput,
    NodeInput,
    SchemeInput,
    SchemeKPIInput,
    TierInput,
    compute_entity,
)

D = Decimal

GRID = (
    TierInput(D('0'), D('100'), D('0.500')),
    TierInput(D('100'), None, D('1.500')),
)

EXPERT_GATES = (
    GateInput('RCPA', 'gte', D('85')),
    GateInput('GEOFENCE', 'gte', D('85')),
    GateInput('IQUEST', 'gte', D('80')),
    GateInput('COMPLIANCE', 'gte', D('100')),
)


def _scheme(gates=EXPERT_GATES, action='zero_payout'):
    return SchemeInput(
        code='EXPERT_SIP', vp_basis_pct=D('100'), overall_cap_pct=None,
        gates=gates, gatekeeper_action=action,
        kpis=(SchemeKPIInput('CORE_VALUE', 'sales', D('100.00'), None, None, GRID),),
    )


def _entity(rcpa='90', geofence='90', iquest='85', compliance='100', core='110',
            exception=None):
    ach = {'CORE_VALUE': AchievementInput(D(core), D('100000'), D(core) * D('1000'))}
    for code, pct in (('RCPA', rcpa), ('GEOFENCE', geofence),
                      ('IQUEST', iquest), ('COMPLIANCE', compliance)):
        if pct is not None:
            ach[code] = AchievementInput(D(pct), D('100'), D(pct))
    return NodeInput(
        entity_id=1, variable_pay=D('50000.00'), eligible_working_days=None,
        period_working_days=20, achievements=ach, exception=exception,
    )


def test_all_gates_pass():
    r = compute_entity(_scheme(), _entity())
    assert r.gatekeeper_status == 'passed'
    assert r.total_payout == D('75000.00')  # 50000 × 1.5 × 100%
    assert [g.passed for g in r.gate_results] == [True, True, True, True]


def test_one_of_four_failing_zeroes_payout():
    r = compute_entity(_scheme(), _entity(rcpa='84.99'))
    assert r.gatekeeper_status == 'failed'
    assert r.total_payout == D('0.00')
    assert r.gross_payout == D('75000.00')  # lines still computed for explainability
    failed = [g for g in r.gate_results if not g.passed]
    assert len(failed) == 1 and failed[0].kpi_code == 'RCPA'
    assert failed[0].achievement_pct == D('84.99')


def test_gate_boundary_gte_passes_at_threshold():
    r = compute_entity(_scheme(), _entity(rcpa='85'))
    assert r.gatekeeper_status == 'passed'


def test_gate_operator_gt_fails_at_threshold():
    gates = (GateInput('RCPA', 'gt', D('85')),)
    assert compute_entity(_scheme(gates), _entity(rcpa='85')).gatekeeper_status == 'failed'
    assert compute_entity(_scheme(gates), _entity(rcpa='85.01')).gatekeeper_status == 'passed'


def test_cap_at_1x_caps_every_line_above_1():
    r = compute_entity(_scheme(action='cap_at_1x'), _entity(iquest='79'))
    assert r.gatekeeper_status == 'failed'
    line = r.lines[0]
    assert line.applied_multiplier == D('1.000')  # 1.5 capped to 1x
    assert line.treatment == 'capped'
    assert r.total_payout == D('50000.00')


def test_exemption_waives_all_gates():
    exc = ExceptionInput('actual_performance', 'actual_performance', 'exempted')
    r = compute_entity(_scheme(), _entity(rcpa='10', iquest='10', exception=exc))
    assert r.gatekeeper_status == 'exempted'
    assert r.total_payout == D('75000.00')
    # Gate results still recorded, showing what actually happened.
    assert [g.passed for g in r.gate_results] == [False, True, False, True]


def test_missing_gate_achievement_counts_as_zero_and_fails():
    r = compute_entity(_scheme(), _entity(compliance=None))
    assert r.gatekeeper_status == 'failed'
    comp = next(g for g in r.gate_results if g.kpi_code == 'COMPLIANCE')
    assert comp.achievement_pct == D('0') and comp.passed is False
    assert any('COMPLIANCE' in w for w in r.warnings)


def test_no_gates_means_not_applicable():
    r = compute_entity(_scheme(gates=()), _entity())
    assert r.gatekeeper_status == 'not_applicable'
    assert r.gate_results == []
    assert r.total_payout == D('75000.00')
