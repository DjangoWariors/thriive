"""Audit read APIs + RBAC + verify endpoint."""
import pytest

from apps.audit.models import AuditLog
from apps.audit.services import AuditService

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db
BASE = '/api/v1/audit/'


def _seed_logs():
    AuditService.log('create', 'hierarchy.Node', 1, None, {'name': 'A'})
    AuditService.log('update', 'hierarchy.Node', 1, None, {'name': 'B'})
    AuditService.log('create', 'master_data.SKU', 9, None, {'code': 'SKU9'})


class TestAuditLogApi:
    def test_list_requires_permission(self, db):
        _seed_logs()
        nobody = make_user('no@x.com', perms={'dashboard': 'own_only'})
        assert client_for(nobody).get(f'{BASE}logs/').status_code == 403

    def test_list_returns_logs(self, auditor):
        _seed_logs()
        resp = client_for(auditor).get(f'{BASE}logs/')
        assert resp.status_code == 200
        assert resp.data['count'] == 3

    def test_filter_by_entity_type(self, auditor):
        _seed_logs()
        resp = client_for(auditor).get(f'{BASE}logs/', {'entity_type': 'master_data.SKU'})
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['entity_type'] == 'master_data.SKU'

    def test_filter_by_action(self, auditor):
        _seed_logs()
        resp = client_for(auditor).get(f'{BASE}logs/', {'action': 'create'})
        assert resp.data['count'] == 2

    def test_record_history_endpoint(self, auditor):
        _seed_logs()
        resp = client_for(auditor).get(f'{BASE}logs/hierarchy.Node/1/')
        assert resp.status_code == 200
        assert resp.data['count'] == 2

    def test_user_label_resolved(self, auditor):
        actor = make_user('actor@x.com')
        AuditService.log('update', 'x.Y', 1, actor, {'k': 'v'})
        resp = client_for(auditor).get(f'{BASE}logs/', {'user': actor.pk})
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['user_label'] == 'actor@x.com'


class TestVerifyApi:
    def test_verify_reports_ok(self, auditor):
        _seed_logs()
        resp = client_for(auditor).post(f'{BASE}verify/', {})
        assert resp.status_code == 200
        assert resp.data['ok'] is True

    def test_verify_reports_break(self, auditor):
        _seed_logs()
        row = AuditLog.objects.order_by('id')[1]
        AuditLog.objects.filter(pk=row.pk).update(action='HACKED')
        resp = client_for(auditor).post(f'{BASE}verify/', {})
        assert resp.data['ok'] is False
        assert resp.data['broken_at'] == row.pk


class TestAccessLogApi:
    def test_access_log_needs_higher_permission(self, db):
        # audit_logs alone is not enough — access trail needs audit_access.
        only_audit = make_user('aud@x.com', perms={'audit_logs': 'view_all'})
        assert client_for(only_audit).get(f'{BASE}access-logs/').status_code == 403

    def test_access_log_visible_with_permission(self, auditor):
        from apps.audit.services import AccessService
        AccessService.record(auditor, 'payout', subject_entity_id=3, object_id=1)
        resp = client_for(auditor).get(f'{BASE}access-logs/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['resource'] == 'payout'
