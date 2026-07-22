"""Incentives API — RBAC scoping (T21), run lifecycle endpoints, exception approval."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.incentives.services import PayoutService

from .conftest import mk_baseline_achievements, mk_exception, mk_scheme, mk_vp

BASE = '/api/v1/incentives/'


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


_role_seq = iter(range(10000))


def _user(email, *, entity=None, perms=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        code = f'r{next(_role_seq)}'
        role = Role.objects.create(code=code, name=code, permissions=perms)
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
    return u


@pytest.fixture
def computed(tree, period, ase_type, kpis):
    scheme = mk_scheme(ase_type, kpis)
    mk_vp(tree['ase1'], period)
    mk_vp(tree['ase2'], period)
    mk_baseline_achievements(period, kpis, tree['ase1'])
    mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
    run = PayoutService.start_run(scheme.pk, period.pk)
    PayoutService.compute_run(run.pk)
    run.refresh_from_db()
    return {'scheme': scheme, 'run': run, **tree}


@pytest.mark.django_db
class TestPayoutScoping:
    def test_ase_sees_only_own(self, computed, period):
        u = _user('ase1@x.com', entity=computed['ase1'], perms={'final_payout': 'own_only'})
        resp = _client(u).get(f'{BASE}payouts/', {'period': period.id})
        assert resp.status_code == 200
        assert {r['entity_code'] for r in resp.data['results']} == {'ASE1'}

    def test_team_grant_is_clamped_to_none(self, computed, period):
        """Payout confidentiality: 'team' on final_payout is structurally impossible —
        even a directly-seeded grant resolves to none, so the manager gets 403."""
        u = _user('asm@x.com', entity=computed['asm'], perms={'final_payout': 'team'})
        resp = _client(u).get(f'{BASE}payouts/', {'period': period.id})
        assert resp.status_code == 403

    def test_finance_sees_all(self, computed, period):
        u = _user('fin@x.com', perms={'final_payout': 'view_all'})
        resp = _client(u).get(f'{BASE}payouts/', {'period': period.id})
        assert {r['entity_code'] for r in resp.data['results']} == {'ASE1', 'ASE2'}

    def test_breakdown_denied_outside_subtree(self, computed, period):
        from apps.incentives.models import Payout
        other = Payout.objects.get(run=computed['run'], entity=computed['ase2'])
        u = _user('ase1b@x.com', entity=computed['ase1'], perms={'final_payout': 'own_only'})
        resp = _client(u).get(f'{BASE}payouts/{other.pk}/')
        assert resp.status_code == 404  # scoped queryset → not found

    def test_breakdown_has_line_items(self, computed, period):
        from apps.incentives.models import Payout
        own = Payout.objects.get(run=computed['run'], entity=computed['ase1'])
        u = _user('ase1c@x.com', entity=computed['ase1'], perms={'final_payout': 'own_only'})
        resp = _client(u).get(f'{BASE}payouts/{own.pk}/')
        assert resp.status_code == 200
        assert len(resp.data['line_items']) == 3
        assert resp.data['total_payout'] == '71000.00'
        assert resp.data['line_items'][0]['kpi_code'] == 'PRIMARY'

    def test_summary_respects_scope(self, computed, period):
        # Authorized (view_all) summary aggregates everything…
        fin = _user('fin2@x.com', perms={'final_payout': 'view_all'})
        resp = _client(fin).get(f'{BASE}payouts/summary/', {'period': period.id})
        assert resp.status_code == 200
        assert resp.data['entities'] == 2
        assert resp.data['total_payout'] == '186000.00'  # 71000 + 115000
        # …while a team-level grant is clamped and gets nothing.
        asm = _user('asm2@x.com', entity=computed['asm'], perms={'final_payout': 'team'})
        assert _client(asm).get(f'{BASE}payouts/summary/', {'period': period.id}).status_code == 403


def _computed_run(scheme, period):
    """Standalone computed run via the service layer — the API no longer creates
    final runs outside a cycle (month-close owns final computes)."""
    run = PayoutService.start_run(scheme.pk, period.pk)
    PayoutService.compute_run(run.pk)
    run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestRunLifecycleApi:
    def test_compute_endpoint_is_gone(self, tree, period, ase_type, kpis):
        # Regression: the standalone final-compute API bypassed the month-close.
        scheme = mk_scheme(ase_type, kpis)
        admin = _user('ops0@x.com', perms={'final_payout': 'full'})
        resp = _client(admin).post(f'{BASE}payout-runs/compute/',
                                   {'scheme_id': scheme.pk, 'period_id': period.pk})
        assert resp.status_code in (404, 405)  # route no longer exists

    def test_submit_requires_planning_admin(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        run = _computed_run(scheme, period)
        u = _user('rep@x.com', entity=tree['ase1'], perms={'final_payout': 'own_only'})
        resp = _client(u).post(f'{BASE}payout-runs/{run.pk}/submit/')
        assert resp.status_code == 403

    def test_lifecycle(self, tree, period, ase_type, kpis):
        scheme = mk_scheme(ase_type, kpis)
        mk_vp(tree['ase1'], period)
        mk_baseline_achievements(period, kpis, tree['ase1'])
        admin = _user('ops@x.com', perms={'final_payout': 'full'})
        approver = _user('fin2@x.com',
                         perms={'final_payout': 'view_all', 'payout_approve': 'full'})

        run_id = _computed_run(scheme, period).pk

        resp = _client(admin).post(f'{BASE}payout-runs/{run_id}/submit/')
        assert resp.status_code == 200
        assert resp.data['status'] == 'under_review'

        # Submitter cannot approve even with payout_approve
        admin_role = Role.objects.create(code='r_appr_extra', name='r_appr_extra',
                                         permissions={'payout_approve': 'full'})
        UserRole.objects.create(user=admin, role=admin_role, effective_from=date.today())
        resp = _client(admin).post(f'{BASE}payout-runs/{run_id}/approve/')
        assert resp.status_code == 422

        # Approver without payout_approve is denied
        viewer = _user('viewer@x.com', perms={'final_payout': 'view_all'})
        resp = _client(viewer).post(f'{BASE}payout-runs/{run_id}/approve/')
        assert resp.status_code == 403

        resp = _client(approver).post(f'{BASE}payout-runs/{run_id}/approve/')
        assert resp.status_code == 200
        assert resp.data['status'] == 'approved'

        resp = _client(approver).post(f'{BASE}payout-runs/{run_id}/mark-paid/',
                                      {'payment_ref': 'NEFT-42'})
        assert resp.status_code == 200
        assert resp.data['status'] == 'paid'
        assert resp.data['payment_ref'] == 'NEFT-42'

    def test_runs_are_payout_admin_only(self, computed, period):
        # Runs carry scheme-level totals and no entity anchor → view_all+ only.
        # own_only holders (field ICs, partners) see their own payout via /payouts/,
        # never the org-wide run list.
        own = _user('rep2@x.com', entity=computed['ase1'], perms={'final_payout': 'own_only'})
        assert _client(own).get(f'{BASE}payout-runs/', {'period': period.id}).status_code == 403

        admin = _user('payadmin@x.com', perms={'final_payout': 'view_all'})
        resp = _client(admin).get(f'{BASE}payout-runs/', {'period': period.id})
        assert resp.status_code == 200
        assert len(resp.data['results']) == 1


@pytest.mark.django_db
class TestSchemeApi:
    def _payload(self, ase_type, kpis):
        grid = [
            {'min_achievement_pct': '0', 'max_achievement_pct': '100', 'multiplier': '0.5'},
            {'min_achievement_pct': '100', 'max_achievement_pct': None, 'multiplier': '1.0'},
        ]
        return {
            'name': 'API Scheme', 'code': 'API_SCHEME',
            'target_entity_type': ase_type.pk,
            'kpis': [
                {'kpi': kpis['PRIMARY'].pk, 'incentive_category': 'sales',
                 'weightage': '100.00', 'tiers': grid},
            ],
        }

    def test_create_and_versioned_update(self, ase_type, kpis):
        admin = _user('cfg@x.com', perms={'scheme_management': 'full'})
        c = _client(admin)
        resp = c.post(f'{BASE}schemes/', self._payload(ase_type, kpis), format='json')
        assert resp.status_code == 201, resp.data
        scheme_id = resp.data['id']
        assert resp.data['version'] == 1

        payload = self._payload(ase_type, kpis)
        payload['kpis'][0]['weightage'] = '100.00'
        payload['name'] = 'API Scheme v2'
        resp = c.put(f'{BASE}schemes/{scheme_id}/', payload, format='json')
        assert resp.status_code == 200
        assert resp.data['version'] == 2

        resp = c.get(f"{BASE}schemes/{resp.data['id']}/versions/")
        assert [row['version'] for row in resp.data] == [2, 1]

    def test_validate_endpoint(self, ase_type, kpis):
        admin = _user('cfg2@x.com', perms={'scheme_management': 'full'})
        payload = self._payload(ase_type, kpis)
        payload['kpis'][0]['weightage'] = '90.00'
        resp = _client(admin).post(f'{BASE}schemes/validate/', payload, format='json')
        assert resp.status_code == 200
        assert resp.data['valid'] is False
        assert any('100' in e for e in resp.data['errors'])

    def test_scheme_requires_permission(self, ase_type, kpis, tree):
        u = _user('norole@x.com', entity=tree['ase1'], perms={'final_payout': 'own_only'})
        resp = _client(u).get(f'{BASE}schemes/')
        assert resp.status_code == 403


@pytest.mark.django_db
class TestExceptionApi:
    def test_raise_and_approve_flow(self, tree, period):
        maker = _user('mk@x.com', entity=tree['asm'],
                      perms={'exception_management': 'team'})
        resp = _client(maker).post(f'{BASE}exceptions/', {
            'entity': tree['ase1'].pk, 'target_period': period.pk,
            'category': 'medical_leave', 'sales_kpi_action': 'default_1x',
            'execution_kpi_action': 'actual_performance',
            'gatekeeper_action': 'no_exemption', 'reason': '15 days leave',
        })
        assert resp.status_code == 201, resp.data
        exc_id = resp.data['id']
        assert resp.data['status'] == 'pending'

        # Approve needs exception_approve
        resp = _client(maker).post(f'{BASE}exceptions/{exc_id}/approve/')
        assert resp.status_code == 403

        checker = _user('ck@x.com', perms={'exception_management': 'full',
                                           'exception_approve': 'full'})
        resp = _client(checker).post(f'{BASE}exceptions/{exc_id}/approve/')
        assert resp.status_code == 200
        assert resp.data['status'] == 'approved'

    def test_exception_scoped_to_subtree(self, tree, period):
        mk_exception(tree['ase1'], period)
        mk_exception(tree['ase2'], period)
        u = _user('own@x.com', entity=tree['ase1'],
                  perms={'exception_management': 'own_only'})
        resp = _client(u).get(f'{BASE}exceptions/', {'period': period.id})
        assert {r['entity_code'] for r in resp.data['results']} == {'ASE1'}

    def test_patch_to_clashing_entity_is_422_not_500(self, tree, period):
        from apps.incentives.models import PayoutException
        mk_exception(tree['ase2'], period, status=PayoutException.PENDING)
        exc = mk_exception(tree['ase1'], period, status=PayoutException.PENDING)
        u = _user('editor@x.com', entity=tree['asm'],
                  perms={'exception_management': 'team'})
        resp = _client(u).patch(f'{BASE}exceptions/{exc.pk}/',
                                {'entity': tree['ase2'].pk})
        assert resp.status_code == 422
        exc.refresh_from_db()
        assert exc.entity_id == tree['ase1'].pk  # unchanged

    def test_patch_non_pending_rejected(self, tree, period):
        exc = mk_exception(tree['ase1'], period)  # approved
        u = _user('editor2@x.com', perms={'exception_management': 'full'})
        resp = _client(u).patch(f'{BASE}exceptions/{exc.pk}/', {'reason': 'too late'})
        assert resp.status_code == 422
