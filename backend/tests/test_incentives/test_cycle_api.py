"""Payout cycle API — the month-close workspace endpoints (P4).

Happy-path lifecycle through the HTTP surface, cycle-level maker-checker enforcement,
and the held-excluded-from-register guarantee.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.incentives.models import Payout, PayoutCycle

from .conftest import mk_baseline_achievements, mk_scheme, mk_vp

BASE = '/api/v1/incentives/'


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


_seq = iter(range(10000))


def _user(email, *, perms=None):
    u = User.objects.create_user(email=email, password='pass')
    if perms:
        code = f'r{next(_seq)}'
        role = Role.objects.create(code=code, name=code, permissions=perms)
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
    return u


@pytest.fixture
def admin():
    return User.objects.create_superuser(email='admin@x.com', password='pass')


@pytest.fixture
def opened_cycle(tree, period, ase_type, kpis, admin):
    """Scheme + VP + fresh achievements, cycle opened via the API."""
    from django.utils import timezone
    from apps.achievements.models import Achievement

    mk_scheme(ase_type, kpis)
    mk_vp(tree['ase1'], period)
    mk_vp(tree['ase2'], period)
    mk_baseline_achievements(period, kpis, tree['ase1'])
    mk_baseline_achievements(period, kpis, tree['ase2'], primary='128', eco='105', msl='110')
    Achievement.objects.filter(target_period=period).update(computed_at=timezone.now())
    resp = _client(admin).post(f'{BASE}cycles/', {'period_id': period.id}, format='json')
    assert resp.status_code == 201
    return resp.data['id']


@pytest.mark.django_db
class TestCycleApi:
    def test_readiness_is_green(self, opened_cycle, admin):
        resp = _client(admin).get(f'{BASE}cycles/{opened_cycle}/readiness/')
        assert resp.status_code == 200
        assert resp.data['is_ready'] is True

    def test_full_lifecycle_through_api(self, opened_cycle, admin, period):
        c = _client(admin)
        cid = opened_cycle

        assert c.post(f'{BASE}cycles/{cid}/finalize/', {}, format='json').status_code == 202
        assert PayoutCycle.objects.get(pk=cid).status == PayoutCycle.COMPUTING

        assert c.post(f'{BASE}cycles/{cid}/compute/', {}, format='json').status_code == 202
        assert PayoutCycle.objects.get(pk=cid).status == PayoutCycle.UNDER_REVIEW

        review = c.get(f'{BASE}cycles/{cid}/review/')
        assert review.status_code == 200
        assert review.data['stats']['payees'] == 2

        assert c.post(f'{BASE}cycles/{cid}/submit/', {}, format='json').status_code == 200

        # Maker (admin) cannot approve their own cycle (BusinessError → 422).
        checker = _user('checker@x.com', perms={'payout_approve': 'full', 'final_payout': 'view_all'})
        assert c.post(f'{BASE}cycles/{cid}/approve/', {}, format='json').status_code == 422
        assert _client(checker).post(f'{BASE}cycles/{cid}/approve/', {},
                                     format='json').status_code == 200
        assert PayoutCycle.objects.get(pk=cid).status == PayoutCycle.APPROVED

        disb = _client(checker).post(f'{BASE}cycles/{cid}/disburse/',
                                     {'payment_ref': 'NEFT-1'}, format='json')
        assert disb.status_code == 200
        assert PayoutCycle.objects.get(pk=cid).status == PayoutCycle.DISBURSED

    def test_hold_excluded_from_register(self, opened_cycle, admin, tree):
        c = _client(admin)
        cid = opened_cycle
        c.post(f'{BASE}cycles/{cid}/finalize/', {}, format='json')
        c.post(f'{BASE}cycles/{cid}/compute/', {}, format='json')

        p1 = Payout.objects.get(run__cycle_id=cid, entity=tree['ase1'])
        held = c.post(f'{BASE}payouts/{p1.id}/hold/', {'reason': 'dispute'}, format='json')
        assert held.status_code == 200
        assert held.data['hold_status'] == 'held'

        reg = c.get(f'{BASE}cycles/{cid}/register/')
        codes = {r['entity_code'] for r in reg.data['rows']}
        assert 'ASE1' not in codes and 'ASE2' in codes

        csv_resp = c.get(f'{BASE}cycles/{cid}/register/?fmt=csv')
        assert csv_resp['Content-Type'] == 'text/csv'
        assert b'TOTAL' in csv_resp.content

    def test_statement_endpoint(self, opened_cycle, admin, tree):
        c = _client(admin)
        cid = opened_cycle
        c.post(f'{BASE}cycles/{cid}/finalize/', {}, format='json')
        c.post(f'{BASE}cycles/{cid}/compute/', {}, format='json')
        p1 = Payout.objects.get(run__cycle_id=cid, entity=tree['ase1'])
        stmt = c.get(f'{BASE}payouts/{p1.id}/statement/')
        assert stmt.status_code == 200
        assert stmt.data['entity']['code'] == 'ASE1'
        assert {li['kpi_code'] for li in stmt.data['lines']} == {'PRIMARY', 'ECO', 'MSL'}

    def test_non_admin_cannot_finalize(self, opened_cycle, period):
        u = _user('rep@x.com', perms={'final_payout': 'own_only'})
        resp = _client(u).post(f'{BASE}cycles/{opened_cycle}/finalize/', {}, format='json')
        assert resp.status_code == 403
