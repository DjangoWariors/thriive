"""In-app (and email/SMS-ready) notifications.

A ``NotificationTemplate`` is the configurable copy for an event (``earning_credited``,
``redemption_approved``, …). ``NotificationService.send`` renders a template against a
context and persists a per-user ``Notification`` for the bell/feed. Channels beyond
``in_app`` (email/SMS) are stubbed for per-client wiring.
"""
from django.db import models

from apps.core.models import BaseModel


class NotificationTemplate(BaseModel):
    IN_APP = 'in_app'
    EMAIL = 'email'
    SMS = 'sms'
    CHANNEL_CHOICES = [(IN_APP, 'In-app'), (EMAIL, 'Email'), (SMS, 'SMS')]

    code = models.CharField(max_length=80, unique=True)
    event = models.CharField(max_length=80, blank=True, default='', db_index=True)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=IN_APP)
    title_template = models.CharField(max_length=255, default='')
    body_template = models.TextField(blank=True, default='')
    category = models.CharField(max_length=40, blank=True, default='')  # earning/redemption/kyc/claim
    link_template = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'notifications_template'
        ordering = ['code']

    def __str__(self):
        return self.code


class Notification(BaseModel):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    code = models.CharField(max_length=80, blank=True, default='', db_index=True)
    category = models.CharField(max_length=40, blank=True, default='', db_index=True)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    link = models.CharField(max_length=255, blank=True, default='')
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'notifications_notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read'], name='notif_user_read_idx'),
        ]

    def __str__(self):
        return f'{self.title} → user {self.user_id}'


class NotificationPreference(BaseModel):
    """Per-user opt-in matrix. ``prefs`` maps a notification category to a
    per-channel toggle: ``{"<category>": {"in_app": bool, "email": bool, "sms": bool}}``.
    A missing category or channel key means **opted in** — so existing users with
    no row keep receiving everything."""

    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE,
                                related_name='notification_pref')
    prefs = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'notifications_preference'

    def __str__(self):
        return f'prefs(user {self.user_id})'
