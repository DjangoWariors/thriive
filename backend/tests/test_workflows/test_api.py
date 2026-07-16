import pytest

from apps.incentives.models import PayoutException
from apps.workflows.services import WorkflowService

from .conftest import client_for, make_exception, make_user

pytestmark = pytest.mark.django_db

BASE = '/api/v1/workflows/'


def _raise(org, period):
    exc = make_exception(org['ase1'], period, actor=org['asm_user'])
    inst = WorkflowService.initiate(exc, 'payout_exception_standard',
                                    initiated_by=org['asm_user'])
    return exc, inst


class TestInbox:
    def test_pending_lists_for_assignee(self, org, period, seeded):
        _raise(org, period)
        resp = client_for(org['nsm_user']).get(f'{BASE}pending/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1

    def test_pending_count_endpoint(self, org, period, seeded):
        _raise(org, period)
        resp = client_for(org['nsm_user']).get(f'{BASE}pending/count/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1

    def test_requires_workflow_permission(self, org, period, seeded):
        _raise(org, period)
        nobody = make_user('nobody@x.com', perms={'dashboard': 'own_only'})
        resp = client_for(nobody).get(f'{BASE}pending/')
        assert resp.status_code == 403


class TestDecisions:
    def test_assignee_can_approve(self, org, period, seeded):
        _, inst = _raise(org, period)
        resp = client_for(org['nsm_user']).post(f'{BASE}{inst.pk}/approve/', {'comments': 'ok'})
        assert resp.status_code == 200
        assert resp.data['status'] == 'approved'

    def test_non_assignee_blocked_422(self, org, period, seeded):
        _, inst = _raise(org, period)
        other = make_user('other@x.com', perms={'workflow_management': 'full'})
        resp = client_for(other).post(f'{BASE}{inst.pk}/approve/', {'comments': 'x'})
        assert resp.status_code == 422

    def test_reject_requires_reason(self, org, period, seeded):
        _, inst = _raise(org, period)
        resp = client_for(org['nsm_user']).post(f'{BASE}{inst.pk}/reject/', {})
        assert resp.status_code == 400

    def test_history_endpoint(self, org, period, seeded):
        _, inst = _raise(org, period)
        client_for(org['nsm_user']).post(f'{BASE}{inst.pk}/approve/', {'comments': 'ok'})
        resp = client_for(org['nsm_user']).get(f'{BASE}{inst.pk}/history/')
        assert resp.status_code == 200
        actions = {a['action'] for a in resp.data}
        assert 'initiate' in actions and 'approve' in actions

    def test_bulk_approve_endpoint(self, org, period, seeded):
        _, i1 = _raise(org, period)
        e2 = make_exception(org['ase2'], period, actor=org['asm_user'])
        i2 = WorkflowService.initiate(e2, 'payout_exception_standard',
                                      initiated_by=org['asm_user'])
        resp = client_for(org['nsm_user']).post(
            f'{BASE}bulk-approve/', {'ids': [i1.pk, i2.pk], 'comments': 'batch'}, format='json',
        )
        assert resp.status_code == 200
        assert set(resp.data['processed']) == {i1.pk, i2.pk}
