from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


@shared_task
def import_skus_task(job_id, csv_text, user_id):
    """Celery adapter for SKU bulk import. Keeps the all-or-nothing semantics of
    MasterDataService.bulk_import_skus and records progress / row errors on the BulkJob."""
    from apps.accounts.models import User
    from apps.master_data.services import MasterDataService

    job = BulkJob.objects.get(pk=job_id)
    user = User.objects.filter(pk=user_id).first() if user_id else None
    JobService.mark_running(job)

    try:
        result = MasterDataService.bulk_import_skus(csv_text, actor=user)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the job, not the worker
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return

    if result.get('status') != 'success':
        # Map {row, error} → the BulkJob {row, errors:[...]} shape the frontend expects.
        JobService.fail(
            job,
            errors=[{'row': e['row'], 'errors': [e['error']]} for e in result.get('errors', [])],
        )
        return

    processed = result.get('created', 0) + result.get('updated', 0)
    JobService.update_progress(job, processed=processed, success=processed, error=0)
    JobService.complete(job, result=result)
