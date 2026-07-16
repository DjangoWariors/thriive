"""
Phase B2 — async + dry-run for bulk import.

Covers the entity and user bulk endpoints: dry-run validates without writing,
async returns 202 + a pollable job that completes (eager mode), the >threshold
rule forces async, and the existing synchronous behaviour is unchanged.
"""
import json
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType
from apps.jobs.models import BulkJob

ENTITY_BULK_URL = '/api/v1/entities/bulk/'
USER_BULK_URL = '/api/v1/auth/users/bulk/'


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


@pytest.fixture
def hierarchy_user(db):
    user = User.objects.create_user(email='hmgr@example.com', password='pass')
    role = Role.objects.create(
        code='hier_mgr', name='Hierarchy Manager',
        permissions={'hierarchy_management': 'full'},
    )
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def user_mgr(db):
    user = User.objects.create_user(email='umgr@example.com', password='pass')
    role = Role.objects.create(
        code='user_mgr', name='User Manager',
        permissions={'user_management': 'full'},
    )
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def base_type(db):
    return NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, effective_from=date.today(),
    )


def _entity_rows(n, prefix='E'):
    return [{'entity_type_code': 'NSM', 'name': f'{prefix}{i}', 'code': f'{prefix}{i}'} for i in range(n)]


# ── Node bulk: dry-run ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeBulkDryRun:

    def test_dry_run_valid_creates_nothing(self, hierarchy_user, base_type):
        rows = _entity_rows(3)
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows), 'dry_run': True},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'valid'
        assert resp.data['rows'] == 3
        assert resp.data['would_create'] == 3
        assert Node.objects.count() == 0

    def test_dry_run_invalid_returns_422_and_creates_nothing(self, hierarchy_user, base_type):
        rows = [{'entity_type_code': 'NOPE', 'name': 'X', 'code': 'X'}]
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows), 'dry_run': True},
            format='json',
        )
        assert resp.status_code == 422
        assert resp.data['status'] == 'validation_failed'
        assert resp.data['errors'][0]['row'] == 1
        assert Node.objects.count() == 0


# ── Node bulk: async ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeBulkAsync:

    def test_run_async_returns_202_and_completes(self, hierarchy_user, base_type):
        rows = _entity_rows(2)
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows), 'run_async': True},
            format='json',
        )
        assert resp.status_code == 202
        job_id = resp.data['id']
        # Eager mode → already completed by the time we get the response.
        job = BulkJob.objects.get(pk=job_id)
        assert job.job_type == BulkJob.JobType.ENTITY_IMPORT
        assert job.status == BulkJob.Status.COMPLETED
        assert job.success_count == 2
        assert job.result['created'] == 2
        assert Node.objects.count() == 2

    def test_over_threshold_forces_async(self, hierarchy_user, base_type, monkeypatch):
        import apps.hierarchy.views as hviews
        monkeypatch.setattr(hviews, 'BULK_ASYNC_THRESHOLD', 2)
        rows = _entity_rows(3)
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows)},
            format='json',
        )
        assert resp.status_code == 202
        assert resp.data['total_rows'] == 3
        assert Node.objects.count() == 3

    def test_async_validation_failure_marks_job_failed(self, hierarchy_user, base_type):
        rows = [{'entity_type_code': 'NOPE', 'name': 'X', 'code': 'X'}]
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows), 'run_async': True},
            format='json',
        )
        assert resp.status_code == 202
        job = BulkJob.objects.get(pk=resp.data['id'])
        assert job.status == BulkJob.Status.FAILED
        assert job.errors[0]['row'] == 1
        assert Node.objects.count() == 0


# ── Node bulk: sync unchanged ───────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeBulkSyncUnchanged:

    def test_small_sync_import_still_200(self, hierarchy_user, base_type):
        rows = _entity_rows(2)
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows)},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'success'
        assert resp.data['created'] == 2
        assert Node.objects.count() == 2

    def test_sync_validation_failure_422(self, hierarchy_user, base_type):
        rows = [{'entity_type_code': 'NOPE', 'name': 'X', 'code': 'X'}]
        resp = _auth_client(hierarchy_user).post(
            ENTITY_BULK_URL,
            {'format': 'json', 'data': json.dumps(rows)},
            format='json',
        )
        assert resp.status_code == 422
        assert Node.objects.count() == 0


# ── User bulk: dry-run + async ────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserBulk:

    def test_dry_run_valid_creates_nothing(self, user_mgr):
        csv_data = 'first_name,email\nAda,ada@x.com\nBob,bob@x.com\n'
        resp = _auth_client(user_mgr).post(
            USER_BULK_URL,
            {'format': 'csv', 'data': csv_data, 'dry_run': True},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'valid'
        assert resp.data['rows'] == 2
        assert not User.objects.filter(email='ada@x.com').exists()

    def test_dry_run_invalid_returns_422(self, user_mgr):
        # Missing first_name on row 1.
        csv_data = 'first_name,email\n,ada@x.com\n'
        resp = _auth_client(user_mgr).post(
            USER_BULK_URL,
            {'format': 'csv', 'data': csv_data, 'dry_run': True},
            format='json',
        )
        assert resp.status_code == 422
        assert resp.data['status'] == 'validation_failed'
        assert not User.objects.filter(email='ada@x.com').exists()

    def test_run_async_returns_202_and_completes(self, user_mgr):
        csv_data = 'first_name,email\nAda,ada@x.com\nBob,bob@x.com\n'
        resp = _auth_client(user_mgr).post(
            USER_BULK_URL,
            {'format': 'csv', 'data': csv_data, 'run_async': True},
            format='json',
        )
        assert resp.status_code == 202
        job = BulkJob.objects.get(pk=resp.data['id'])
        assert job.job_type == BulkJob.JobType.USER_IMPORT
        assert job.status == BulkJob.Status.COMPLETED
        assert job.success_count == 2
        assert User.objects.filter(email='ada@x.com').exists()

    def test_sync_success_still_201(self, user_mgr):
        csv_data = 'first_name,email\nAda,ada@x.com\n'
        resp = _auth_client(user_mgr).post(
            USER_BULK_URL,
            {'format': 'csv', 'data': csv_data},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.data['status'] == 'success'
        assert resp.data['created'] == 1
