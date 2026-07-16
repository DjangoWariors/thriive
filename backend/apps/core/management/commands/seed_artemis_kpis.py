"""Seed the Haleon "Project Artemis" KPI set + its supporting master data.

Idempotent and ADDITIVE — existing channels, SKU groups and KPIs (by code) are reused, never
duplicated. Mirrors ``seed_fmcg_kpis``. These are illustrative *configuration* records derived
from ``docs/RFP - Project Artemis v1.pdf`` (see ``docs/ARTEMIS_KPI_REFERENCE.md``), not platform
logic — a real client tweaks them through the builder.

Seeds:
  • Channels: GT, MT, ECOM, EXPERT, NHDD
  • SKU groups: FOCUS, NPI, ENO (brand), FOCUS_NPI (focus ∪ npi)
  • 10 KPIs: Core/NPI/Brand-Eno/Focus/Focus-NPI/NHDD value, EC overall/brand/focus, Unique SKUs

The RFP's Productive Calls / Activation Adherence / Blue line / TLSD are intentionally omitted —
they need SFA/external data, not the Transaction table, or a precise definition from the client.

Pass ``--demo`` to also seed a handful of SKUs + transactions so the achievement/preview screens
show non-zero numbers.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.hierarchy.models import Channel
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.services import KPIService
from apps.master_data.models import SKU, SKUGroup

SECONDARY = Transaction.SECONDARY


def _measure(field, agg, net='sales_minus_returns', level=SECONDARY):
    return {'measure_field': field, 'aggregation': agg, 'net_logic': net, 'transaction_level': level}


def _ec_measure(net='all'):
    """Effective Coverage: distinct outlets whose net sales (sales − returns) clear 0."""
    return {**_measure('outlet_code', 'count_distinct', net=net),
            'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}}


CHANNELS = [
    ('GT', 'General Trade'),
    ('MT', 'Modern Trade'),
    ('ECOM', 'E-commerce'),
    ('EXPERT', 'Expert'),
    ('NHDD', 'NHDD'),
]

# code, name, filter_type, rule (None → explicit, populated in handle)
SKU_GROUPS = [
    ('FOCUS', 'Focus SKUs', SKUGroup.FILTER_RULE, {'is_focus': True}),
    ('NPI', 'New Products', SKUGroup.FILTER_RULE, {'is_npi': True}),
    ('ENO', 'Eno (Brand)', SKUGroup.FILTER_RULE, {'brand': 'Eno'}),
    ('FOCUS_NPI', 'Focus + NPI', SKUGroup.FILTER_EXPLICIT, None),
]

KPIS = [
    dict(code='CORE_VALUE', name='Core Value', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum')),
    dict(code='NPI_VALUE', name='NPI Value', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'NPI'}),
    dict(code='BRAND_VALUE_ENO', name='Brand Value (Eno)', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'ENO'}),
    dict(code='FOCUS_VALUE', name='Focus SKU Value', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'FOCUS'}),
    dict(code='FOCUS_NPI_VALUE', name='Focus/NPI Value', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'FOCUS_NPI'}),
    dict(code='NHDD_VALUE', name='NHDD Value (All Haleon SKUs)', category='value', unit='₹',
         kpi_type=KPIDefinition.VALUE, measure_config=_measure('net_amount', 'sum'),
         channel_filter=['NHDD']),
    dict(code='EC_OVERALL', name='Effective Coverage (Overall)', category='execution', unit='outlets',
         decimal_places=0, kpi_type=KPIDefinition.COUNT_DISTINCT, measure_config=_ec_measure()),
    dict(code='BRAND_EC', name='Brand EC (Eno)', category='execution', unit='outlets',
         decimal_places=0, kpi_type=KPIDefinition.COUNT_DISTINCT, measure_config=_ec_measure(),
         sku_filter={'type': 'group', 'group_code': 'ENO'}),
    dict(code='FOCUS_EC', name='Focus SKU EC', category='execution', unit='outlets',
         decimal_places=0, kpi_type=KPIDefinition.COUNT_DISTINCT, measure_config=_ec_measure(),
         sku_filter={'type': 'group', 'group_code': 'FOCUS'}),
    dict(code='UNIQUE_SKUS', name='Total Unique SKUs', category='execution', unit='SKUs',
         decimal_places=0, kpi_type=KPIDefinition.COUNT_DISTINCT,
         measure_config=_measure('sku_code', 'count_distinct', net='gross_only')),
]

# Demo SKUs (only with --demo). code, name, brand, is_focus, is_npi
DEMO_SKUS = [
    ('ART-CORE', 'Core Product', '', False, False),
    ('ART-FOCUS', 'Focus Product', '', True, False),
    ('ART-NPI', 'New Product', '', False, True),
    ('ART-ENO', 'Eno Antacid', 'Eno', True, False),
]


class Command(BaseCommand):
    help = 'Seed the Haleon Artemis KPI set + master data (idempotent). --demo also seeds sample data.'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Also seed sample SKUs + transactions.')

    @transaction.atomic
    def handle(self, *args, **options):
        self._ensure_channels()
        if options['demo']:
            self._ensure_demo_skus()  # before groups so FOCUS_NPI/ENO resolve to something
        self._ensure_sku_groups()

        created = skipped = 0
        for spec in KPIS:
            if KPIDefinition.objects.filter(code=spec['code'], is_current=True).exists():
                skipped += 1
                continue
            KPIService.create_kpi(dict(spec), actor=None)
            created += 1
            self.stdout.write(f'  + {spec["code"]} ({spec["kpi_type"]})')
        self.stdout.write(self.style.SUCCESS(f'Artemis KPIs: {created} created, {skipped} skipped.'))

        if options['demo']:
            self._seed_demo_transactions()

    # ── master data ──────────────────────────────────────────────────────────
    def _ensure_channels(self):
        for code, name in CHANNELS:
            Channel.objects.get_or_create(code=code, defaults={'name': name})

    def _ensure_sku_groups(self):
        for code, name, ftype, rule in SKU_GROUPS:
            group, _ = SKUGroup.objects.get_or_create(
                code=code,
                defaults={'name': name, 'filter_type': ftype, 'filter_rules': rule or {}},
            )
            # FOCUS_NPI is an explicit group (the rule resolver ANDs, it can't OR focus∪npi) —
            # (re)populate it from the current focus/NPI SKUs each run so it stays in step.
            if code == 'FOCUS_NPI':
                group.skus.set(SKU.objects.filter(Q(is_focus=True) | Q(is_npi=True), is_active=True))

    def _ensure_demo_skus(self):
        for code, name, brand, is_focus, is_npi in DEMO_SKUS:
            SKU.objects.get_or_create(
                code=code,
                defaults={'name': name, 'brand': brand, 'is_focus': is_focus, 'is_npi': is_npi},
            )

    # ── demo transactions ────────────────────────────────────────────────────
    def _seed_demo_transactions(self):
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import GeographyNode

        # Attribute to the deepest owned territory so demo sales roll UP through every ancestor owner.
        owner = (
            Assignment.objects.filter(role_in_scope='owner', is_active=True)
            .select_related('scope').order_by('-scope__depth').first()
        )
        if owner is not None:
            node_id = owner.scope_id
        else:
            node = GeographyNode.objects.filter(is_active=True).first()
            node_id = node.id if node else None
        if node_id is None:
            self.stdout.write(self.style.WARNING('No geography/assignments found — skipping demo transactions.'))
            return

        today = date.today()
        skus = ['ART-CORE', 'ART-FOCUS', 'ART-NPI', 'ART-ENO']
        rows = []
        # GT secondary sales across 4 outlets × the demo SKUs (lights up Core / EC / Unique / group KPIs)
        for i in range(8):
            rows.append(Transaction(
                attributed_node_id=node_id, transaction_date=today - timedelta(days=i),
                transaction_type=Transaction.SALE, transaction_level=SECONDARY,
                channel_code='GT', sku_code=skus[i % 4], outlet_code=f'OUT{i % 4}',
                bill_ref=f'ART-BILL{i}', gross_amount=Decimal('1100'), net_amount=Decimal('1000'),
                quantity=Decimal('5'), uom='cases', source='manual_entry',
                external_ref=f'ART-DEMO-{node_id}-{i}',
            ))
        # A couple of NHDD-channel sales so NHDD Value is non-zero
        for i in range(2):
            rows.append(Transaction(
                attributed_node_id=node_id, transaction_date=today - timedelta(days=i),
                transaction_type=Transaction.SALE, transaction_level=SECONDARY,
                channel_code='NHDD', sku_code='ART-ENO', outlet_code=f'NHDD-OUT{i}',
                bill_ref=f'ART-NHDD-{i}', gross_amount=Decimal('900'), net_amount=Decimal('800'),
                quantity=Decimal('4'), uom='cases', source='manual_entry',
                external_ref=f'ART-DEMO-NHDD-{node_id}-{i}',
            ))
        Transaction.objects.bulk_create(rows, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(f'Demo transactions seeded for node {node_id}.'))
