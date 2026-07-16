from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


@shared_task
def import_users_task(job_id, data, fmt, user_id, dry_run=False):
    """Celery adapter for user bulk import"""
    from apps.accounts.models import User
    from apps.accounts.services import UserService

    job = BulkJob.objects.get(pk=job_id)
    actor = User.objects.filter(pk=user_id).first() if user_id else None
    JobService.mark_running(job)

    try:
        result = UserService.bulk_import_users(data=data, fmt=fmt, actor=actor, dry_run=dry_run)
    except Exception as exc:
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return

    if result.get('status') == 'validation_failed':
        JobService.fail(job, errors=result.get('errors', []))
        return

    created = result.get('created', result.get('would_create', 0))
    JobService.update_progress(job, processed=created, success=created, error=0)
    JobService.complete(job, result=result)
