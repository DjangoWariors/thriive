"""PayoutCycle review → hold → disbursement (P3, payout & achievements revamp).

Gate: maker ≠ checker at cycle level; a held payee is excluded from the register; the
register total reconciles to the payable (non-held) payouts to the paisa.
"""
from decimal import Decimal

import pytest

from apps.incentives.models import Payout, PayoutCycle, PayoutRun
from apps.incentives.services import PayoutCycleService, PayoutService
from apps.core.exceptions import BusinessError
from apps.targets.models import TargetPeriod

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp
from .test_cycle import _su


def _computed_cycle(period, tree, ase_type, kpis):
    """A finalized, computed cycle sitting in under_review with two payees."""
    from django.utils import timezone
    from apps.achievements.models import Achievement

    mk_scheme(ase_type, kpis)
    mk_vp(tree['ase1'], period)
    mk_vp(tree['ase2'], period)
    mk_baseline_achievements(period, kpis, tree['ase1'])
    mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
    Achievement.objects.filter(target_period=period).update(computed_at=timezone.now())
    cycle = PayoutCycleService.open_cycle(period)
    PayoutCycleService.finalize(cycle, actor=_su('maker@x.com'))
    PayoutCycleService.compute(cycle, actor=_su('c1@x.com'))
    cycle.refresh_from_db()
    return cycle


@pytest.mark.django_db
class TestCycleMakerChecker:
    def test_maker_cannot_approve_own_cycle(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        maker = _su('m@x.com')
        PayoutCycleService.submit_cycle(cycle, actor=maker)
        with pytest.raises(BusinessError, match='cannot be approved by its submitter'):
            PayoutCycleService.approve_cycle(cycle, actor=maker)

    def test_approve_requires_prior_submit(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        with pytest.raises(BusinessError, match='Submit the cycle'):
            PayoutCycleService.approve_cycle(cycle, actor=_su('c@x.com'))

    def test_checker_approves_and_runs_follow(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.submit_cycle(cycle, actor=_su('m@x.com'))
        PayoutCycleService.approve_cycle(cycle, actor=_su('c@x.com'))
        cycle.refresh_from_db()
        assert cycle.status == PayoutCycle.APPROVED
        assert all(r.status == PayoutRun.APPROVED
                   for r in cycle.runs.filter(kind=PayoutRun.FINAL))

    def test_full_disbursement_flow(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.submit_cycle(cycle, actor=_su('m@x.com'))
        PayoutCycleService.approve_cycle(cycle, actor=_su('c@x.com'))
        PayoutCycleService.disburse_cycle(cycle, actor=_su('fin@x.com'),
                                          payment_ref='NEFT-2026-06')
        cycle.refresh_from_db()
        assert cycle.status == PayoutCycle.DISBURSED
        assert cycle.register_ref == 'NEFT-2026-06'
        assert all(r.status == PayoutRun.PAID for r in cycle.runs.filter(kind=PayoutRun.FINAL))
        PayoutCycleService.close_cycle(cycle)
        cycle.refresh_from_db()
        assert cycle.status == PayoutCycle.CLOSED
        # Closing the cycle closes the month (derived period status).
        period.refresh_from_db()
        assert period.status == TargetPeriod.CLOSED


@pytest.mark.django_db
class TestHoldAndRegister:
    def test_held_payee_excluded_and_register_reconciles(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p_ase1 = Payout.objects.get(run__cycle=cycle, entity=tree['ase1'])
        p_ase2 = Payout.objects.get(run__cycle=cycle, entity=tree['ase2'])

        PayoutCycleService.hold_payout(p_ase1, actor=_su('m@x.com'), reason='Disputed target')

        reg = PayoutCycleService.register(cycle)
        codes = {r['entity_code'] for r in reg['rows']}
        assert 'ASE1' not in codes  # held → excluded
        assert 'ASE2' in codes
        assert reg['held_count'] == 1

        # Register total reconciles to the payable payouts to the paisa.
        payable_total = PayoutCycleService._payable_payouts(cycle).aggregate(
            t=__import__('django.db.models', fromlist=['Sum']).Sum('total_payout'))['t']
        assert Decimal(reg['total_payout']) == payable_total == p_ase2.total_payout

    def test_hold_requires_reason_and_review_state(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = Payout.objects.get(run__cycle=cycle, entity=tree['ase1'])
        with pytest.raises(BusinessError, match='reason is required'):
            PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='  ')

        # After disbursement, holding is no longer allowed.
        PayoutCycleService.submit_cycle(cycle, actor=_su('m1@x.com'))
        PayoutCycleService.approve_cycle(cycle, actor=_su('c@x.com'))
        PayoutCycleService.disburse_cycle(cycle, actor=_su('fin@x.com'), payment_ref='X')
        p.refresh_from_db()
        with pytest.raises(BusinessError, match='under review'):
            PayoutCycleService.hold_payout(p, actor=_su('m2@x.com'), reason='late')

    def test_release_restores_to_register(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = Payout.objects.get(run__cycle=cycle, entity=tree['ase1'])
        PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='check')
        PayoutCycleService.release_payout(p, actor=_su('m2@x.com'))
        p.refresh_from_db()
        assert p.hold_status == Payout.HOLD_RELEASED
        reg = PayoutCycleService.register(cycle)
        assert {'ASE1', 'ASE2'} <= {r['entity_code'] for r in reg['rows']}

    def test_register_csv_has_header_and_total(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        csv_text = PayoutCycleService.register_csv(cycle)
        lines = csv_text.strip().splitlines()
        assert lines[0].startswith('entity_code,entity_name')
        assert lines[-1].startswith('TOTAL')


@pytest.mark.django_db
class TestReviewPayload:
    def test_review_stats_and_distribution(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = Payout.objects.get(run__cycle=cycle, entity=tree['ase1'])
        PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='x')

        review = PayoutCycleService.review(cycle)
        assert review['stats']['payees'] == 1  # ase2 only (ase1 held)
        assert review['stats']['held'] == 1
        assert sum(b['count'] for b in review['multiplier_distribution']) == 1
        assert [r['entity_code'] for r in review['outliers']['held']] == ['ASE1']
        assert review['variance'] is None  # no prior cycle

    def test_statement_reads_lines(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = Payout.objects.get(run__cycle=cycle, entity=tree['ase1'])
        stmt = PayoutService.statement(p.pk, _su('admin@x.com'))
        assert stmt['entity']['code'] == 'ASE1'
        assert stmt['total_payout'] == str(p.total_payout)
        assert {li['kpi_code'] for li in stmt['lines']} == {'PRIMARY', 'ECO', 'MSL'}
