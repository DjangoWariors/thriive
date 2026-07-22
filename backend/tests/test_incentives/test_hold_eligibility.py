"""can_hold / can_release — the backend eligibility flags the UI reads so it never offers
a hold/release the API refuses.

Locks the predicate <-> action agreement and covers the adjustment-run case a naive
"the run is computed" proxy gets wrong (an adjustment run also rests at 'computed' in an
under_review cycle, yet kind != FINAL makes it un-holdable).
"""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.core.exceptions import BusinessError
from apps.incentives.models import Payout, PayoutCycle, PayoutRun
from apps.incentives.services import PayoutCycleService, PayoutService

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp
from .test_cycle import _su
from .test_cycle_review import _computed_cycle
from .test_cycle_adjustment import _closed_cycle, _july, _restate, _stamp_computed


def _payout(cycle, entity):
    return Payout.objects.get(run__cycle=cycle, entity=entity)


@pytest.mark.django_db
class TestHoldEligibilityMatrix:
    def test_final_under_review_unheld(self, tree, period, ase_type, kpis):
        p = _payout(_computed_cycle(period, tree, ase_type, kpis), tree['ase1'])
        assert PayoutCycleService.can_hold(p) is True
        assert PayoutCycleService.can_release(p) is False

    def test_final_under_review_held(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = _payout(cycle, tree['ase1'])
        PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='dispute')
        p.refresh_from_db()
        assert PayoutCycleService.can_hold(p) is False   # already held → offer Release
        assert PayoutCycleService.can_release(p) is True

    def test_final_approved_neither(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        PayoutCycleService.submit_cycle(cycle, actor=_su('m@x.com'))
        PayoutCycleService.approve_cycle(cycle, actor=_su('c@x.com'))
        p = _payout(cycle, tree['ase1'])
        p.refresh_from_db()
        assert PayoutCycleService.can_hold(p) is False
        assert PayoutCycleService.can_release(p) is False

    def test_final_disbursed_neither(self, tree, period, ase_type, kpis):
        _cycle, run = _closed_cycle(period, tree, ase_type, kpis)  # disbursed + closed
        p = Payout.objects.get(run=run, entity=tree['ase1'])
        assert PayoutCycleService.can_hold(p) is False
        assert PayoutCycleService.can_release(p) is False

    def test_no_cycle_neither(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run = PayoutService.start_run(scheme.pk, period.pk)  # cycle = None
        PayoutService.compute_run(run.pk)
        p = Payout.objects.get(run=run, entity=tree['ase1'])
        assert p.run.cycle_id is None
        assert PayoutCycleService.can_hold(p) is False
        assert PayoutCycleService.can_release(p) is False

    def test_adjustment_under_review_not_holdable(self, tree, period, ase_type, kpis):
        """The residual hole: an adjustment run also sits at 'computed' in an under_review
        cycle (so a run_status proxy would wrongly offer Hold), but kind != FINAL → refused."""
        _june, june_run = _closed_cycle(period, tree, ase_type, kpis)
        _restate(period, kpis['PRIMARY'], tree['ase1'], 120)  # arrears for ase1
        july = _july(period)
        july_cycle = PayoutCycleService.open_cycle(july)
        result = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=_su('adj@x.com'))
        # Drive July to under_review; the adjustment run rides along at 'computed'.
        mk_vp(tree['ase1'], july)
        _stamp_computed(july)
        PayoutCycleService.finalize(july_cycle, actor=_su('adj_jm@x.com'), override=True,
                                    override_reason='no july targets')
        july_cycle.refresh_from_db()
        PayoutCycleService.compute(july_cycle, actor=_su('adj_jc@x.com'))
        july_cycle.refresh_from_db()

        adj = Payout.objects.get(run_id=result['run_id'], entity=tree['ase1'])
        assert adj.run.kind == PayoutRun.ADJUSTMENT
        assert adj.run.status == PayoutRun.COMPUTED            # what a naive proxy keys on
        assert july_cycle.status == PayoutCycle.UNDER_REVIEW
        assert PayoutCycleService.can_hold(adj) is False       # kind guard — the fix


@pytest.mark.django_db
class TestPredicateMirrorsAction:
    """Where a predicate is False for a state-guard reason, the action raises; where True,
    it is accepted. Keeps the flags honest against the real enforcement."""

    def test_true_then_hold_accepted(self, tree, period, ase_type, kpis):
        p = _payout(_computed_cycle(period, tree, ase_type, kpis), tree['ase1'])
        assert PayoutCycleService.can_hold(p) is True
        PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='ok')
        p.refresh_from_db()
        assert p.hold_status == Payout.HOLD_HELD
        assert PayoutCycleService.can_release(p) is True
        PayoutCycleService.release_payout(p, actor=_su('m2@x.com'))
        p.refresh_from_db()
        assert p.hold_status == Payout.HOLD_RELEASED

    def test_false_then_hold_refused(self, tree, period, ase_type, kpis):
        _cycle, run = _closed_cycle(period, tree, ase_type, kpis)  # disbursed
        p = Payout.objects.get(run=run, entity=tree['ase1'])
        assert PayoutCycleService.can_hold(p) is False
        with pytest.raises(BusinessError, match='under review'):
            PayoutCycleService.hold_payout(p, actor=_su('m@x.com'), reason='late')


@pytest.mark.django_db
class TestDetailApiExposesFlags:
    def test_payout_detail_carries_flags(self, tree, period, ase_type, kpis):
        cycle = _computed_cycle(period, tree, ase_type, kpis)
        p = _payout(cycle, tree['ase1'])
        u = User.objects.create_superuser(email='fin@x.com', password='pass')
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(u).access_token}')
        resp = c.get(f'/api/v1/incentives/payouts/{p.pk}/')
        assert resp.status_code == 200
        assert resp.data['can_hold'] is True
        assert resp.data['can_release'] is False
