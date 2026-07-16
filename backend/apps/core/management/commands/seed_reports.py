from django.core.management.base import BaseCommand

from apps.reports.models import ReportDefinition

# One row per registered generator. param_schema reuses the NodeType
# attribute-schema shape (key/label/type/required/options).
_Cat = ReportDefinition.Category

_DATE_RANGE = [
    {'key': 'date_from', 'label': 'From Date', 'type': 'date', 'required': False},
    {'key': 'date_to', 'label': 'To Date', 'type': 'date', 'required': False},
    {'key': 'channel', 'label': 'Channel Code', 'type': 'string', 'required': False},
]
_PERIOD = [{'key': 'period', 'label': 'Target Period', 'type': 'integer', 'required': True}]

REPORTS_SEED = [
    # ── Sales & Distribution ────────────────────────────────────────────────
    {'code': 'primary_sales_register', 'name': 'Primary Sales Register', 'category': _Cat.SALES,
     'description': 'Company → distributor sell-in, by distributor and SKU.',
     'required_permission': 'report_sales', 'is_confidential': False,
     'default_formats': ['xlsx', 'pdf', 'csv'], 'param_schema': _DATE_RANGE},
    {'code': 'secondary_sales_register', 'name': 'Secondary Sales Register', 'category': _Cat.SALES,
     'description': 'Distributor → retailer sell-out, the main incentive driver.',
     'required_permission': 'report_sales', 'is_confidential': False, 'is_dataset': True,
     'default_formats': ['xlsx', 'pdf', 'csv'], 'param_schema': _DATE_RANGE},
    {'code': 'channel_mix', 'name': 'Channel Mix', 'category': _Cat.SALES,
     'description': 'Net sales split by channel with % share.',
     'required_permission': 'report_sales', 'is_confidential': False,
     'default_formats': ['xlsx', 'pdf', 'csv'], 'param_schema': _DATE_RANGE},
    # ── Targets & Achievement ───────────────────────────────────────────────
    {'code': 'target_vs_achievement', 'name': 'Target vs Achievement', 'category': _Cat.TARGETS,
     'description': 'Per entity × KPI, target vs achieved with % and gap.',
     'required_permission': 'report_targets', 'is_confidential': False, 'is_dataset': True,
     'default_formats': ['xlsx', 'pdf', 'csv'],
     'param_schema': _PERIOD + [{'key': 'kpi', 'label': 'KPI Code', 'type': 'string', 'required': False}]},
    # ── Incentive & Payout (confidential) ───────────────────────────────────
    {'code': 'payout_register', 'name': 'Payout Register', 'category': _Cat.INCENTIVE,
     'description': 'Node payout: VP → gross → cap → net, with gatekeeper status.',
     'required_permission': 'report_payout', 'is_confidential': True, 'is_dataset': True,
     'default_formats': ['xlsx', 'pdf', 'csv'],
     'param_schema': _PERIOD + [{'key': 'scheme', 'label': 'Scheme', 'type': 'integer', 'required': False}]},
    {'code': 'exception_register', 'name': 'Exception Register', 'category': _Cat.INCENTIVE,
     'description': 'Payout exceptions with the per-category treatment applied.',
     'required_permission': 'report_payout', 'is_confidential': False,
     'default_formats': ['xlsx', 'pdf', 'csv'],
     'param_schema': [{'key': 'period', 'label': 'Target Period', 'type': 'integer', 'required': False},
                      {'key': 'status', 'label': 'Status', 'type': 'string', 'required': False}]},
    # ── Master & Audit ──────────────────────────────────────────────────────
    {'code': 'entity_roster', 'name': 'Node Roster', 'category': _Cat.MASTER,
     'description': 'Org directory / field-force roster, scoped to your subtree.',
     'required_permission': 'report_master', 'is_confidential': False,
     'default_formats': ['xlsx', 'pdf', 'csv'],
     'param_schema': [
         {'key': 'entity_type', 'label': 'Node Type', 'type': 'string', 'required': False},
         {'key': 'status', 'label': 'Status', 'type': 'choice', 'required': False,
          'options': ['active', 'inactive', 'suspended', 'onboarding']}]},
    {'code': 'audit_trail_export', 'name': 'Audit Trail Export', 'category': _Cat.MASTER,
     'description': 'Audit log export for auditors (hash-verified rows).',
     'required_permission': 'audit_logs', 'is_confidential': True,
     'default_formats': ['xlsx', 'csv'],
     'param_schema': [
         {'key': 'date_from', 'label': 'From Date', 'type': 'date', 'required': False},
         {'key': 'date_to', 'label': 'To Date', 'type': 'date', 'required': False},
         {'key': 'action', 'label': 'Action', 'type': 'string', 'required': False}]},
]


class Command(BaseCommand):
    help = 'Seed the report catalog (ReportDefinition rows).'

    def handle(self, *args, **options):
        created = updated = 0
        for data in REPORTS_SEED:
            _, was_created = ReportDefinition.objects.update_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'category': data['category'],
                    'description': data['description'],
                    'required_permission': data['required_permission'],
                    'is_confidential': data['is_confidential'],
                    'is_dataset': data.get('is_dataset', False),
                    'default_formats': data['default_formats'],
                    'param_schema': data['param_schema'],
                    'is_active': True,
                },
            )
            created += was_created
            updated += not was_created
            self.stdout.write(f'  [{"+" if was_created else "~"}] {data["code"]}')

        # Retire catalog rows whose generator no longer ships (e.g. removed modules).
        stale = ReportDefinition.objects.filter(is_active=True).exclude(
            code__in=[d['code'] for d in REPORTS_SEED],
        )
        retired = stale.update(is_active=False)
        if retired:
            self.stdout.write(f'  [-] {retired} stale definition(s) retired')

        self.stdout.write(self.style.SUCCESS(
            f'Done. {created} created, {updated} updated. '
            f'Total: {ReportDefinition.objects.count()} reports.'))
