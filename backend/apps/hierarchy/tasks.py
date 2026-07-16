from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


@shared_task
def import_entities_task(job_id, raw, fmt, user_id, dry_run=False):
    """
    Celery adapter for entity bulk import.
    """
    from apps.hierarchy.services import NodeService

    _run_import(job_id, user_id, lambda user: NodeService.bulk_import(
        raw, fmt=fmt, user=user, dry_run=dry_run))


@shared_task
def import_geography_task(job_id, raw, fmt, user_id, dry_run=False):
    """
    Celery adapter for geography-node (territory) bulk import.
    """
    from apps.hierarchy.config_services import GeographyNodeService

    _run_import(job_id, user_id, lambda user: GeographyNodeService.bulk_import(
        raw, fmt=fmt, user=user, dry_run=dry_run))


def _run_import(job_id, user_id, runner):
    from apps.accounts.models import User

    job = BulkJob.objects.get(pk=job_id)
    user = User.objects.filter(pk=user_id).first() if user_id else None
    JobService.mark_running(job)

    try:
        result = runner(user)
    except Exception as exc:
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return

    if result.get('status') == 'validation_failed':
        JobService.fail(job, errors=result.get('errors', []))
        return

    created = result.get('created', result.get('would_create', 0))
    JobService.update_progress(job, processed=created, success=created, error=0)
    JobService.complete(job, result=result)
