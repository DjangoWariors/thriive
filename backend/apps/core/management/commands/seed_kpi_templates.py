"""Seed a default set of KPI builder templates (idempotent).

Templates are *configuration*, not platform logic: they drive the builder's
"pick a starting point" gallery and a client can edit, add, or remove them in admin.
This command provides a sensible default set at onboarding. Idempotent on ``code``.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.kpi_engine.models import KPIDefinition, KpiTemplate, Transaction

SECONDARY = Transaction.SECONDARY


def _measure(field, agg, net='sales_minus_returns', level=SECONDARY):
    return {'measure_field': field, 'aggregation': agg, 'net_logic': net, 'transaction_level': level}


TEMPLATES = [
    dict(
        code='SECONDARY_NSV', name='Secondary Sales (Net)', icon='trending-up',
        description='Total net sales value from distributor to retailer for the period.',
        category='Sales', unit='₹', decimal_places=0,
        kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
    ),
    dict(
        code='ECO', name='Effective Coverage (ECO)', icon='store',
        description='How many shops actually bought something (net sales above zero).',
        category='Distribution', unit='outlets', decimal_places=0,
        kpi_type=KPIDefinition.COUNT_DISTINCT,
        measure_config={**_measure('outlet_code', 'count_distinct', net='all'),
                        'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}},
    ),
    dict(
        code='DROP_SIZE', name='Drop Size (₹ per bill)', icon='receipt',
        description='Average value of each bill — total sales divided by number of bills.',
        category='Productivity', unit='₹', decimal_places=0,
        kpi_type=KPIDefinition.RATIO,
        ratio_config={'numerator': _measure('net_amount', 'sum'),
                      'denominator': _measure('bill_ref', 'count_distinct', net='gross_only')},
    ),
    dict(
        code='LINES_PER_BILL', name='Lines per Bill', icon='list-ordered',
        description='Average number of product lines on each bill — a range-selling measure.',
        category='Productivity', unit='lines', decimal_places=1,
        kpi_type=KPIDefinition.RATIO,
        ratio_config={'numerator': _measure('sku_code', 'count_distinct', net='gross_only'),
                      'denominator': _measure('bill_ref', 'count_distinct', net='gross_only')},
    ),
    dict(
        code='GROWTH_LY', name='Growth vs Last Year', icon='line-chart',
        description='Percentage change in net sales versus the same period last year.',
        category='Sales', unit='%', decimal_places=1,
        kpi_type=KPIDefinition.GROWTH, measure_config=_measure('net_amount', 'sum'),
        growth_config={'basis': 'last_year_same_period', 'output': 'growth_pct'},
    ),
    dict(
        code='FOCUS_COMPLIANT', name='Focus-SKU Compliance', icon='badge-check',
        description='A met / not-met flag for whether a focus product range was stocked.',
        category='Compliance', unit='', decimal_places=0,
        kpi_type=KPIDefinition.BOOLEAN,
        measure_config=_measure('quantity', 'sum', net='gross_only'),
        boolean_config={'operator': 'gte', 'threshold': 1},
        sku_filter={'type': 'group', 'group_code': 'FOCUS'},
    ),
]


class Command(BaseCommand):
    help = 'Seed default KPI builder templates (idempotent on code).'

    @transaction.atomic
    def handle(self, *args, **options):
        created = updated = 0
        for order, spec in enumerate(TEMPLATES, start=1):
            _, was_created = KpiTemplate.objects.update_or_create(
                code=spec['code'], defaults={**spec, 'display_order': order},
            )
            created += int(was_created)
            updated += int(not was_created)
            self.stdout.write(f'  {"+ " if was_created else "~ "}{spec["code"]} ({spec["kpi_type"]})')
        self.stdout.write(self.style.SUCCESS(f'KPI templates: {created} created, {updated} updated.'))
