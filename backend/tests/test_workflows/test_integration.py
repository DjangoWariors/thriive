"""End-to-end: raise an exception → approve it through the workflow → the next payout run
reflects the override. Proves the retrofit invariant against the real payout engine."""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement
from apps.incentives.models import (
    IncentiveScheme, MultiplierTier, PayoutException, SchemeKPI, VariablePay,
)
from apps.incentives.services import ExceptionService, PayoutService
from apps.kpi_engine.models import KPIDefinition
from apps.workflows.services import WorkflowService

pytestmark = pytest.mark.django_db

GRID = [('0', '50', '0.000'), ('50', '80', '0.500'), ('80', '100', '0.800'),
        ('100', '120', '1.000'), ('120', None, '1.300')]


def _build_scheme(ase_type):
    kpi = KPIDefinition.objects.create(
        code='PRIMARY', name='Primary', kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    scheme = IncentiveScheme.objects.create(
        name='FF', code='FF', target_entity_type=ase_type, vp_basis_pct=Decimal('100.00'),
        gatekeeper_action='zero_payout', effective_from=date.today(),
    )
    sk = SchemeKPI.objects.create(
        scheme=scheme, kpi=kpi, incentive_category=SchemeKPI.SALES,
        weightage=Decimal('100.00'), display_order=0,
    )
    for mn, mx, mult in GRID:
        MultiplierTier.objects.create(
            scheme_kpi=sk, min_achievement_pct=Decimal(mn),
            max_achievement_pct=Decimal(mx) if mx else None, multiplier=Decimal(mult),
        )
    return scheme, kpi


def test_workflow_approved_exception_changes_payout(org, period, seeded):
    scheme, kpi = _build_scheme(org['ase1'].entity_type)
    VariablePay.objects.create(entity=org['ase1'], target_period=period, amount=Decimal('100000.00'))
    Achievement.objects.create(
        target_period=period, kpi=kpi, entity=org['ase1'],
        target_value=Decimal('100000'), achieved_value=Decimal('85000'),
        achievement_pct=Decimal('85'),
    )

    # Baseline: 85% → 0.8x → 100000 * 0.8 = 80000.00
    run = PayoutService.start_run(scheme.pk, period.pk)
    PayoutService.compute_run(run.pk)
    assert run.payouts.get(entity=org['ase1']).total_payout == Decimal('80000.00')

    # Raise a 'zero sales' exception, route + approve through the workflow.
    exc = ExceptionService.create({
        'entity': org['ase1'], 'target_period': period, 'scheme': None,
        'category': 'technical', 'sales_kpi_action': PayoutException.ZERO,
        'execution_kpi_action': PayoutException.ACTUAL,
        'gatekeeper_action': PayoutException.NO_EXEMPTION, 'reason': 'bad data',
    }, actor=org['asm_user'])
    inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
    assert inst is not None
    WorkflowService.approve(inst, org['nsm_user'], 'approved')
    exc.refresh_from_db()
    assert exc.status == PayoutException.APPROVED

    # Recompute: the sole sales KPI is zeroed → payout 0.00.
    run2 = PayoutService.start_run(scheme.pk, period.pk)
    PayoutService.compute_run(run2.pk)
    assert run2.payouts.get(entity=org['ase1']).total_payout == Decimal('0.00')
