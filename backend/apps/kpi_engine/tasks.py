from celery import shared_task

from apps.jobs.models import BulkJob
from apps.jobs.services import JobService


@shared_task
def import_transactions_task(job_id, raw, fmt='csv', user_id=None):
    """Celery adapter for transaction bulk import. Mirrors hierarchy.import_entities_task:
    runs the service, then records progress / completion / failure on the BulkJob."""
    from apps.accounts.models import User
    from apps.kpi_engine.services import KPIService

    job = BulkJob.objects.get(pk=job_id)
    user = User.objects.filter(pk=user_id).first() if user_id else None
    JobService.mark_running(job)

    try:
        result = KPIService.bulk_import_transactions(raw, actor=user)
    except Exception as exc:
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return

    if result.get('status') == 'validation_failed':
        JobService.fail(job, errors=result.get('errors', []))
        return

    processed = result.get('created', 0) + result.get('updated', 0)
    JobService.update_progress(job, processed=processed, success=processed, error=0)
    JobService.complete(job, result=result)


@shared_task
def import_metric_values_task(job_id, raw, fmt='csv', user_id=None):
    """Celery adapter for external-metric-value CSV import (same job protocol as
    import_transactions_task)."""
    from apps.accounts.models import User
    from apps.kpi_engine.services import IngestionService

    job = BulkJob.objects.get(pk=job_id)
    user = User.objects.filter(pk=user_id).first() if user_id else None
    JobService.mark_running(job)

    try:
        result = IngestionService.bulk_import_metric_values(raw, actor=user)
    except Exception as exc:
        JobService.fail(job, errors=[{'row': 0, 'errors': [str(exc)]}])
        return

    if result.get('status') == 'validation_failed':
        JobService.fail(job, errors=result.get('errors', []))
        return

    processed = result.get('created', 0) + result.get('updated', 0)
    JobService.update_progress(job, processed=processed, success=processed, error=0)
    JobService.complete(job, result=result)
