"""PayoutService end-to-end: compute through the ORM bridge, run lifecycle,
supersede, immutability. Exact Decimal assertions throughout."""
from decimal import Decimal

import pytest

from apps.audit.models import ComputationLog
from apps.core.exceptions import BusinessError
from apps.incentives.models import Payout, PayoutRun
from apps.incentives.services import PayoutService

from .conftest import mk_baseline_achievements, mk_exception, mk_scheme, mk_vp

D = Decimal


def _user(email):
    from apps.accounts.models import User
    return User.objects.create_user(email=email, password='pass')


def _compute(scheme, period, actor=None):
    run = PayoutService.start_run(scheme.pk, period.pk, actor=actor)
    result = PayoutService.compute_run(run.pk, triggered_by=actor)
    run.refresh_from_db()
    return run, result


@pytest.mark.django_db
class TestCompute:
    def test_t1_normal_three_kpis(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])

        run, result = _compute(scheme, period)
        payout = Payout.objects.get(run=run, entity=tree['ase1'])
        assert payout.total_payout == D('71000.00')
        assert payout.total_multiplier == D('0.7100')
        assert [li.line_payout for li in payout.line_items.all()] == [
            D('40000.00'), D('15000.00'), D('16000.00'),
        ]
        assert run.status == PayoutRun.COMPUTED
        assert result['total_payout'] == '71000.00'

    def test_t2_overachiever(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'], primary='128', eco='105', msl='110')
        run, _ = _compute(scheme, period)
        assert Payout.objects.get(run=run).total_payout == D('115000.00')

    def test_t3_exception_sales_default_1x(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        exc = mk_exception(tree['ase1'], period, sales='default_1x')
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.total_payout == D('81000.00')
        assert payout.exception_id == exc.pk
        line = payout.line_items.get(kpi_code='PRIMARY')
        assert line.treatment == 'default_1x'
        assert line.applied_multiplier == D('1.000')

    def test_t4_exception_all_zero(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        mk_exception(tree['ase1'], period, sales='zero', execution='zero')
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.total_payout == D('0.00')
        assert payout.line_items.count() == 3
        assert all(li.treatment == 'zero' for li in payout.line_items.all())

    def test_t5_gatekeeper_fail(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis, gk_kpi=kpis['MSL'], gk_threshold='80')
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'], msl='75')
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.gross_payout == D('65000.00')
        assert payout.total_payout == D('0.00')
        assert payout.gatekeeper_status == 'failed'

    def test_t6_gatekeeper_exempted(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis, gk_kpi=kpis['MSL'], gk_threshold='80')
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'], msl='75')
        mk_exception(tree['ase1'], period, gatekeeper='exempted')
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.total_payout == D('65000.00')
        assert payout.gatekeeper_status == 'exempted'

    def test_t7_pending_exception_ignored(self, tree, period, ase_type, kpis):
        from apps.incentives.models import PayoutException
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        mk_exception(tree['ase1'], period, sales='zero', execution='zero',
                     status=PayoutException.PENDING)
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.total_payout == D('71000.00')
        assert payout.exception_id is None

    def test_t8_zero_and_missing_vp(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period, amount='0.00')
        mk_baseline_achievements(period, kpis, tree['ase1'])
        mk_baseline_achievements(period, kpis, tree['ase2'])  # no VP row for ase2
        run, result = _compute(scheme, period)
        assert Payout.objects.get(run=run, entity=tree['ase1']).total_payout == D('0.00')
        assert not Payout.objects.filter(run=run, entity=tree['ase2']).exists()
        assert run.error_count == 1
        assert result['errors'][0]['code'] == 'no_variable_pay'
        assert result['errors'][0]['entity_id'] == tree['ase2'].pk

    def test_t9_last_tier_unlimited(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'], primary='250')
        run, _ = _compute(scheme, period)
        line = Payout.objects.get(run=run).line_items.get(kpi_code='PRIMARY')
        assert line.line_payout == D('65000.00')
        assert line.tier_max is None

    def test_t14_proration(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period, eligible_days=10)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        assert payout.proration_factor == D('0.5000')
        assert payout.eligible_vp == D('50000.00')
        assert payout.total_payout == D('35500.00')

    def test_t19_eligibility(self, tree, period, ase_type, kpis, gt):
        from apps.hierarchy.models import Channel
        scheme = mk_scheme(ase_type, kpis, channel=gt)
        other = Channel.objects.create(name='Modern Trade', code='MT')
        tree['ase2'].channel = other
        tree['ase2'].save()
        mk_vp(tree['ase1'], period)
        mk_vp(tree['ase2'], period)
        mk_vp(tree['asm'], period)  # wrong type — not targeted
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run, _ = _compute(scheme, period)
        assert run.entities_processed == 1
        assert set(Payout.objects.filter(run=run).values_list('entity__code', flat=True)) == {'ASE1'}

    def test_channel_dimensioned_achievements(self, tree, period, ase_type, kpis, gt):
        """Achievements stored per-channel (no overall row) still drive payouts:
        an unscoped scheme aggregates channel rows; a channel-scoped scheme uses
        only its channel's row."""
        from decimal import Decimal as DD
        from apps.achievements.models import Achievement

        def channel_achievement(kpi, pct, channel):
            target = DD('100000')
            return Achievement.objects.create(
                target_period=period, kpi=kpi, entity=tree['ase1'], channel=channel,
                target_value=target, achieved_value=target * DD(pct) / 100,
                achievement_pct=DD(pct),
            )

        for code, pct in (('PRIMARY', '85'), ('ECO', '60'), ('MSL', '90')):
            channel_achievement(kpis[code], pct, gt)

        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        run, _ = _compute(scheme, period)
        assert Payout.objects.get(run=run).total_payout == D('71000.00')

        # Channel-scoped scheme to another channel ignores GT rows → all 0%
        from apps.hierarchy.models import Channel
        mt = Channel.objects.create(name='Modern Trade', code='MT')
        tree['ase1'].channel = mt
        tree['ase1'].save()
        scheme_mt = mk_scheme(ase_type, kpis, code='FF_MT', channel=mt)
        run2, _ = _compute(scheme_mt, period)
        assert Payout.objects.get(run=run2).total_payout == D('0.00')

    def test_t20_missing_achievement(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'], eco=None)
        run, _ = _compute(scheme, period)
        payout = Payout.objects.get(run=run)
        eco = payout.line_items.get(kpi_code='ECO')
        assert eco.achievement_pct == D('0.00')
        assert eco.line_payout == D('0.00')
        assert payout.total_payout == D('56000.00')

    def test_t22_computation_log_snapshot(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis, overall_cap='150.00')
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run, result = _compute(scheme, period)
        log = ComputationLog.objects.get(pk=result['computation_id'])
        snap = log.config_snapshot
        assert snap['scheme_code'] == 'FF_TEST'
        assert snap['scheme_version'] == 1
        assert snap['overall_cap_pct'] == '150.00'
        assert snap['period_working_days'] == 20
        assert len(snap['kpis']) == 3
        assert len(snap['kpis'][0]['tiers']) == 5
        payout = Payout.objects.get(run=run)
        assert payout.computation_id == log.pk
        assert run.computation_log_id == log.pk


@pytest.mark.django_db
class TestLifecycle:
    def test_t17_full_lifecycle(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        maker, checker = _user('maker@x.com'), _user('checker@x.com')

        run, _ = _compute(scheme, period, actor=maker)
        run = PayoutService.submit_for_review(run, maker)
        assert run.status == PayoutRun.UNDER_REVIEW

        with pytest.raises(BusinessError, match='maker-checker'):
            PayoutService.approve(run, maker)

        run = PayoutService.approve(run, checker)
        assert run.status == PayoutRun.APPROVED
        assert run.approved_by == checker

        run = PayoutService.mark_paid(run, checker, payment_ref='PAY-001')
        assert run.status == PayoutRun.PAID
        assert run.payment_ref == 'PAY-001'

    def test_t17_reject_back_to_computed(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        maker, checker = _user('m@x.com'), _user('c@x.com')
        run, _ = _compute(scheme, period, actor=maker)
        run = PayoutService.submit_for_review(run, maker)
        run = PayoutService.reject(run, checker, 'wrong tier grid')
        assert run.status == PayoutRun.COMPUTED
        assert run.rejection_reason == 'wrong tier grid'
        assert run.submitted_by is None

    def test_t17_recompute_supersedes(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run1, _ = _compute(scheme, period)
        run2, _ = _compute(scheme, period)
        run1.refresh_from_db()
        assert run1.status == PayoutRun.SUPERSEDED
        assert run2.status == PayoutRun.COMPUTED
        # Old payouts retained under the old run
        assert Payout.objects.filter(run=run1).count() == 1
        assert Payout.objects.filter(run=run2).count() == 1

    def test_t18_blocking_statuses(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        maker, checker = _user('m2@x.com'), _user('c2@x.com')
        run, _ = _compute(scheme, period, actor=maker)
        PayoutService.submit_for_review(run, maker)
        with pytest.raises(BusinessError, match='under_review'):
            PayoutService.start_run(scheme.pk, period.pk)
        run.refresh_from_db()
        PayoutService.approve(run, checker)
        with pytest.raises(BusinessError, match='approved'):
            PayoutService.start_run(scheme.pk, period.pk)

    def test_t18_approved_totals_immutable_to_later_exception(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        maker, checker = _user('m3@x.com'), _user('c3@x.com')
        run, _ = _compute(scheme, period, actor=maker)
        PayoutService.submit_for_review(run, maker)
        PayoutService.approve(run, checker)
        # An exception approved AFTER computation does not rewrite stored payouts
        mk_exception(tree['ase1'], period, sales='zero', execution='zero')
        assert Payout.objects.get(run=run).total_payout == D('71000.00')

    def test_invalid_transitions(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run, _ = _compute(scheme, period)
        u = _user('x@x.com')
        with pytest.raises(BusinessError):
            PayoutService.approve(run, u)        # computed → approve invalid
        with pytest.raises(BusinessError):
            PayoutService.mark_paid(run, u)      # computed → paid invalid

    def test_non_monthly_period_rejected(self, tree, ase_type, kpis):
        from datetime import date
        from apps.targets.models import TargetPeriod
        annual = TargetPeriod.objects.create(
            name='FY 2026-27', code='FY27-ANN', period_type=TargetPeriod.ANNUAL,
            start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        )
        scheme = mk_scheme(ase_type, kpis)
        with pytest.raises(BusinessError, match='monthly'):
            PayoutService.start_run(scheme.pk, annual.pk)
