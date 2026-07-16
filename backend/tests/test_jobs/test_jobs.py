"""
Tests for the bulk-job infrastructure (Phase B1):
JobService lifecycle, run_or_dispatch sync/async behaviour, and BulkJobViewSet RBAC scoping.
"""
import pytest
from celery import shared_task
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.jobs import dispatch as dispatch_mod
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.services import JobService

JOBS_URL = '/api/v1/jobs/'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@shared_task
def _complete_job_task(job_id, value):
    """A trivial task used to exercise run_or_dispatch."""
    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    JobService.update_progress(job, processed=value, success=value)
    JobService.complete(job, result={'value': value})


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def user_a(db):
    return User.objects.create_user(email='a@example.com', password='pass')


@pytest.fixture
def user_b(db):
    return User.objects.create_user(email='b@example.com', password='pass')


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


# ── JobService lifecycle ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestJobServiceLifecycle:

    def test_create_defaults_to_queued(self, user_a):
        job = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a, total_rows=10, request_id='req-1')
        assert job.status == BulkJob.Status.QUEUED
        assert job.total_rows == 10
        assert job.created_by == user_a
        assert job.request_id == 'req-1'
        assert job.is_terminal is False

    def test_create_with_anonymous_user_sets_null(self, db):
        from django.contrib.auth.models import AnonymousUser
        job = JobService.create(BulkJob.JobType.USER_IMPORT, AnonymousUser())
        assert job.created_by is None

    def test_running_then_complete(self, user_a):
        job = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        JobService.mark_running(job)
        assert job.status == BulkJob.Status.RUNNING
        assert job.started_at is not None

        JobService.update_progress(job, processed=5, success=4, error=1)
        assert (job.processed_rows, job.success_count, job.error_count) == (5, 4, 1)

        JobService.complete(job, result={'created': [1, 2, 3]})
        job.refresh_from_db()
        assert job.status == BulkJob.Status.COMPLETED
        assert job.finished_at is not None
        assert job.result == {'created': [1, 2, 3]}
        assert job.is_terminal is True

    def test_fail_records_errors_and_count(self, user_a):
        job = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        errors = [{'row': 1, 'errors': ['bad']}, {'row': 2, 'errors': ['worse']}]
        JobService.fail(job, errors=errors)
        job.refresh_from_db()
        assert job.status == BulkJob.Status.FAILED
        assert job.errors == errors
        assert job.error_count == 2
        assert job.is_terminal is True

    def test_partial_records_errors(self, user_a):
        job = JobService.create(BulkJob.JobType.USER_IMPORT, user_a)
        JobService.mark_partial(job, errors=[{'row': 3, 'errors': ['skipped']}])
        job.refresh_from_db()
        assert job.status == BulkJob.Status.PARTIAL
        assert job.error_count == 1
        assert job.is_terminal is True


# ── run_or_dispatch ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRunOrDispatch:

    def test_runs_inline_when_eager(self, user_a):
        # Dev settings set CELERY_TASK_ALWAYS_EAGER = True → inline path.
        job = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a, total_rows=42)
        returned = run_or_dispatch(_complete_job_task, job, 42)
        assert returned.status == BulkJob.Status.COMPLETED
        assert returned.processed_rows == 42
        assert returned.result == {'value': 42}

    def test_dispatches_when_not_eager(self, user_a, monkeypatch):
        # Force the async branch and capture the dispatch instead of executing.
        monkeypatch.setattr(dispatch_mod, 'should_run_eager', lambda: False)
        calls = {}
        monkeypatch.setattr(
            _complete_job_task, 'delay',
            lambda *args, **kwargs: calls.setdefault('args', args),
        )
        job = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        returned = run_or_dispatch(_complete_job_task, job, 7)

        assert calls['args'] == (job.id, 7)
        # Not executed inline → still queued.
        assert returned.status == BulkJob.Status.QUEUED


# ── API: RBAC scoping ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkJobAPI:

    def test_user_sees_only_own_jobs(self, user_a, user_b):
        job_a = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_b)

        resp = _auth_client(user_a).get(JOBS_URL)
        assert resp.status_code == 200
        ids = [row['id'] for row in resp.data['results']]
        assert ids == [job_a.id]

    def test_user_cannot_retrieve_others_job(self, user_a, user_b):
        job_b = JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_b)
        resp = _auth_client(user_a).get(f'{JOBS_URL}{job_b.id}/')
        assert resp.status_code == 404

    def test_superuser_sees_all_jobs(self, user_a, user_b, superuser):
        JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        JobService.create(BulkJob.JobType.USER_IMPORT, user_b)
        resp = _auth_client(superuser).get(JOBS_URL)
        assert resp.status_code == 200
        assert resp.data['count'] == 2

    def test_filter_by_job_type(self, user_a):
        JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        JobService.create(BulkJob.JobType.USER_IMPORT, user_a)
        resp = _auth_client(user_a).get(f'{JOBS_URL}?job_type=user_import')
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['job_type'] == 'user_import'

    def test_unauthenticated_denied(self, user_a):
        JobService.create(BulkJob.JobType.ENTITY_IMPORT, user_a)
        resp = APIClient().get(JOBS_URL)
        assert resp.status_code == 401
