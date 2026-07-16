"""PayoutCycle — the month-close process (P2, payout & achievements revamp).

Covers readiness gating, the audited override, finalize freezing achievements, the
final-requires-finalized-cycle rule, run kinds (estimate never submittable, estimate
auto-supersede) and the dashboard preferring final over estimate.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement
from apps.achievements.services import AchievementService, DashboardService
from apps.audit.models import AuditLog
from apps.incentives.models import PayoutCycle, PayoutRun
from apps.incentives.services import PayoutCycleService, PayoutService
from apps.core.exceptions import BusinessError
from apps.targets.models import TargetPeriod

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp

D = Decimal


def _su(email='su@x.com'):
    from apps.accounts.models import User
    return User.objects.create_superuser(email=email, password='pass')


def _ready_cycle(period, tree, ase_type, kpis):
    """A period whose readiness is green: scheme + VP for both ASEs + fresh achievements,
    no pending exceptions, no plans (warning, not red)."""
    scheme = mk_scheme(ase_type, kpis)
    mk_vp(tree['ase1'], period)
    mk_vp(tree['ase2'], period)
    mk_baseline_achievements(period, kpis, tree['ase1'])
    mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
    # Stamp computed_at so the achievements-fresh readiness check reads green (these
    # baselines are inserted directly, not through the compute pass).
    from django.utils import timezone
    Achievement.objects.filter(target_period=period).update(computed_at=timezone.now())
    cycle = PayoutCycleService.open_cycle(period)
    return scheme, cycle


@pytest.mark.django_db
class TestReadiness:
    def test_pending_exception_makes_readiness_red(self, tree, period, ase_type, kpis):
        from .conftest import mk_exception
        from apps.incentives.models import PayoutException

        _ready_cycle(period, tree, ase_type, kpis)
        mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        snapshot = PayoutCycleService.readiness(PayoutCycle.objects.get(target_period=period))
        exc_check = next(c for c in snapshot['checks'] if c['key'] == 'exceptions_decided')
        assert exc_check['status'] == 'red'
        assert snapshot['is_ready'] is False

    def test_missing_variable_pay_is_red(self, tree, period, ase_type, kpis):
        mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)  # ase2 has none
        cycle = PayoutCycleService.open_cycle(period)
        snapshot = PayoutCycleService.readiness(cycle)
        vp_check = next(c for c in snapshot['checks'] if c['key'] == 'variable_pay')
        assert vp_check['status'] == 'red'
        assert vp_check['count'] == 1


@pytest.mark.django_db
class TestFinalize:
    def test_red_readiness_blocks_finalize(self, tree, period, ase_type, kpis):
        mk_scheme(ase_type, kpis)  # no VP → red
        cycle = PayoutCycleService.open_cycle(period)
        with pytest.raises(BusinessError, match='Readiness checks are not green'):
            PayoutCycleService.finalize(cycle, actor=_su())

    def test_override_requires_reason_and_is_audited(self, tree, period, ase_type, kpis):
        mk_scheme(ase_type, kpis)  # no VP → red
        cycle = PayoutCycleService.open_cycle(period)
        with pytest.raises(BusinessError, match='override reason is required'):
            PayoutCycleService.finalize(cycle, actor=_su(), override=True)

        cycle = PayoutCycle.objects.get(pk=cycle.pk)
        PayoutCycleService.finalize(cycle, actor=_su('su2@x.com'), override=True,
                                    override_reason='DMS backfill lands tomorrow; pay now.')
        cycle.refresh_from_db()
        assert cycle.readiness_overridden is True
        assert cycle.finalized_at is not None
        assert AuditLog.objects.filter(
            entity_type='incentives.PayoutCycle', entity_id=cycle.pk, action='readiness_override',
        ).exists()

    def test_finalize_freezes_achievements(self, tree, period, ase_type, kpis):
        _, cycle = _ready_cycle(period, tree, ase_type, kpis)
        # Provisional before finalize (period is PUBLISHED, not frozen).
        assert Achievement.objects.filter(target_period=period, is_provisional=True).exists()

        PayoutCycleService.finalize(cycle, actor=_su())
        cycle.refresh_from_db()
        assert cycle.status == PayoutCycle.COMPUTING
        assert cycle.finalized_at is not None
        assert not Achievement.objects.filter(target_period=period, is_provisional=True).exists()
        # Freezing achievements also locks the period's targets (derived status).
        period.refresh_from_db()
        assert period.status == TargetPeriod.LOCKED

    def test_estimate_recompute_after_finalize_keeps_rows_frozen(self, tree, period, ase_type, kpis):
        """A recompute must not un-freeze finalized achievements."""
        _, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.finalize(cycle, actor=_su())
        AchievementService.compute_period(period.id)  # a later nightly-style recompute
        assert not Achievement.objects.filter(target_period=period, is_provisional=True).exists()


@pytest.mark.django_db
class TestRunKinds:
    def test_compute_requires_finalized_cycle(self, tree, period, ase_type, kpis):
        _, cycle = _ready_cycle(period, tree, ase_type, kpis)
        with pytest.raises(BusinessError, match='Finalize the cycle'):
            PayoutCycleService.compute(cycle, actor=_su())

    def test_full_close_computes_final_runs(self, tree, period, ase_type, kpis):
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.finalize(cycle, actor=_su())
        result = PayoutCycleService.compute(cycle, actor=_su('su2@x.com'))
        cycle.refresh_from_db()

        assert cycle.status == PayoutCycle.UNDER_REVIEW
        assert len(result['run_ids']) == 1
        run = PayoutRun.objects.get(pk=result['run_ids'][0])
        assert run.kind == PayoutRun.FINAL
        assert run.cycle_id == cycle.pk
        assert cycle.total_payout == run.total_payout

    def test_estimate_never_submittable(self, tree, period, ase_type, kpis):
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.compute_estimates(cycle)
        est = PayoutRun.objects.get(target_period=period, kind=PayoutRun.ESTIMATE)
        est.status = PayoutRun.COMPUTED
        est.save(update_fields=['status'])
        with pytest.raises(BusinessError, match='Only final payout runs enter review'):
            PayoutService.submit_for_review(est, _su())

    def test_estimate_compute_sends_no_payee_notifications(self, tree, period, ase_type, kpis):
        """The nightly estimate must not spam payees with 'payout ready'; the cycle's
        final run still notifies them."""
        from apps.accounts.models import User
        from apps.notifications.models import Notification

        User.objects.create_user(email='deepa@x.com', password='pass', entity=tree['ase1'])
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.compute_estimates(cycle)
        assert Notification.objects.filter(code='payout_ready').count() == 0

        PayoutCycleService.finalize(cycle, actor=_su())
        PayoutCycleService.compute(cycle, actor=_su('su2@x.com'))
        assert Notification.objects.filter(code='payout_ready').count() == 1

    def test_cycle_run_not_individually_submittable(self, tree, period, ase_type, kpis):
        """A cycle-governed final run must go through the cycle's submit/approve — an
        individually-submitted run would be stranded by the cycle sweep."""
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.finalize(cycle, actor=_su())
        result = PayoutCycleService.compute(cycle, actor=_su('su2@x.com'))
        run = PayoutRun.objects.get(pk=result['run_ids'][0])
        with pytest.raises(BusinessError, match='belongs to a payout cycle'):
            PayoutService.submit_for_review(run, _su('su3@x.com'))

    def test_estimate_reruns_supersede(self, tree, period, ase_type, kpis):
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.compute_estimates(cycle)
        PayoutCycleService.compute_estimates(cycle)  # next night
        live = PayoutRun.objects.filter(
            target_period=period, kind=PayoutRun.ESTIMATE,
        ).exclude(status=PayoutRun.SUPERSEDED)
        assert live.count() == 1
        assert PayoutRun.objects.filter(
            target_period=period, kind=PayoutRun.ESTIMATE, status=PayoutRun.SUPERSEDED,
        ).count() == 1

    def test_estimate_and_final_coexist(self, tree, period, ase_type, kpis):
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.compute_estimates(cycle)
        PayoutCycleService.finalize(cycle, actor=_su())
        PayoutCycleService.compute(cycle, actor=_su('su2@x.com'))
        # Both kinds are live for the same scheme × period.
        kinds = set(PayoutRun.objects.filter(target_period=period).exclude(
            status=PayoutRun.SUPERSEDED,
        ).values_list('kind', flat=True))
        assert kinds == {PayoutRun.ESTIMATE, PayoutRun.FINAL}


@pytest.mark.django_db
class TestDashboardPrefersFinal:
    def test_dashboard_prefers_final_over_estimate(self, tree, period, ase_type, kpis):
        scheme, cycle = _ready_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.compute_estimates(cycle)

        su = _su()
        data = DashboardService.build(su, period, entity=tree['ase1'])
        assert data['summary']['payout_kind'] == 'estimate'
        assert data['summary']['estimated_payout'] == '71000.00'

        PayoutCycleService.finalize(cycle, actor=su)
        PayoutCycleService.compute(cycle, actor=_su('su2@x.com'))
        data = DashboardService.build(su, period, entity=tree['ase1'])
        assert data['summary']['payout_kind'] == 'final'
        assert data['summary']['estimated_payout'] == '71000.00'
