"""Celery adapters for notification delivery — retry/logging only."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_email(self, email: str, subject: str, body: str) -> None:
    from django.core.mail import send_mail
    try:
        send_mail(subject, body, None, [email])
    except Exception as exc:  # noqa: BLE001 — delivery must never surface to the trigger
        logger.warning('notification email to %s failed: %s', email, exc)
        raise self.retry(exc=exc)
