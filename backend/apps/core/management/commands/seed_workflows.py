"""Seed the default approval workflows + the FMCG exception-reason catalog.

These are *configuration*, not code — clients can edit them through the admin/API. The
FMCG defaults make a fresh deployment work out of the box (the same way ``seed_roles`` does).
"""
from datetime import date

from django.core.management.base import BaseCommand

from apps.incentives.models import ExceptionCategory, PayoutException
from apps.workflows.models import WorkflowDefinition

# Two-tier exception approval: the subject's direct manager always reviews; high-impact
# requests additionally need a national-head sign-off. Thresholds/SLA are config, not code.
PAYOUT_EXCEPTION_STANDARD = {
    'code': 'payout_exception_standard',
    'name': 'Payout Exception — Standard',
    'subject_type': 'incentives.PayoutException',
    'description': 'Manager review; national-head sign-off when financial impact is high.',
    'steps': [
        {'order': 1, 'name': 'Manager Review', 'assignee_rule': 'hierarchy_manager',
         'hierarchy_levels_up': 1, 'approval_mode': 'single',
         'condition': None, 'sla_hours': 48, 'on_sla_breach': 'escalate'},
        {'order': 2, 'name': 'National Head Sign-off', 'assignee_rule': 'role',
         'role_code': 'national_head', 'approval_mode': 'single',
         'condition': {'field': 'impact_amount', 'op': 'gt', 'value': '50000'},
         'sla_hours': 72, 'on_sla_breach': 'escalate'},
    ],
}

# A published target edit beyond its auto-approve band routes to the editor's immediate
# manager (the org reporting line), even though the target itself is geography-anchored.
TARGET_REVISION = {
    'code': 'target_revision',
    'name': 'Target Revision Approval',
    'subject_type': 'targets.TargetRevision',
    'description': 'Manager sign-off on a published target edit beyond its auto-approve band.',
    'steps': [
        {'order': 1, 'name': 'Manager Review', 'assignee_rule': 'hierarchy_manager',
         'hierarchy_levels_up': 1, 'approval_mode': 'single',
         'condition': None, 'sla_hours': 48, 'on_sla_breach': 'escalate'},
    ],
}

DEFINITIONS = [PAYOUT_EXCEPTION_STANDARD, TARGET_REVISION]

A, D1, Z = PayoutException.ACTUAL, PayoutException.DEFAULT_1X, PayoutException.ZERO
NOEX, EXEMPT = PayoutException.NO_EXEMPTION, PayoutException.EXEMPTED

# FMCG reason catalog. (sales_action, execution_action, gatekeeper_action, requires_dates)
CATEGORIES = [
    ('medical_leave', 'Medical Leave', D1, D1, EXEMPT, True),
    ('maternity_leave', 'Maternity Leave', D1, D1, EXEMPT, True),
    ('new_joiner', 'New Joiner', D1, A, EXEMPT, True),
    ('transfer', 'Mid-period Transfer', A, A, EXEMPT, True),
    ('natural_calamity', 'Natural Calamity', D1, D1, EXEMPT, True),
    ('device_issue', 'Device / App Issue', A, D1, NOEX, False),
    ('demise', 'Demise', D1, D1, EXEMPT, True),
    ('technical', 'Technical / Data Issue', A, A, NOEX, False),
    ('secondary_sales_dispute', 'Secondary Sales Dispute', A, A, NOEX, False),
    ('damage_expiry_claim', 'Damage / Expiry Claim', A, A, NOEX, True),
    ('scheme_dispute', 'Trade Scheme Dispute', A, A, NOEX, False),
]


class Command(BaseCommand):
    help = 'Seed default approval workflow definitions and the FMCG exception-reason catalog.'

    def handle(self, *args, **options):
        today = date.today()

        defs_created = 0
        for spec in DEFINITIONS:
            obj, created = WorkflowDefinition.objects.update_or_create(
                code=spec['code'], is_current=True,
                defaults={
                    'name': spec['name'], 'subject_type': spec['subject_type'],
                    'description': spec['description'], 'steps': spec['steps'],
                    'effective_from': today, 'is_active': True,
                },
            )
            defs_created += created
            self.stdout.write(('  [+] ' if created else '  [~] ') + obj.code)

        cats_created = 0
        for code, name, sales, execution, gk, needs_dates in CATEGORIES:
            obj, created = ExceptionCategory.objects.update_or_create(
                code=code, is_current=True,
                defaults={
                    'name': name, 'default_sales_kpi_action': sales,
                    'default_execution_kpi_action': execution,
                    'default_gatekeeper_action': gk, 'requires_dates': needs_dates,
                    'workflow_definition_code': 'payout_exception_standard',
                    'effective_from': today, 'is_active': True,
                },
            )
            cats_created += created
            self.stdout.write(('  [+] ' if created else '  [~] ') + f'category {obj.code}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {WorkflowDefinition.objects.filter(is_current=True).count()} definitions, '
            f'{ExceptionCategory.objects.filter(is_current=True).count()} categories.'
        ))
