"""Notification business logic."""
from django.utils import timezone

from apps.audit.services import AuditService

from .models import Notification, NotificationPreference, NotificationTemplate

CHANNELS = ['in_app', 'email', 'sms']


class _SafeDict(dict):
    def __missing__(self, key):
        return ''


def _render(tmpl: str, context: dict) -> str:
    try:
        return tmpl.format_map(_SafeDict(context))
    except Exception:  # noqa: BLE001 — never let copy formatting break a send
        return tmpl


class NotificationService:

    @staticmethod
    def send(user, template_code: str, context: dict | None = None) -> Notification | None:
        if user is None:
            return None
        context = context or {}
        tmpl = NotificationTemplate.objects.filter(code=template_code, is_active=True).first()
        if tmpl is None:
            title = context.get('title') or template_code.replace('_', ' ').title()
            body = context.get('body', '')
            category = context.get('category', '')
            link = context.get('link', '')
        else:
            title = _render(tmpl.title_template, context)
            body = _render(tmpl.body_template, context)
            category = tmpl.category
            link = _render(tmpl.link_template, context)
        if not NotificationPreferenceService.is_allowed(user, category, 'in_app'):
            return None
        notif = Notification.objects.create(
            user=user, code=template_code, category=category, title=title, body=body,
            link=link, metadata=context if isinstance(context, dict) else {},
        )
        # Email delivers async (SMS remains a per-client wiring stub).
        if (tmpl is not None and tmpl.channel == NotificationTemplate.EMAIL
                and getattr(user, 'email', None)
                and NotificationPreferenceService.is_allowed(user, category, 'email')):
            try:
                from .tasks import send_notification_email
                send_notification_email.delay(user.email, title, body)
            except Exception:  # noqa: BLE001 — a broker outage must not break the mutation
                pass
        return notif

    @staticmethod
    def send_bulk(template_code: str, recipients) -> int:
        """Fan-out variant of ``send``: one template fetch, one preference query, chunked
        bulk inserts — in-app only. For events with thousands of recipients (a final
        payout run's payees), per-recipient ``send`` would hold the caller's transaction
        open across thousands of queries. ``recipients`` = iterable of ``(user, context)``;
        None users are skipped."""
        recipients = [(u, c or {}) for u, c in recipients if u is not None]
        if not recipients:
            return 0
        tmpl = NotificationTemplate.objects.filter(code=template_code, is_active=True).first()
        prefs = {
            p.user_id: p.prefs for p in NotificationPreference.objects.filter(
                user_id__in=[u.pk for u, _ in recipients])
        }
        rows = []
        for user, context in recipients:
            if tmpl is None:
                title = context.get('title') or template_code.replace('_', ' ').title()
                body, category, link = context.get('body', ''), context.get('category', ''), context.get('link', '')
            else:
                title = _render(tmpl.title_template, context)
                body = _render(tmpl.body_template, context)
                category, link = tmpl.category, _render(tmpl.link_template, context)
            if not prefs.get(user.pk, {}).get(category, {}).get('in_app', True):
                continue  # same opt-out default as is_allowed: missing keys = allowed
            rows.append(Notification(user=user, code=template_code, category=category,
                                     title=title, body=body, link=link, metadata=context))
        for i in range(0, len(rows), 1000):
            Notification.objects.bulk_create(rows[i:i + 1000], batch_size=1000)
        return len(rows)

    @staticmethod
    def unread_count(user) -> int:
        return Notification.objects.filter(user=user, is_read=False).count()

    @staticmethod
    def mark_read(notif: Notification) -> Notification:
        if not notif.is_read:
            notif.is_read = True
            notif.read_at = timezone.now()
            notif.save(update_fields=['is_read', 'read_at', 'updated_at'])
        return notif

    @staticmethod
    def mark_all_read(user) -> int:
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True, read_at=timezone.now())


class NotificationPreferenceService:

    @staticmethod
    def get(user) -> dict:
        pref = NotificationPreference.objects.filter(user=user).first()
        return pref.prefs if pref is not None else {}

    @staticmethod
    def set(user, prefs: dict) -> NotificationPreference:
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        old = pref.prefs
        pref.prefs = prefs or {}
        pref.save(update_fields=['prefs', 'updated_at'])
        AuditService.log('update', 'notifications.NotificationPreference', pref.pk, user,
                         {'old': old, 'new': pref.prefs})
        return pref

    @staticmethod
    def is_allowed(user, category: str, channel: str) -> bool:
        """Opt-out check. Missing category/channel keys default to allowed, so
        users without a preference row keep receiving every notification."""
        if user is None:
            return False
        prefs = NotificationPreferenceService.get(user)
        return bool(prefs.get(category, {}).get(channel, True))

    @staticmethod
    def available_categories() -> list[str]:
        return list(
            NotificationTemplate.objects.filter(is_active=True)
            .exclude(category='')
            .values_list('category', flat=True)
            .distinct()
            .order_by('category')
        )
