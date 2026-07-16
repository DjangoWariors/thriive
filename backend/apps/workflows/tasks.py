"""Celery adapters — SLA enforcement. Business logic stays in WorkflowService."""
from celery import shared_task


@shared_task
def escalate_overdue_workflows():
    """Apply each overdue active step's SLA policy (escalate / auto-approve / remind).
    Scheduled on django-celery-beat (see config settings)."""
    from .services import WorkflowService
    count = WorkflowService.sweep_overdue()
    return {'escalated': count}


@shared_task
def send_workflow_reminders():
    """Remind assignees of approvals approaching their SLA. Best-effort notifications."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.services import NotificationService
    from .models import WorkflowInstance, WorkflowStep
    from .services import WorkflowService

    soon = timezone.now() + timedelta(hours=12)
    sent = 0
    due = (
        WorkflowInstance.objects
        .filter(status__in=WorkflowInstance.OPEN_STATUSES,
                sla_due_at__isnull=False, sla_due_at__lte=soon)
        .prefetch_related('steps')
    )
    for inst in due:
        step = next((s for s in inst.steps.all() if s.status in WorkflowStep.OPEN_STATUSES), None)
        if step is None:
            continue
        for user in WorkflowService._step_users(step):
            NotificationService.send(user, 'workflow_reminder',
                                     WorkflowService._notify_ctx(inst, step))
            sent += 1
    return {'reminded': sent}
