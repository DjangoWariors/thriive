"""Adjustment runs — late data after payday (P5, payout & achievements revamp).

Gate: delta math exact vs the reference run; the paid run is provably untouched; recovery
(negative) rows appear in the current cycle's register; guards reject an open reference
cycle and a missing restatement.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement
from apps.audit.models import ComputationLog
from apps.incentives.models import Payout, PayoutCycle, PayoutRun
from apps.incentives.services import PayoutCycleService
from apps.core.exceptions import BusinessError
from apps.targets.models import TargetPeriod

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp
from .test_cycle import _su


def _stamp_computed(period):
    from django.utils import timezone
    Achievement.objects.filter(target_period=period).update(computed_at=timezone.now())


def _closed_cycle(period, tree, ase_type, kpis, hold_entity=None):
    """June fully closed and paid; returns (cycle, final_run).
    ``hold_entity`` holds that payee during review, so they miss the register."""
    mk_scheme(ase_type, kpis)
    mk_vp(tree['ase1'], period)
    mk_vp(tree['ase2'], period)
    mk_baseline_achievements(period, kpis, tree['ase1'])
    mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
    _stamp_computed(period)
    cycle = PayoutCycleService.open_cycle(period)
    PayoutCycleService.finalize(cycle, actor=_su('jm@x.com'))
    PayoutCycleService.compute(cycle, actor=_su('jc1@x.com'))
    cycle.refresh_from_db()
    if hold_entity is not None:
        held = Payout.objects.get(run__cycle=cycle, entity=hold_entity)
        PayoutCycleService.hold_payout(held, actor=_su('jh@x.com'), reason='bank details disputed')
    PayoutCycleService.submit_cycle(cycle, actor=_su('jm2@x.com'))
    PayoutCycleService.approve_cycle(cycle, actor=_su('jc2@x.com'))
    PayoutCycleService.disburse_cycle(cycle, actor=_su('jf@x.com'), payment_ref='JUN-NEFT')
    PayoutCycleService.close_cycle(cycle)
    cycle.refresh_from_db()
    run = PayoutRun.objects.get(cycle=cycle, kind=PayoutRun.FINAL)
    return cycle, run


def _july(period):
    return TargetPeriod.objects.create(
        name='July 2026', code='JUL26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


def _august():
    return TargetPeriod.objects.create(
        name='August 2026', code='AUG26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
        working_days=21, status=TargetPeriod.PUBLISHED,
    )


def _close_cycle_with_adjustment(cycle, entity, period):
    """Drive an open cycle that carries an adjustment run through to closed/paid."""
    mk_vp(entity, period)
    _stamp_computed(period)
    PayoutCycleService.finalize(cycle, actor=_su(f'{period.code}m@x.com'), override=True,
                                override_reason='no targets for this demo month')
    cycle.refresh_from_db()
    PayoutCycleService.compute(cycle, actor=_su(f'{period.code}c@x.com'))
    cycle.refresh_from_db()
    PayoutCycleService.submit_cycle(cycle, actor=_su(f'{period.code}m2@x.com'))
    PayoutCycleService.approve_cycle(cycle, actor=_su(f'{period.code}c2@x.com'))
    cycle.refresh_from_db()
    PayoutCycleService.disburse_cycle(cycle, actor=_su(f'{period.code}f@x.com'),
                                      payment_ref=f'{period.code}-NEFT')
    PayoutCycleService.close_cycle(cycle)
    cycle.refresh_from_db()


def _restate(period, kpi, entity, pct):
    """Simulate late data: bump an achievement and record a fresh compute log for the period."""
    a = Achievement.objects.get(target_period=period, kpi=kpi, entity=entity)
    a.achievement_pct = Decimal(str(pct))
    a.achieved_value = a.target_value * Decimal(str(pct)) / 100
    a.save(update_fields=['achievement_pct', 'achieved_value'])
    ComputationLog.objects.create(
        computation_type='achievement', entity_id=0, period_id=period.id,
        config_snapshot={}, result_snapshot={},
    )


@pytest.mark.django_db
class TestAdjustment:
    def test_arrears_delta_exact_and_paid_run_untouched(self, tree, period, ase_type, kpis):
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        ref_before = {p.entity_id: p.total_payout
                      for p in Payout.objects.filter(run=june_run)}

        # Late data: ASE1 actually did 120% on PRIMARY (was 85%) → arrears owed.
        _restate(period, kpis['PRIMARY'], tree['ase1'], 120)

        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        result = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))

        adj_run = PayoutRun.objects.get(pk=result['run_id'])
        assert adj_run.kind == PayoutRun.ADJUSTMENT
        assert adj_run.reference_run_id == june_run.id
        assert adj_run.cycle_id == july_cycle.id

        adj = Payout.objects.get(run=adj_run, entity=tree['ase1'])
        # Delta is exact vs the reference: full recompute − amount already paid.
        assert adj.total_payout - adj.adjustment_amount == ref_before[tree['ase1'].id]
        assert adj.adjustment_amount > 0  # arrears

        # The paid June run is provably untouched.
        for p in Payout.objects.filter(run=june_run):
            assert p.total_payout == ref_before[p.entity_id]
        june_run.refresh_from_db()
        assert june_run.status == PayoutRun.PAID

    def test_recovery_is_negative_and_in_register(self, tree, period, ase_type, kpis):
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        # ASE2 was overpaid — restated down from 128% to 60%.
        _restate(period, kpis['PRIMARY'], tree['ase2'], 60)

        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))

        adj = Payout.objects.get(run__cycle=july_cycle, run__kind=PayoutRun.ADJUSTMENT,
                                 entity=tree['ase2'])
        assert adj.adjustment_amount < 0  # recovery

        reg = PayoutCycleService.register(july_cycle)
        adj_rows = [r for r in reg['rows'] if r['kind'] == 'adjustment']
        assert len(adj_rows) == 1
        assert adj_rows[0]['entity_code'] == 'ASE2'
        assert adj_rows[0]['adjustment_for'] == period.code
        assert Decimal(adj_rows[0]['total_payout']) == adj.adjustment_amount
        # Register total reconciles to the payable total (finals payable here are 0 — no finals).
        assert Decimal(reg['total_payout']) == PayoutCycleService._cycle_payable_total(july_cycle)

    def test_no_change_yields_no_rows(self, tree, period, ase_type, kpis):
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        # A fresh compute with no value change (guard passes, but nothing moved).
        ComputationLog.objects.create(computation_type='achievement', entity_id=0,
                                      period_id=period.id, config_snapshot={}, result_snapshot={})
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        result = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))
        assert Decimal(result['net_delta']) == Decimal('0.00')
        assert Payout.objects.filter(run_id=result['run_id']).count() == 0

    def test_reference_cycle_must_be_closed(self, tree, period, ase_type, kpis):
        # A cycle still under review can't be adjusted against.
        mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_vp(tree['ase2'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        _stamp_computed(period)
        cycle = PayoutCycleService.open_cycle(period)
        PayoutCycleService.finalize(cycle, actor=_su('m@x.com'))
        PayoutCycleService.compute(cycle, actor=_su('c@x.com'))
        cycle.refresh_from_db()
        run = PayoutRun.objects.get(cycle=cycle, kind=PayoutRun.FINAL)

        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        with pytest.raises(BusinessError, match='must reference a paid final run'):
            PayoutCycleService.create_adjustment(run, july_cycle, actor=_su('adj@x.com'))

    def test_requires_real_restatement(self, tree, period, ase_type, kpis):
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        # No fresh compute since finalize → nothing to adjust.
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        with pytest.raises(BusinessError, match='No achievement restatement'):
            PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))

    def test_adjustment_rides_cycle_approval_and_disbursement(self, tree, period, ase_type, kpis):
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        _restate(period, kpis['PRIMARY'], tree['ase1'], 120)
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))

        # July's own final compute (no July achievements → no final payouts) then close.
        mk_vp(tree['ase1'], july)
        _stamp_computed(july)
        PayoutCycleService.finalize(july_cycle, actor=_su('jlm@x.com'), override=True,
                                    override_reason='no july targets yet')
        july_cycle.refresh_from_db()
        PayoutCycleService.compute(july_cycle, actor=_su('jlc@x.com'))
        july_cycle.refresh_from_db()
        PayoutCycleService.submit_cycle(july_cycle, actor=_su('jlm2@x.com'))
        PayoutCycleService.approve_cycle(july_cycle, actor=_su('jlc2@x.com'))
        july_cycle.refresh_from_db()

        adj_run = PayoutRun.objects.get(cycle=july_cycle, kind=PayoutRun.ADJUSTMENT)
        assert adj_run.status == PayoutRun.APPROVED  # rode the cycle approval

        PayoutCycleService.disburse_cycle(july_cycle, actor=_su('jlf@x.com'), payment_ref='JUL-NEFT')
        adj_run.refresh_from_db()
        assert adj_run.status == PayoutRun.PAID

    def test_held_payout_rides_next_cycle_adjustment(self, tree, period, ase_type, kpis):
        """A payee held at disbursement was never paid — the next cycle's adjustment pays
        their full amount as arrears, and no restatement is needed to raise it."""
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis,
                                             hold_entity=tree['ase2'])
        held = Payout.objects.get(run=june_run, entity=tree['ase2'])
        assert held.hold_status == Payout.HOLD_HELD
        assert held.total_payout == Decimal('115000.00')

        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        # No achievement restatement — the held amount alone justifies the adjustment.
        result = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))

        adj = Payout.objects.get(run_id=result['run_id'], entity=tree['ase2'])
        assert adj.adjustment_amount == held.total_payout  # full withheld amount as arrears
        # The payee who was paid normally didn't change → no row.
        assert not Payout.objects.filter(run_id=result['run_id'], entity=tree['ase1']).exists()
        assert Decimal(result['net_delta']) == held.total_payout

    def test_second_adjustment_pays_only_incremental_delta(self, tree, period, ase_type, kpis):
        """Prior paid adjustment deltas are folded into 'already paid' — a later
        restatement pays only the increment, never re-paying the first delta."""
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)

        # First restatement: PRIMARY 85% → 105% (71,000 → 81,000) → +10,000 in July.
        _restate(period, kpis['PRIMARY'], tree['ase1'], 105)
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        r1 = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj1@x.com'))
        adj1 = Payout.objects.get(run_id=r1['run_id'], entity=tree['ase1'])
        assert adj1.adjustment_amount == Decimal('10000.00')
        _close_cycle_with_adjustment(july_cycle, tree['ase1'], july)

        # Second restatement: 105% → 125% (81,000 → 96,000) → only +15,000 in August.
        _restate(period, kpis['PRIMARY'], tree['ase1'], 125)
        aug_cycle = PayoutCycleService.open_cycle(_august())
        r2 = PayoutCycleService.create_adjustment(june_run, aug_cycle, actor=_su('adj2@x.com'))
        adj2 = Payout.objects.get(run_id=r2['run_id'], entity=tree['ase1'])
        assert adj2.adjustment_amount == Decimal('15000.00')  # 96,000 − (71,000 + 10,000)

    def test_repeat_adjustment_after_settlement_yields_no_rows(self, tree, period, ase_type, kpis):
        """Once an adjustment has settled a restatement, raising another one without new
        data produces no rows (idempotent — nothing left to pay or recover)."""
        june_cycle, june_run = _closed_cycle(period, tree, ase_type, kpis)
        _restate(period, kpis['PRIMARY'], tree['ase1'], 105)
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj1@x.com'))
        _close_cycle_with_adjustment(july_cycle, tree['ase1'], july)

        aug_cycle = PayoutCycleService.open_cycle(_august())
        result = PayoutCycleService.create_adjustment(june_run, aug_cycle, actor=_su('adj2@x.com'))
        assert Decimal(result['net_delta']) == Decimal('0.00')
        assert Payout.objects.filter(run_id=result['run_id']).count() == 0
