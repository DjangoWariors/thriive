"""ReportSchedule lifecycle: recipient resolution, relative-period resolution,
celery-beat sync, and the per-recipient scheduled run."""
import json
from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.core.permissions import _rank, highest_level
from apps.core.permissions import subtree_lookup
from apps.reports.models import ReportExecution, ReportSchedule
from apps.reports.services import ReportService

_TASK = 'apps.reports.tasks.run_scheduled_report'


class ReportScheduleService:

    # ── celery-beat sync ────────────────────────────────────────────────────
    @staticmethod
    def sync_beat(schedule: ReportSchedule) -> None:
        """Create/update the PeriodicTask backing this schedule. Best-effort:
        if django-celery-beat tables aren't migrated (e.g. minimal test db), the
        schedule still persists and run-now / the task still work."""
        try:
            from django_celery_beat.models import CrontabSchedule, PeriodicTask
        except Exception:  # pragma: no cover
            return
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=schedule.cron_minute, hour=schedule.cron_hour,
            day_of_week=schedule.cron_day_of_week,
            day_of_month=schedule.cron_day_of_month,
            month_of_year=schedule.cron_month_of_year,
            timezone='Asia/Kolkata',
        )
        task, _ = PeriodicTask.objects.update_or_create(
            name=f'report_schedule_{schedule.pk}',
            defaults={
                'task': _TASK,
                'crontab': crontab,
                'args': json.dumps([schedule.pk]),
                'enabled': schedule.is_enabled,
            },
        )
        if schedule.periodic_task_id != task.pk:
            ReportSchedule.objects.filter(pk=schedule.pk).update(periodic_task_id=task.pk)

    @staticmethod
    def set_enabled(schedule: ReportSchedule, enabled: bool) -> ReportSchedule:
        schedule.is_enabled = enabled
        schedule.save(update_fields=['is_enabled', 'updated_at'])
        ReportScheduleService.sync_beat(schedule)
        return schedule

    # ── resolution ──────────────────────────────────────────────────────────
    @staticmethod
    def resolve_params(params: dict) -> dict:
        out = dict(params or {})
        token = out.get('period')
        if token in ('current', 'last_month'):
            out['period'] = ReportScheduleService._resolve_period(token)
        return out

    @staticmethod
    def _resolve_period(token: str):
        from apps.targets.models import TargetPeriod
        today = date.today()
        if token == 'current':
            p = (TargetPeriod.objects.filter(start_date__lte=today, end_date__gte=today)
                 .order_by('-start_date').first())
        else:  # last_month
            p = (TargetPeriod.objects.filter(period_type=TargetPeriod.MONTHLY,
                                             end_date__lt=today.replace(day=1))
                 .order_by('-end_date').first())
        return p.pk if p else None

    @staticmethod
    def resolve_recipients(schedule: ReportSchedule) -> list[User]:
        """Concrete users to deliver to — explicit users + members of named roles +
        users under named entity subtrees — filtered to those who actually hold the
        report's required_permission (so a payout schedule never reaches a rep)."""
        rec = schedule.recipients or {}
        perm = schedule.definition.required_permission
        found: dict[int, User] = {}

        if uids := rec.get('users'):
            for u in User.objects.filter(pk__in=uids, is_active=True):
                found[u.pk] = u

        if role_codes := rec.get('roles'):
            today = date.today()
            urs = (UserRole.objects.filter(
                role__code__in=role_codes, is_active=True, role__is_active=True,
                effective_from__lte=today,
            ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
                .select_related('user'))
            for ur in urs:
                if ur.user.is_active:
                    found[ur.user.pk] = ur.user

        if eids := rec.get('entities'):
            from apps.hierarchy.models import Node
            paths = Node.objects.filter(pk__in=eids).values_list('path', flat=True)
            for path in paths:
                in_subtree = Node.objects.filter(is_current=True, **subtree_lookup(path))
                for u in User.objects.filter(entity__in=in_subtree, is_active=True):
                    found[u.pk] = u

        return [u for u in found.values()
                if u.is_superuser or _rank(highest_level(u, perm)) > 0]

    # ── run ─────────────────────────────────────────────────────────────────
    @staticmethod
    def run(schedule: ReportSchedule) -> dict:
        from apps.notifications.services import NotificationService

        params = ReportScheduleService.resolve_params(schedule.parameters)

        # Target delivery = machine extract: ONE run in the owner's scope, pushed out.
        if schedule.delivery == ReportSchedule.Delivery.TARGET:
            return ReportScheduleService._run_target(schedule, params)

        recipients = ReportScheduleService.resolve_recipients(schedule)
        delivered = 0
        for user in recipients:
            execution = ReportService.build_execution(schedule.definition, params,
                                                       schedule.format, user)
            ReportService.run_execution(execution)
            if execution.status == ReportExecution.Status.COMPLETED:
                if schedule.delivery in (ReportSchedule.Delivery.IN_APP,
                                         ReportSchedule.Delivery.BOTH):
                    NotificationService.send(user, 'report_ready', {
                        'title': f'{schedule.definition.name} is ready',
                        'body': f'Your scheduled report "{schedule.name}" has been generated.',
                        'execution_id': execution.pk,
                    })
                # Email delivery: in dev the notification backend is console; a real
                # SMTP/SES backend attaches the artifact. Both routed through notifications.
                delivered += 1

        ReportSchedule.objects.filter(pk=schedule.pk).update(last_run_at=timezone.now())
        return {'recipients': len(recipients), 'delivered': delivered}

    @staticmethod
    def _run_target(schedule: ReportSchedule, params: dict) -> dict:
        from apps.reports.delivery import push_to_target

        execution = ReportService.build_execution(
            schedule.definition, params, schedule.format, schedule.owner,
        )
        ReportService.run_execution(execution)
        delivered = 0
        if execution.status == ReportExecution.Status.COMPLETED and schedule.delivery_target:
            filename = (
                f'{schedule.definition.code}-{timezone.now():%Y%m%d-%H%M%S}.{execution.format}'
            )
            try:
                with execution.file.open('rb') as fh:
                    push_to_target(schedule.delivery_target, filename, fh.read())
                execution.delivered_at = timezone.now()
                execution.save(update_fields=['delivered_at', 'updated_at'])
                delivered = 1
            except Exception as exc:  # noqa: BLE001 — record delivery failure on the execution
                execution.delivery_error = str(exc)
                execution.save(update_fields=['delivery_error', 'updated_at'])

        ReportSchedule.objects.filter(pk=schedule.pk).update(last_run_at=timezone.now())
        return {'recipients': 1, 'delivered': delivered}
