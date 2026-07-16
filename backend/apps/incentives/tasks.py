from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


def _user(user_id):
    from apps.accounts.models import User
    return User.objects.filter(pk=user_id).first() if user_id else None


@shared_task
def run_scheduled_estimates():
    """Nightly beat: recompute the estimate payout runs for every OPEN cycle whose period
    covers today. Estimates feed dashboards ("earning so far") honestly labelled and never
    enter review; each night's run auto-supersedes the last. Cycles are opened explicitly
    (a period with no open cycle gets no estimates)."""
    from django.utils import timezone

    from apps.incentives.models import PayoutCycle
    from apps.incentives.services import PayoutCycleService

    today = timezone.localdate()
    cycles = PayoutCycle.objects.filter(
        status=PayoutCycle.OPEN,
        target_period__start_date__lte=today,
        target_period__end_date__gte=today,
    ).select_related('target_period')

    results = [PayoutCycleService.compute_estimates(cycle) for cycle in cycles]
    return {'cycles': len(results), 'results': results}


@shared_task(autoretry_for=(Exception,), max_retries=3, default_retry_delay=60)
def finalize_cycle_task(job_id, cycle_id, user_id=None, override=False, override_reason=''):
    """Freeze a cycle's achievements (finalize). Wraps PayoutCycleService.finalize and
    reports on the BulkJob. The readiness gate is validated in the view before dispatch;
    finalize re-checks idempotently."""
    from apps.incentives.models import PayoutCycle
    from apps.incentives.services import PayoutCycleService

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        cycle = PayoutCycle.objects.get(pk=cycle_id)
        cycle = PayoutCycleService.finalize(
            cycle, actor=_user(user_id), override=override, override_reason=override_reason,
        )
    except Exception as exc:  # noqa: BLE001
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        raise
    JobService.complete(job, result={'cycle_id': cycle.pk, 'status': cycle.status,
                                     'computation_id': cycle.achievement_computation_id})


@shared_task(autoretry_for=(Exception,), max_retries=3, default_retry_delay=60)
def compute_cycle_task(job_id, cycle_id, user_id=None):
    """Compute the final payout runs for a finalized cycle. Wraps PayoutCycleService.compute."""
    from apps.incentives.models import PayoutCycle
    from apps.incentives.services import PayoutCycleService

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        cycle = PayoutCycle.objects.get(pk=cycle_id)
        result = PayoutCycleService.compute(cycle, actor=_user(user_id))
    except Exception as exc:  # noqa: BLE001
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        raise
    JobService.update_progress(job, processed=len(result['run_ids']),
                               success=len(result['run_ids']))
    JobService.complete(job, result=result)


@shared_task(autoretry_for=(Exception,), max_retries=3, default_retry_delay=60)
def compute_payout_run(job_id, run_id, user_id=None):
    """Compute one payout run (scheme × period). Wraps PayoutService.compute_run
    and reports progress on the BulkJob; marks the run failed on error."""
    from apps.incentives.services import PayoutService

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        result = PayoutService.compute_run(run_id, triggered_by=_user(user_id))
    except Exception as exc:  # noqa: BLE001
        PayoutService.mark_failed(run_id, str(exc))
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        raise
    processed = result.get('entities_processed', 0)
    JobService.update_progress(job, processed=processed, success=processed,
                               error=len(result.get('errors', [])))
    JobService.complete(job, result=result)
