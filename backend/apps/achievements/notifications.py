"""Achievements → notification triggers.

Thin helpers the achievement service calls when a computation finishes. They resolve the
loginable User behind each entity and hand off to
``apps.notifications.services.NotificationService``. Every call is best-effort — a
notification failure must never break a compute run. Safe (no-op) if templates are missing.
"""


def _send(user, template_code: str, context: dict) -> None:
    if user is None:
        return
    try:
        from apps.notifications.services import NotificationService
        NotificationService.send(user, template_code, context)
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def notify_achievements_computed(period, entity_ids, computation_id=None) -> None:
    """One ``achievement_computed`` notification per entity-with-a-user (deduped across KPIs)."""
    ids = {i for i in (entity_ids or []) if i}
    if not ids:
        return
    try:
        from apps.accounts.models import User
        users = User.objects.filter(entity_id__in=ids, is_active=True).only('id', 'email')
    except Exception:  # noqa: BLE001
        return
    ctx = {'period_code': period.code, 'period_name': getattr(period, 'name', '') or period.code,
           'computation_id': computation_id}
    for user in users:
        _send(user, 'achievement_computed', ctx)
