from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.audit.models import AccessLog, AuditLog, ComputationLog, RetentionPolicy
from apps.audit.services import AuditService

# Which model each retention policy log_type sweeps.
_SWEEP_MODELS = {
    RetentionPolicy.LogType.AUDIT: AuditLog,
    RetentionPolicy.LogType.ACCESS: AccessLog,
    RetentionPolicy.LogType.COMPUTATION: ComputationLog,
    # REPORT_ARTIFACT is swept by the reports app (it owns the files on disk).
}


@shared_task
def sweep_retention() -> dict:
    """
    Apply each RetentionPolicy: delete rows older than retain_days where the
    strategy is 'delete'. The sweep records its own action in the audit log so
    the deletion itself is accountable.
    """
    now = timezone.now()
    summary = {}
    for policy in RetentionPolicy.objects.filter(is_active=True):
        model = _SWEEP_MODELS.get(policy.log_type)
        if model is None or policy.archive_strategy != 'delete':
            continue
        cutoff = now - timedelta(days=policy.retain_days)
        deleted, _ = model.objects.filter(timestamp__lt=cutoff).delete()
        summary[policy.log_type] = deleted

    if summary:
        AuditService.log('retention_sweep', 'audit.RetentionPolicy', 0, None, summary)
    return summary
