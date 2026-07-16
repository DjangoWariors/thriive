"""Incentives → notification triggers.

Helpers the payout and exception services call on key events. They resolve the relevant
User and hand off to ``apps.notifications.services.NotificationService``. Every call is
best-effort — a notification failure must never break a payout run or exception action.
Safe (no-op) if templates are missing.
"""


def _user_for_entity(entity):
    return getattr(entity, 'user', None)


def _send(user, template_code: str, context: dict) -> None:
    if user is None:
        return
    try:
        from apps.notifications.services import NotificationService
        NotificationService.send(user, template_code, context)
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def notify_payout_ready(run, targets) -> None:
    """``targets`` is an iterable of ``(entity, total_payout)`` for entities paid in this run."""
    scheme_name = run.scheme.name
    period_name = run.target_period.name
    for entity, total in targets or []:
        _send(_user_for_entity(entity), 'payout_ready',
              {'scheme': scheme_name, 'period': period_name,
               'entity': entity.name, 'total_payout': str(total)})


def notify_exception_raised(exc, checker_user) -> None:
    _send(checker_user, 'exception_raised',
          {'entity': exc.entity.name, 'period': exc.target_period.name,
           'category': exc.category, 'reason': exc.reason})


def notify_exception_resolved(exc) -> None:
    """Notify the raiser that their exception was approved/rejected. Reads ``exc.status``."""
    _send(getattr(exc, 'requested_by', None), 'exception_resolved',
          {'entity': exc.entity.name, 'period': exc.target_period.name,
           'status': exc.status, 'rejection_reason': exc.rejection_reason or ''})
