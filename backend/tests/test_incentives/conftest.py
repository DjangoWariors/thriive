"""Shared fixtures for incentive tests.

Tree:  NSM (root) → ASM (manager) → ASE1, ASE2 (leaves)
Period: June 2026, working_days=20.
Canonical scheme: PRIMARY (sales, w50), ECO (execution, w30), MSL (execution, w20);
tier grid [0,50)→0, [50,80)→0.5, [80,100)→0.8, [100,120)→1.0, [120,∞)→1.3.
Baseline achievements: PRIMARY 85%, ECO 60%, MSL 90% → payout 71,000.00 on VP 100,000.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement
from apps.hierarchy.models import Channel, Node, NodeType
from apps.incentives.models import (
    IncentiveScheme,
    MultiplierTier,
    PayoutException,
    SchemeGate,
    SchemeKPI,
    VariablePay,
)
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetPeriod

GRID = [
    ('0', '50', '0.000'),
    ('50', '80', '0.500'),
    ('80', '100', '0.800'),
    ('100', '120', '1.000'),
    ('120', None, '1.300'),
]


@pytest.fixture
def gt(db):
    return Channel.objects.create(name='General Trade', code='GT')


@pytest.fixture
def ase_type(db):
    return NodeType.objects.create(
        name='ASE', code='ASE', level_order=3, incentive_eligible=True,
        effective_from=date.today(),
    )


@pytest.fixture
def tree(db, ase_type, gt):
    nsm_type = NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, incentive_eligible=True,
        effective_from=date.today(),
    )
    asm_type = NodeType.objects.create(
        name='ASM', code='ASM', level_order=2, incentive_eligible=True,
        effective_from=date.today(),
    )
    nsm = Node.objects.create(entity_type=nsm_type, name='NSM', code='NSM',
                                effective_from=date.today())
    asm = Node.objects.create(entity_type=asm_type, name='ASM', code='ASM', parent=nsm,
                                effective_from=date.today())
    ase1 = Node.objects.create(entity_type=ase_type, name='Deepa', code='ASE1', parent=asm,
                                 channel=gt, effective_from=date.today())
    ase2 = Node.objects.create(entity_type=ase_type, name='Rahul', code='ASE2', parent=asm,
                                 channel=gt, effective_from=date.today())
    return {'nsm': nsm, 'asm': asm, 'ase1': ase1, 'ase2': ase2}


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        name='June 2026', code='JUN26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


def mk_kpi(code, name=None):
    return KPIDefinition.objects.create(
        code=code, name=name or code, kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )


@pytest.fixture
def kpis(db):
    return {
        'PRIMARY': mk_kpi('PRIMARY', 'Primary Sales'),
        'ECO': mk_kpi('ECO', 'Effective Coverage'),
        'MSL': mk_kpi('MSL', 'Must-Sell Lines'),
    }


def mk_scheme(ase_type, kpis, *, code='FF_TEST', vp_basis='100.00', overall_cap=None,
              gk_kpi=None, gk_threshold=None, gk_action='zero_payout', channel=None,
              kpi_overrides=None):
    """Create the canonical scheme directly (model-level; bypasses SchemeService)."""
    scheme = IncentiveScheme.objects.create(
        name='Field Force Test', code=code, target_entity_type=ase_type,
        channel=channel, vp_basis_pct=Decimal(vp_basis),
        overall_cap_pct=Decimal(overall_cap) if overall_cap is not None else None,
        gatekeeper_action=gk_action,
        effective_from=date.today(),
    )
    if gk_kpi is not None:
        SchemeGate.objects.create(
            scheme=scheme, kpi=gk_kpi, operator=SchemeGate.GTE,
            threshold_pct=Decimal(gk_threshold),
        )
    spec = [
        ('PRIMARY', SchemeKPI.SALES, '50.00'),
        ('ECO', SchemeKPI.EXECUTION, '30.00'),
        ('MSL', SchemeKPI.EXECUTION, '20.00'),
    ]
    overrides = kpi_overrides or {}
    for order, (kpi_code, category, weight) in enumerate(spec):
        extra = overrides.get(kpi_code, {})
        scheme_kpi = SchemeKPI.objects.create(
            scheme=scheme, kpi=kpis[kpi_code], incentive_category=category,
            weightage=Decimal(weight), display_order=order,
            min_qualifying_pct=extra.get('min_qualifying_pct'),
            multiplier_cap=extra.get('multiplier_cap'),
        )
        for tier_min, tier_max, mult in GRID:
            MultiplierTier.objects.create(
                scheme_kpi=scheme_kpi,
                min_achievement_pct=Decimal(tier_min),
                max_achievement_pct=Decimal(tier_max) if tier_max is not None else None,
                multiplier=Decimal(mult),
            )
    return scheme


def mk_vp(entity, period, amount='100000.00', eligible_days=None):
    return VariablePay.objects.create(
        entity=entity, target_period=period, amount=Decimal(amount),
        eligible_working_days=eligible_days,
    )


def mk_achievement(period, kpi, entity, pct, target='100000'):
    pct = Decimal(str(pct))
    target = Decimal(str(target))
    return Achievement.objects.create(
        target_period=period, kpi=kpi, entity=entity,
        target_value=target, achieved_value=target * pct / 100,
        achievement_pct=pct,
    )


def mk_baseline_achievements(period, kpis, entity, primary='85', eco='60', msl='90'):
    for code, pct in (('PRIMARY', primary), ('ECO', eco), ('MSL', msl)):
        if pct is not None:
            mk_achievement(period, kpis[code], entity, pct)


def mk_exception(entity, period, *, scheme=None, sales='actual_performance',
                 execution='actual_performance', gatekeeper='no_exemption',
                 status=PayoutException.APPROVED, requested_by=None):
    return PayoutException.objects.create(
        entity=entity, target_period=period, scheme=scheme,
        sales_kpi_action=sales, execution_kpi_action=execution,
        gatekeeper_action=gatekeeper, reason='test', status=status,
        requested_by=requested_by,
    )
