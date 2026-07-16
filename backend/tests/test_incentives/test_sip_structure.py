"""SIP variable-pay split — monthly (80%) vs annual (20%) components."""
from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.incentives.services import PayoutService, SchemeService
from apps.targets.models import TargetPeriod

from .conftest import mk_achievement, mk_scheme, mk_vp

D = Decimal


@pytest.fixture
def annual_period(db):
    return TargetPeriod.objects.create(
        name='FY 2026-27', code='FY27', period_type=TargetPeriod.ANNUAL,
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        working_days=240, status=TargetPeriod.PUBLISHED,
    )


@pytest.mark.django_db
def test_annual_scheme_computes_over_annual_period(tree, annual_period, ase_type, kpis):
    scheme = mk_scheme(ase_type, kpis, code='EXPERT_ANNUAL', vp_basis='20.00')
    scheme.payout_frequency = 'annual'
    scheme.save(update_fields=['payout_frequency'])

    mk_vp(tree['ase1'], annual_period, amount='120000.00')
    for code in ('PRIMARY', 'ECO', 'MSL'):
        mk_achievement(annual_period, kpis[code], tree['ase1'], '100')

    run = PayoutService.start_run(scheme.pk, annual_period.pk)
    PayoutService.compute_run(run.pk)
    payout = run.payouts.get(entity=tree['ase1'])
    # eligible VP = 120000 × 20% = 24000; at 100% every line pays 1.0×
    assert payout.eligible_vp == D('24000.00')
    assert payout.total_payout == D('24000.00')


@pytest.mark.django_db
def test_frequency_period_type_mismatch_rejected(tree, period, annual_period, ase_type, kpis):
    monthly = mk_scheme(ase_type, kpis, code='MONTHLY_S')
    with pytest.raises(BusinessError, match='monthly scheme'):
        PayoutService.start_run(monthly.pk, annual_period.pk)

    annual = mk_scheme(ase_type, kpis, code='ANNUAL_S')
    annual.payout_frequency = 'annual'
    annual.save(update_fields=['payout_frequency'])
    with pytest.raises(BusinessError, match='annual scheme'):
        PayoutService.start_run(annual.pk, period.pk)


@pytest.mark.django_db
def test_sip_structure_groups_and_completeness(ase_type, kpis):
    monthly = mk_scheme(ase_type, kpis, code='EXPERT_MONTHLY', vp_basis='80.00')
    structure = SchemeService.sip_structure()
    group = next(g for g in structure if g['entity_type'] == ase_type.code)
    assert group['is_complete'] is False  # 80 only
    assert group['total_vp_basis_pct'] == '80.00'

    annual = mk_scheme(ase_type, kpis, code='EXPERT_ANNUAL', vp_basis='20.00')
    annual.payout_frequency = 'annual'
    annual.save(update_fields=['payout_frequency'])

    structure = SchemeService.sip_structure()
    group = next(g for g in structure if g['entity_type'] == ase_type.code)
    assert group['is_complete'] is True
    assert group['total_vp_basis_pct'] == '100.00'
    freqs = {c['scheme_code']: c['payout_frequency'] for c in group['components']}
    assert freqs == {'EXPERT_MONTHLY': 'monthly', 'EXPERT_ANNUAL': 'annual'}
    assert monthly.code in freqs
