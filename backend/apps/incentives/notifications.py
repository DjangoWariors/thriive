"""Incentives → notification triggers.

Helpers the payout and exception services call on key events. They resolve the relevant
User and hand off to ``apps.notifications.services.NotificationService``. Every call is
best-effort — a notification failure must never break a payout run or exception action.
Safe (no-op) if templates are missing.
"""


def _send(user, template_code: str, context: dict) -> None:
    if user is None:
        return
    try:
        from apps.notifications.services import NotificationService
        NotificationService.send(user, template_code, context)
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def notify_payout_ready(run, targets) -> None:
    """``targets`` is an iterable of ``(entity, total_payout)`` for entities paid in this run.

    Bulk path: a final run can pay thousands of entities — users resolve in one query and
    the notifications land via ``send_bulk``, never a send per payee inside the run's
    transaction."""
    targets = list(targets or [])
    if not targets:
        return
    try:
        from apps.accounts.models import User
        from apps.notifications.services import NotificationService
        users = {u.entity_id: u for u in User.objects.filter(
            entity_id__in=[e.pk for e, _ in targets], is_active=True)}
        NotificationService.send_bulk('payout_ready', [
            (users.get(entity.pk), {'scheme': run.scheme.name, 'period': run.target_period.name,
                                    'entity': entity.name, 'total_payout': str(total)})
            for entity, total in targets
        ])
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def notify_exception_raised(exc, checker_user) -> None:
    _send(checker_user, 'exception_raised',
          {'entity': exc.entity.name, 'period': exc.target_period.name,
           'category': exc.category, 'reason': exc.reason})


def notify_exception_resolved(exc) -> None:
    """Notify the raiser that their exception was approved/rejected. Reads ``exc.status``."""
    _send(getattr(exc, 'requested_by', None), 'exception_resolved',
          {'entity': exc.entity.name, 'period': exc.target_period.name,
           'status': exc.status, 'rejection_reason': exc.rejection_reason or ''})
