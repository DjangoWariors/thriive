"""T22 — the achievements dashboard picks up payout data once a run is live,
and degrades gracefully (Nones) before any run exists."""
from decimal import Decimal

import pytest

from apps.achievements.services import DashboardService
from apps.incentives.services import PayoutService

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp

D = Decimal


def _su():
    from apps.accounts.models import User
    return User.objects.create_superuser(email='su@x.com', password='pass')


@pytest.mark.django_db
class TestDashboardIntegration:
    def test_graceful_degrade_before_any_run(self, tree, period, kpis):
        mk_baseline_achievements(period, kpis, tree['ase1'])
        data = DashboardService.build(_su(), period, entity=tree['ase1'])
        assert data['modules']['incentives'] is False
        assert data['summary']['estimated_payout'] is None
        assert all(c['multiplier'] is None for c in data['kpi_cards'])

    def test_dashboard_filled_after_compute(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_vp(tree['ase2'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
        run = PayoutService.start_run(scheme.pk, period.pk)
        PayoutService.compute_run(run.pk)

        su = _su()
        # Rep view: estimated payout + per-KPI multiplier/weight
        data = DashboardService.build(su, period, entity=tree['ase1'])
        assert data['modules']['incentives'] is True
        assert data['summary']['estimated_payout'] == '71000.00'
        cards = {c['kpi_code']: c for c in data['kpi_cards']}
        assert cards['PRIMARY']['multiplier'] == '0.800'
        assert cards['PRIMARY']['weight_pct'] == '50.00'

        # Manager view: child ranking carries payouts
        data = DashboardService.build(su, period, entity=tree['asm'])
        payouts = {r['entity_code']: r['payout'] for r in data['child_ranking']}
        assert payouts == {'ASE1': '71000.00', 'ASE2': '115000.00'}

    def test_manager_keeps_ranking_but_never_sees_team_payouts(self, tree, period, ase_type, kpis):
        """Payout confidentiality (RFP matrix): a manager with team-level achievement
        access and own_only payout access gets the achievement ranking with payout
        amounts withheld — and no estimated payout for a drilled-down child."""
        from datetime import date
        from apps.accounts.models import Role, User, UserRole

        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run = PayoutService.start_run(scheme.pk, period.pk)
        PayoutService.compute_run(run.pk)

        manager = User.objects.create_user(email='asm@x.com', entity=tree['asm'])
        role = Role.objects.create(code='asm_conf', name='ASM', permissions={
            'dashboard': 'team', 'achievement_view': 'team', 'final_payout': 'own_only',
        })
        UserRole.objects.create(user=manager, role=role, effective_from=date.today())

        data = DashboardService.build(manager, period, entity=tree['asm'])
        ranking = {r['entity_code']: r for r in data['child_ranking']}
        assert ranking['ASE1']['achievement_pct'] is not None  # achievements visible
        assert all(r['payout'] is None for r in ranking.values())  # payouts withheld

        # Drilling into a child never leaks the child's payout either.
        drilled = DashboardService.build(manager, period, entity=tree['ase1'])
        assert drilled['summary']['estimated_payout'] is None

        # The rep still sees their own number.
        rep = User.objects.create_user(email='ase1@x.com', entity=tree['ase1'])
        UserRole.objects.create(user=rep, role=role, effective_from=date.today())
        own = DashboardService.build(rep, period, entity=tree['ase1'])
        assert own['summary']['estimated_payout'] == '71000.00'
