"""Report scheduling: recipient RBAC filtering, relative periods, run-now delivery."""
from datetime import date

import pytest

from apps.notifications.models import Notification
from apps.reports.models import ReportDefinition, ReportExecution, ReportSchedule
from apps.reports.schedule_service import ReportScheduleService
from apps.targets.models import TargetPeriod

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db
BASE = '/api/v1/reports/'


def _schedule(definition_code='entity_roster', **kw):
    defn = ReportDefinition.objects.get(code=definition_code)
    return ReportSchedule.objects.create(
        definition=defn, name=kw.get('name', 'Weekly Roster'),
        parameters=kw.get('parameters', {}), format=kw.get('format', 'csv'),
        recipients=kw.get('recipients', {}), delivery=kw.get('delivery', 'both'),
    )


class TestRecipientResolution:
    def test_only_permitted_recipients_kept(self, reports_seeded, org):
        # payout_register needs report_payout — a roster-only user is dropped.
        able = make_user('fin@x.com', perms={'report_payout': 'view_all'})
        unable = make_user('rep@x.com', perms={'dashboard': 'own_only'})
        sched = _schedule('payout_register',
                          recipients={'users': [able.pk, unable.pk]})
        resolved = ReportScheduleService.resolve_recipients(sched)
        assert {u.pk for u in resolved} == {able.pk}

    def test_role_recipients_expand_to_members(self, reports_seeded, org):
        from apps.accounts.models import Role, UserRole
        role = Role.objects.create(code='zonal', name='Zonal',
                                   permissions={'report_master': 'view_all'})
        u = make_user('z@x.com')
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
        sched = _schedule('entity_roster', recipients={'roles': ['zonal']})
        resolved = ReportScheduleService.resolve_recipients(sched)
        assert u.pk in {r.pk for r in resolved}


class TestRelativePeriods:
    def test_current_period_resolved(self, db):
        # Span the actual current month so 'current' (period containing today) resolves
        # regardless of when the suite runs.
        from calendar import monthrange
        today = date.today()
        start = today.replace(day=1)
        end = today.replace(day=monthrange(today.year, today.month)[1])
        p = TargetPeriod.objects.create(
            name='Current month', code='CURMON', period_type=TargetPeriod.MONTHLY,
            start_date=start, end_date=end, status=TargetPeriod.PUBLISHED)
        out = ReportScheduleService.resolve_params({'period': 'current'})
        assert out['period'] == p.pk  # today falls within the current month

    def test_unmatched_token_resolves_none(self, db):
        out = ReportScheduleService.resolve_params({'period': 'current'})
        assert out['period'] is None


class TestRunNow:
    def test_run_now_generates_and_notifies(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        user = make_user('mgr@x.com', perms={'report_master': 'view_all'})
        sched = _schedule('entity_roster', recipients={'users': [user.pk]}, delivery='both')

        result = ReportScheduleService.run(sched)
        assert result == {'recipients': 1, 'delivered': 1}
        # A completed execution was produced for the recipient...
        assert ReportExecution.objects.filter(requested_by=user, status='completed').count() == 1
        # ...and an in-app notification queued.
        assert Notification.objects.filter(user=user, code='report_ready').count() == 1
        sched.refresh_from_db()
        assert sched.last_run_at is not None

    def test_run_now_endpoint(self, reports_seeded, org, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        admin = make_user('admin@x.com', superuser=True)
        recipient = make_user('m@x.com', perms={'report_master': 'view_all'})
        sched = _schedule('entity_roster', recipients={'users': [recipient.pk]})
        resp = client_for(admin).post(f'{BASE}schedules/{sched.pk}/run-now/')
        assert resp.status_code == 200
        assert resp.data['recipients'] == 1


class TestScheduleCrud:
    def test_create_requires_permission(self, reports_seeded):
        rep = make_user('rep@x.com', perms={'dashboard': 'own_only'})
        resp = client_for(rep).post(f'{BASE}schedules/', {
            'name': 'X', 'definition_code': 'entity_roster', 'format': 'csv',
        }, format='json')
        assert resp.status_code == 403

    def test_create_and_toggle(self, reports_seeded):
        admin = make_user('admin@x.com', superuser=True)
        resp = client_for(admin).post(f'{BASE}schedules/', {
            'name': 'Weekly Roster', 'definition_code': 'entity_roster',
            'format': 'csv', 'cron_day_of_week': '1', 'recipients': {'roles': ['finance']},
        }, format='json')
        assert resp.status_code == 201
        sid = resp.data['id']
        assert resp.data['is_enabled'] is True
        toggled = client_for(admin).post(f'{BASE}schedules/{sid}/toggle/')
        assert toggled.data['is_enabled'] is False
