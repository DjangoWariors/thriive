from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


def _user(user_id):
    from apps.accounts.models import User
    return User.objects.filter(pk=user_id).first() if user_id else None


@shared_task
def execute_plan_run_task(job_id, run_id):
    """Compute one plan-run stage into staging (never touches committed targets)."""
    from apps.targets.plan_services import PlanService

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        run = PlanService.execute_run(run_id, job=job)
    except Exception as exc:  # noqa: BLE001
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return
    JobService.complete(job, result=run.stats)


@shared_task
def import_allocations_task(job_id, raw, user_id=None):
    from apps.targets.services import TargetService

    job = BulkJob.objects.get(pk=job_id)
    JobService.mark_running(job)
    try:
        result = TargetService.bulk_import_allocations(raw, actor=_user(user_id))
    except Exception as exc:
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return
    if result.get('status') == 'validation_failed':
        JobService.fail(job, errors=result.get('errors', []))
        return
    processed = result.get('created', 0) + result.get('updated', 0)
    JobService.update_progress(job, processed=processed, success=processed, error=0)
    JobService.complete(job, result=result)
