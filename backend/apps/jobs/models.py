from django.db import models

from apps.core.models import BaseModel


class BulkJob(BaseModel):
    """
    Durable status record for a long-running bulk operation (import, bulk move,
    bulk deactivate, role assignment, export).

    A job is created the moment a bulk request is accepted. It runs either
    inline (sync, no broker / eager mode) or on a Celery worker (async). Either
    way, progress and the final per-row error report are persisted here so the
    frontend can poll a single endpoint regardless of execution mode.
    """

    class JobType(models.TextChoices):
        ENTITY_IMPORT = 'entity_import', 'Node Import'
        USER_IMPORT = 'user_import', 'User Import'
        ENTITY_BULK_MOVE = 'entity_bulk_move', 'Node Bulk Move'
        ENTITY_BULK_DEACTIVATE = 'entity_bulk_deactivate', 'Node Bulk Deactivate'
        USER_BULK_ROLES = 'user_bulk_roles', 'User Bulk Role Assignment'
        ENTITY_EXPORT = 'entity_export', 'Node Export'
        SKU_IMPORT = 'sku_import', 'SKU Import'
        GEOGRAPHY_IMPORT = 'geography_import', 'Territory Import'
        TRANSACTION_IMPORT = 'transaction_import', 'Transaction Import'
        METRIC_IMPORT = 'metric_import', 'External Metric Value Import'
        TARGET_DISAGGREGATION = 'target_disaggregation', 'Target Disaggregation'
        TARGET_PHASING = 'target_phasing', 'Target Phasing'
        TARGET_IMPORT = 'target_import', 'Target Import'
        PLAN_RUN = 'plan_run', 'Target Plan Run'
        ACHIEVEMENT_COMPUTE = 'achievement_compute', 'Achievement Computation'
        PAYOUT_COMPUTE = 'payout_compute', 'Payout Computation'
        CYCLE_FINALIZE = 'cycle_finalize', 'Payout Cycle Finalize'
        CYCLE_COMPUTE = 'cycle_compute', 'Payout Cycle Compute'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        VALIDATING = 'validating', 'Validating'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        PARTIAL = 'partial', 'Partial'

    job_type = models.CharField(max_length=40, choices=JobType.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True,
    )

    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    # Per-row error report: [{"row": N, "errors": ["..."]}]
    errors = models.JSONField(default=list, blank=True)
    # Free-form result summary (created IDs, download path, counts, …)
    result = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        'accounts.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='bulk_jobs',
    )
    request_id = models.CharField(max_length=64, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    TERMINAL_STATUSES = frozenset((Status.COMPLETED, Status.FAILED, Status.PARTIAL))

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_type', 'status']),
            models.Index(fields=['created_by', '-created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.job_type} #{self.pk} ({self.status})'

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES
