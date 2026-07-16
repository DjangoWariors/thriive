from django.db.models import F
from django.utils import timezone

from .models import BulkJob


class JobService:
    """
    The only layer that writes to BulkJob. Called by views (to create a job)
    and by Celery tasks / services (to advance it).
    """

    @staticmethod
    def create(job_type: str, user, total_rows: int = 0, request_id: str = '') -> BulkJob:
        return BulkJob.objects.create(
            job_type=job_type,
            status=BulkJob.Status.QUEUED,
            total_rows=total_rows,
            created_by=user if getattr(user, 'is_authenticated', False) else None,
            request_id=request_id or '',
        )

    @staticmethod
    def mark_running(job: BulkJob) -> BulkJob:
        job.status = BulkJob.Status.RUNNING
        fields = ['status', 'updated_at']
        if job.started_at is None:
            job.started_at = timezone.now()
            fields.append('started_at')
        job.save(update_fields=fields)
        return job

    @staticmethod
    def update_progress(job: BulkJob, *, processed=None, success=None, error=None) -> BulkJob:
        fields = ['updated_at']
        if processed is not None:
            job.processed_rows = processed
            fields.append('processed_rows')
        if success is not None:
            job.success_count = success
            fields.append('success_count')
        if error is not None:
            job.error_count = error
            fields.append('error_count')
        job.save(update_fields=fields)
        return job

    @staticmethod
    def increment_progress(job_id: int) -> None:
        """Atomic +1 processed/success — for parallel fan-out units, where a
        read-modify-write from concurrent workers would race."""
        BulkJob.objects.filter(pk=job_id).update(
            processed_rows=F('processed_rows') + 1,
            success_count=F('success_count') + 1,
            updated_at=timezone.now(),
        )

    @staticmethod
    def complete(job: BulkJob, result: dict | None = None) -> BulkJob:
        job.status = BulkJob.Status.COMPLETED
        job.finished_at = timezone.now()
        if result is not None:
            job.result = result
        job.save(update_fields=['status', 'finished_at', 'result', 'updated_at'])
        return job

    @staticmethod
    def fail(job: BulkJob, errors: list | None = None) -> BulkJob:
        job.status = BulkJob.Status.FAILED
        job.finished_at = timezone.now()
        if errors is not None:
            job.errors = errors
            job.error_count = len(errors)
        job.save(update_fields=['status', 'finished_at', 'errors', 'error_count', 'updated_at'])
        return job

    @staticmethod
    def mark_partial(job: BulkJob, errors: list | None = None) -> BulkJob:
        job.status = BulkJob.Status.PARTIAL
        job.finished_at = timezone.now()
        if errors is not None:
            job.errors = errors
            job.error_count = len(errors)
        job.save(update_fields=['status', 'finished_at', 'errors', 'error_count', 'updated_at'])
        return job
