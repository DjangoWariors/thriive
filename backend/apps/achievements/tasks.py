from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


def _user(user_id):
    from apps.accounts.models import User
    return User.objects.filter(pk=user_id).first() if user_id else None


@shared_task
def run_scheduled_achievements():
    """Nightly beat entry point. Recomputes achievements for every period that is
    currently 'live' and whose date range covers today. Live = period status in
    THRIIVE_ACHIEVEMENT_AUTO_STATUSES, or a plan on the period has gone live —
    governance is keyed to PLAN status, so a published plan must feed dashboards
    even while the period itself is still draft on the planning calendar. Each
    period gets its own BulkJob (system-triggered), so it is tracked exactly like
    a manual /achievements/compute/ run."""
    from django.conf import settings
    from django.db.models import Q
    from django.utils import timezone

    from apps.achievements.views import _compute_task_ref
    from apps.jobs.dispatch import run_or_dispatch
    from apps.targets.models import TargetPeriod, TargetPlan

    statuses = getattr(settings, 'THRIIVE_ACHIEVEMENT_AUTO_STATUSES', ['published', 'locked'])
    today = timezone.localdate()
    periods = TargetPeriod.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).filter(
        Q(status__in=statuses) | Q(plans__status__in=TargetPlan.LIVE_STATUSES),
    ).distinct()

    dispatched = []
    task = _compute_task_ref()
    for period in periods:
        job = JobService.create(BulkJob.JobType.ACHIEVEMENT_COMPUTE, None)
        run_or_dispatch(task, job, period.id, None)
        dispatched.append({'period_id': period.id, 'job_id': job.id})
    return {'periods': len(dispatched), 'dispatched': dispatched}


@shared_task(autoretry_for=(Exception,), max_retries=3, default_retry_delay=60)
def compute_daily_achievements(job_id, period_id, user_id=None):
    """Orchestrate one achievement run for a period: open the run, then fan out one unit
    per KPI. Broker-less / eager installs run the units inline; with a real broker each
    unit is its own Celery task (the natural parallel grain) and the last one to finish
    finalizes the run. BulkJob progress is per KPI unit either way."""
    from apps.achievements.services import AchievementService
    from apps.jobs.dispatch import should_run_eager

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        ctx = AchievementService.start_run(period_id, triggered_by=_user(user_id))
    except Exception as exc:  # noqa: BLE001
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        raise
    kpi_ids = ctx['kpi_ids']
    job.total_rows = len(kpi_ids)
    job.save(update_fields=['total_rows', 'updated_at'])

    if not kpi_ids or should_run_eager():
        for done, kpi_id in enumerate(kpi_ids, start=1):
            AchievementService.compute_kpi_unit(
                period_id, kpi_id, ctx['computation_id'], ctx['as_of'], ctx['type_codes'],
            )
            JobService.update_progress(job, processed=done, success=done)
        result = AchievementService.finalize_run(period_id, ctx['computation_id'], ctx['as_of'])
        JobService.complete(job, result=result)
        return
    for kpi_id in kpi_ids:
        compute_achievement_kpi.delay(
            job_id, period_id, kpi_id, ctx['computation_id'],
            ctx['as_of'].isoformat(), ctx['type_codes'],
        )


@shared_task
def compute_achievement_kpi(job_id, period_id, kpi_id, computation_id, as_of, type_codes):
    """One fan-out unit: territory + person pass for a single KPI. KPI-level failures are
    recorded on the run's ComputationLog, never raised — one bad KPI must not sink the
    others. Whichever unit completes the run finalizes it (alerts, log, notifications)
    and closes the BulkJob."""
    from datetime import date

    from apps.achievements.services import AchievementService

    as_of = date.fromisoformat(as_of)
    summary = AchievementService.compute_kpi_unit(
        period_id, kpi_id, computation_id, as_of, type_codes,
    )
    JobService.increment_progress(job_id)
    if summary['is_last']:
        result = AchievementService.finalize_run(period_id, computation_id, as_of)
        JobService.complete(BulkJob.objects.get(pk=job_id), result=result)
