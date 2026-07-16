"""Report API: catalog, generate (eager), poll, download, RBAC, param validation."""
import pytest

from apps.reports.models import ReportExecution

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db
BASE = '/api/v1/reports/'


class TestCatalog:
    def test_catalog_lists_only_runnable(self, reports_seeded):
        able = make_user('mgr@x.com', perms={'report_master': 'view_all'})
        unable = make_user('rep@x.com', perms={'dashboard': 'own_only'})
        assert len(client_for(able).get(f'{BASE}definitions/').data) == 1
        assert len(client_for(unable).get(f'{BASE}definitions/').data) == 0


class TestGenerate:
    def test_generate_runs_eager_and_completes(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        user = make_user('mgr@x.com', perms={'report_master': 'view_all'})
        resp = client_for(user).post(f'{BASE}generate/',
                                     {'code': 'entity_roster', 'format': 'csv'}, format='json')
        assert resp.status_code == 202
        execution_id = resp.data['id']
        execution = ReportExecution.objects.get(pk=execution_id)
        assert execution.status == 'completed'
        assert execution.row_count == 4
        assert execution.file

    def test_generate_forbidden_without_permission(self, reports_seeded, org):
        user = make_user('rep@x.com', perms={'dashboard': 'own_only'})
        resp = client_for(user).post(f'{BASE}generate/',
                                     {'code': 'entity_roster'}, format='json')
        assert resp.status_code == 422  # BusinessError → report_forbidden

    def test_unknown_report_rejected(self, reports_seeded):
        user = make_user('mgr@x.com', perms={'report_master': 'view_all'})
        resp = client_for(user).post(f'{BASE}generate/',
                                     {'code': 'nope'}, format='json')
        assert resp.status_code == 422

    def test_invalid_choice_param_rejected(self, reports_seeded, org):
        user = make_user('mgr@x.com', perms={'report_master': 'view_all'})
        resp = client_for(user).post(
            f'{BASE}generate/',
            {'code': 'entity_roster', 'parameters': {'status': 'banana'}}, format='json')
        assert resp.status_code == 422


class TestExecutionsAndDownload:
    def test_user_sees_only_own_executions(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        mine = make_user('a@x.com', perms={'report_master': 'view_all'})
        other = make_user('b@x.com', perms={'report_master': 'view_all'})
        client_for(mine).post(f'{BASE}generate/', {'code': 'entity_roster'}, format='json')
        assert client_for(mine).get(f'{BASE}executions/').data['count'] == 1
        assert client_for(other).get(f'{BASE}executions/').data['count'] == 0

    def test_download_returns_file(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        user = make_user('a@x.com', perms={'report_master': 'view_all'})
        gen = client_for(user).post(f'{BASE}generate/',
                                    {'code': 'entity_roster', 'format': 'csv'}, format='json')
        eid = gen.data['id']
        resp = client_for(user).get(f'{BASE}executions/{eid}/download/')
        assert resp.status_code == 200
        body = b''.join(resp.streaming_content)
        assert b'Code,Name' in body

    def test_subtree_scope_limits_report_rows(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        # Manager placed at ASM sees only ASM subtree (3 rows), never the NSM above.
        asm_user = make_user('asm@x.com', entity=org['asm'],
                             perms={'report_master': 'team'})
        gen = client_for(asm_user).post(f'{BASE}generate/',
                                        {'code': 'entity_roster'}, format='json')
        execution = ReportExecution.objects.get(pk=gen.data['id'])
        assert execution.row_count == 3
