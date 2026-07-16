"""Seed a canonical FMCG KPI set so the engine can be exercised end-to-end.

Idempotent: existing current KPIs (by code) are skipped. Pass --demo to also create
a handful of demo transactions for the first leaf entity, so /preview returns non-zero.

These are illustrative *configuration* records, not platform logic — a real client would
define their own KPIs through the builder UI. They live here only to make the platform
demonstrable and to back the manual-test guide.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.services import KPIService
from apps.master_data.models import SKUGroup

SECONDARY = Transaction.SECONDARY


def _measure(field, agg, net='sales_minus_returns', level=SECONDARY):
    return {'measure_field': field, 'aggregation': agg, 'net_logic': net, 'transaction_level': level}


KPIS = [
    # code, name, category, type, extra config
    dict(code='PRIMARY_SALES', name='Primary Sales Value', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE,
         measure_config=_measure('net_amount', 'sum', level=Transaction.PRIMARY)),
    dict(code='SECONDARY_NSV', name='Secondary Sales (NSV)', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum')),
    dict(code='SECONDARY_GSV', name='Secondary Sales (GSV)', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('gross_amount', 'sum', net='gross_only')),
    dict(code='SECONDARY_VOLUME', name='Secondary Volume (cases)', category='sales', unit='cases',
         decimal_places=3, kpi_type=KPIDefinition.VALUE, measure_config=_measure('quantity', 'sum', net='all')),
    dict(code='ECO', name='Effective Coverage (net > 0 per outlet)', category='distribution', unit='outlets',
         decimal_places=0, kpi_type=KPIDefinition.COUNT_DISTINCT,
         measure_config={**_measure('outlet_code', 'count_distinct', net='all'),
                         'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}}),
    dict(code='BILLS_CUT', name='Bills Cut', category='distribution', unit='bills', decimal_places=0,
         kpi_type=KPIDefinition.COUNT_DISTINCT,
         measure_config=_measure('bill_ref', 'count_distinct', net='gross_only')),
    dict(code='LINES_PER_BILL', name='Lines per Bill', category='distribution', unit='lines',
         kpi_type=KPIDefinition.RATIO,
         ratio_config={'numerator': _measure('sku_code', 'count_distinct', net='gross_only'),
                       'denominator': _measure('bill_ref', 'count_distinct', net='gross_only')}),
    dict(code='DROP_SIZE', name='Drop Size (₹ per bill)', category='distribution', unit='₹',
         kpi_type=KPIDefinition.RATIO,
         ratio_config={'numerator': _measure('net_amount', 'sum'),
                       'denominator': _measure('bill_ref', 'count_distinct', net='gross_only')}),
    dict(code='SECONDARY_GROWTH_LY', name='Secondary Growth vs LY', category='sales', unit='%',
         kpi_type=KPIDefinition.GROWTH, measure_config=_measure('net_amount', 'sum'),
         growth_config={'basis': 'last_year_same_period', 'output': 'growth_pct'}),
    dict(code='FOCUS_SALES', name='Focus SKU Sales', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'FOCUS'}),
    dict(code='NPI_SALES', name='New Product Sales', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'NPI'}),
    dict(code='MSL_COMPLIANCE', name='MSL Compliance (≥10 SKUs)', category='compliance', unit='flag',
         decimal_places=0, kpi_type=KPIDefinition.BOOLEAN,
         measure_config=_measure('sku_code', 'count_distinct', net='gross_only'),
         boolean_config={'operator': 'gte', 'threshold': 10}),
    # Composite must come last — its components must already exist.
    dict(code='SALES_SCORE', name='Weighted Sales Score', category='sales', unit='index',
         kpi_type=KPIDefinition.COMPOSITE,
         composite_config={'expression': '0.7 * SECONDARY_NSV + 0.3 * FOCUS_SALES',
                           'components': [{'kpi_code': 'SECONDARY_NSV'}, {'kpi_code': 'FOCUS_SALES'}]}),
]


class Command(BaseCommand):
    help = 'Seed a canonical FMCG KPI set (idempotent). --demo also seeds demo transactions.'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Also seed demo transactions.')

    @transaction.atomic
    def handle(self, *args, **options):
        self._ensure_sku_groups()
        created = skipped = 0
        for spec in KPIS:
            if KPIDefinition.objects.filter(code=spec['code'], is_current=True).exists():
                skipped += 1
                continue
            KPIService.create_kpi(dict(spec), actor=None)
            created += 1
            self.stdout.write(f'  + {spec["code"]} ({spec["kpi_type"]})')
        self.stdout.write(self.style.SUCCESS(f'KPIs: {created} created, {skipped} skipped.'))

        if options['demo']:
            self._seed_demo_transactions()

    def _ensure_sku_groups(self):
        for code, name, rule in (
            ('FOCUS', 'Focus SKUs', {'is_focus': True}),
            ('NPI', 'New Products', {'is_npi': True}),
        ):
            SKUGroup.objects.get_or_create(
                code=code,
                defaults={'name': name, 'filter_type': SKUGroup.FILTER_RULE, 'filter_rules': rule},
            )

    def _seed_demo_transactions(self):
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import Node, GeographyNode

        # Attribute to the deepest owned territory (a leaf district/outlet, typically an ASE's),
        # so the demo sales roll UP through every ancestor owner (ASE→ASM→RSM→NSM), not just one.
        owner = (
            Assignment.objects.filter(role_in_scope='owner', is_active=True)
            .select_related('assignee', 'scope').order_by('-scope__depth').first()
        )
        if owner is not None:
            entity, node_id = owner.assignee, owner.scope_id
        else:
            entity = Node.objects.filter(
                entity_type__is_leaf=True, is_current=True, is_active=True,
            ).first() or Node.objects.filter(is_current=True, is_active=True).first()
            if entity is None:
                self.stdout.write(self.style.WARNING('No entities found — skipping demo transactions.'))
                return
            node = GeographyNode.objects.filter(is_active=True).first()
            node_id = node.id if node else None
        if node_id is None:
            self.stdout.write(self.style.WARNING('No geography nodes found — skipping demo transactions.'))
            return

        today = date.today()
        rows = []
        for i in range(6):  # 6 outlets, 1 bill each, current period
            rows.append(Transaction(
                attributed_node_id=node_id, transaction_date=today - timedelta(days=i),
                transaction_type=Transaction.SALE, transaction_level=SECONDARY,
                channel_code='GT', sku_code=f'SKU{i % 4}', outlet_code=f'OUT{i}',
                bill_ref=f'BILL{i}', gross_amount=Decimal('1000'), net_amount=Decimal('900'),
                quantity=Decimal('5'), uom='cases', source='manual_entry',
                external_ref=f'DEMO-{node_id}-{i}',
            ))
        # last-year same period, for growth
        for i in range(3):
            rows.append(Transaction(
                attributed_node_id=node_id, transaction_date=today.replace(year=today.year - 1) - timedelta(days=i),
                transaction_type=Transaction.SALE, transaction_level=SECONDARY,
                channel_code='GT', sku_code=f'SKU{i}', outlet_code=f'OUT{i}',
                bill_ref=f'LYBILL{i}', gross_amount=Decimal('800'), net_amount=Decimal('750'),
                quantity=Decimal('4'), uom='cases', source='manual_entry',
                external_ref=f'DEMO-LY-{entity.id}-{i}',
            ))
        Transaction.objects.bulk_create(rows, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(
            f'Demo transactions seeded for entity {entity.code or entity.id}.'
        ))
