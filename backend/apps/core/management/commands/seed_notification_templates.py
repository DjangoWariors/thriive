"""Seed default in-app notification templates (incentives, achievements, workflows)."""
from django.core.management.base import BaseCommand

from apps.notifications.models import NotificationTemplate

TEMPLATES = [
    # — Achievements —
    ('achievement_computed', 'achievement', 'Achievements updated',
     'Your {period_name} achievements have been updated.', '/achievements'),

    # — Incentives / payouts —
    ('payout_ready', 'payout', 'Payout ready',
     'Your {period} payout of ₹{total_payout} is ready ({scheme}).', '/incentives/payouts'),
    ('exception_raised', 'exception', 'Exception needs review',
     'An exception for {entity} ({category}) needs your review.', '/exceptions'),
    ('exception_resolved', 'exception', 'Exception {status}',
     'Your exception for {entity} was {status}. {rejection_reason}', '/exceptions'),

    # — Targets (plan review cascade) —
    ('target_review_pending', 'approval', 'Targets awaiting your review',
     'The {plan_name} targets for {territory} are waiting for your review.', '/targets'),

    # — Workflows (approval engine) —
    ('workflow_pending', 'approval', 'Approval pending',
     '{title} — awaiting your review at: {step_name}.', '/workflows/pending'),
    ('workflow_resolved', 'approval', 'Request {outcome}',
     '{title} was {outcome}.', '/workflows/pending'),
    ('workflow_escalated', 'approval', 'Approval escalated',
     '{title} was escalated to you (SLA breached).', '/workflows/pending'),
    ('workflow_reminder', 'approval', 'Approval reminder',
     'Reminder: {title} is awaiting your review at {step_name}.', '/workflows/pending'),
]


class Command(BaseCommand):
    help = 'Seed default in-app notification templates across all modules.'

    def handle(self, *args, **options):
        created = updated = 0
        for code, category, title, body, link in TEMPLATES:
            _, was_created = NotificationTemplate.objects.update_or_create(
                code=code,
                defaults={'event': code, 'channel': NotificationTemplate.IN_APP,
                          'category': category, 'title_template': title, 'body_template': body,
                          'link_template': link, 'is_active': True},
            )
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(
            f'Notification templates: {created} created, {updated} updated.'))
