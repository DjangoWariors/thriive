"""Seed a dashboard-ready FMCG dataset on top of the demo hierarchy.

Idempotent. Builds two monthly periods:
  • the *previous* calendar month, CLOSED — full-month transactions and a wide
    achievement spread (~74–125%), so payout runs on it look believable
    (multipliers across the grid, the odd gatekeeper failure)
  • the *current* calendar month, in flight — MTD transactions so run-rate and
    projections are live on the dashboard

Per period: a focused KPI set scoped to the field-force types (nsm/rsm/asm/ase),
secondary + primary transactions across retailer/distributor leaves, per-entity
TargetAllocations, computed Achievements + snapshots, and a couple of alert rules.

Run after `manage.py seed_demo --reset`. Then open the dashboard and pick a period;
run payouts (seed_fmcg_incentives --demo) against the previous month.
"""
import calendar
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.achievements.models import AlertRule
from apps.achievements.services import AchievementService
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.periods import working_days_between
from apps.targets.models import TargetAllocation, TargetPeriod

FIELD_FORCE = ['nsm', 'rsm', 'asm', 'ase']
SKUS = ['SKU-ATTA-5KG', 'SKU-OIL-1L', 'SKU-SOAP-100G', 'SKU-TEA-250G', 'SKU-BISCUIT-200G']

KPI_SPECS = [
    dict(code='SECONDARY_NSV', name='Secondary Sales (NSV)', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE,
         measure_config={'measure_field': 'net_amount', 'aggregation': 'sum',
                         'net_logic': 'sales_minus_returns', 'transaction_level': 'secondary'}),
    dict(code='PRIMARY_SALES', name='Primary Sales Value', category='sales', unit='₹',
         kpi_type=KPIDefinition.VALUE,
         measure_config={'measure_field': 'net_amount', 'aggregation': 'sum',
                         'net_logic': 'sales_minus_returns', 'transaction_level': 'primary'}),
    dict(code='BILLS_CUT', name='Bills Cut', category='distribution', unit='bills', decimal_places=0,
         kpi_type=KPIDefinition.COUNT_DISTINCT,
         measure_config={'measure_field': 'bill_ref', 'aggregation': 'count_distinct',
                         'net_logic': 'gross_only', 'transaction_level': 'secondary'}),
    dict(code='ECO', name='Effective Coverage', category='distribution', unit='outlets', decimal_places=0,
         kpi_type=KPIDefinition.COUNT_DISTINCT,
         measure_config={'measure_field': 'outlet_code', 'aggregation': 'count_distinct',
                         'net_logic': 'all', 'transaction_level': 'secondary',
                         'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}}),
]


class Command(BaseCommand):
    help = 'Seed dashboard-ready achievements (KPIs, period, transactions, targets, computation).'

    def add_arguments(self, parser):
        parser.add_argument('--clear-txns', action='store_true',
                            help='Delete demo-seeded transactions for the period before reseeding.')

    @transaction.atomic
    def handle(self, *args, **options):
        root = Node.objects.filter(code='NSM_001', is_current=True).first()
        if root is None:
            raise CommandError('Demo hierarchy not found. Run `manage.py seed_demo --reset` first.')

        kpis = self._ensure_kpis()
        today = date.today()
        prev_month_end = today.replace(day=1) - timedelta(days=1)

        # (anchor day, target spread, eco_story). The closed month gets a wider spread
        # so payout multipliers land across the whole grid, plus a deterministic
        # narrative: exactly one ASE narrowly misses the ECO gatekeeper.
        months = [
            (prev_month_end, (0.8, 1.35), True),
            (today, (0.85, 1.2), False),
        ]
        for anchor, target_spread, eco_story in months:
            period = self._ensure_period(anchor)
            as_of = min(today, period.end_date)
            self.stdout.write(f'=== {period.name} (through {as_of}) ===')

            if options['clear_txns']:
                Transaction.objects.filter(source='demo_seed',
                                           transaction_date__gte=period.start_date,
                                           transaction_date__lte=period.end_date).delete()

            self.stdout.write('--- Transactions ---')
            self._seed_transactions(root, period, as_of)

            self.stdout.write('--- Targets ---')
            self._seed_targets(root, period, kpis, as_of, target_spread, eco_story)

            self.stdout.write('--- Computing achievements ---')
            result = AchievementService.compute_period(period.id, as_of=as_of)
            self.stdout.write(self.style.SUCCESS(
                f"period={period.code} processed={result['records_processed']} "
                f"alerts={result['alerts']}"))

        self.stdout.write('--- Alert rules ---')
        self._ensure_alert_rules()
        self.stdout.write(self.style.SUCCESS(
            'Done. Open the dashboard and pick a period — payouts demo best on the previous month.'))

    # ── KPIs ──────────────────────────────────────────────────────────────────
    def _ensure_kpis(self):
        kpis = {}
        for spec in KPI_SPECS:
            kpi = KPIDefinition.objects.filter(code=spec['code'], is_current=True).first()
            if kpi is None:
                kpi = KPIDefinition.objects.create(
                    **spec, applicable_entity_types=FIELD_FORCE, effective_from=date.today(),
                )
                self.stdout.write(self.style.SUCCESS(f"  [+] KPI {spec['code']}"))
            else:
                self.stdout.write(f"  [~] KPI {spec['code']}")
            kpis[spec['code']] = kpi
        return kpis

    # ── period ────────────────────────────────────────────────────────────────
    def _ensure_period(self, anchor: date):
        start = anchor.replace(day=1)
        end = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
        code = f'DEMO-{anchor:%Y%m}'
        period = TargetPeriod.objects.filter(code=code).first()
        if period is None:
            period = TargetPeriod.objects.create(
                name=f'{anchor:%B %Y} (Demo)', code=code, period_type=TargetPeriod.MONTHLY,
                fiscal_year=f'{anchor.year}-{(anchor.year + 1) % 100:02d}',
                start_date=start, end_date=end, status=TargetPeriod.PUBLISHED,
                working_days=working_days_between(start, end),
            )
            self.stdout.write(self.style.SUCCESS(f"  [+] Period {period.name}"))
        else:
            self.stdout.write(f"  [~] Period {period.name}")
        return period

    # ── transactions ────────────────────────────────────────────────────────────
    def _seed_transactions(self, root, period, as_of):
        # Secondary sales attributed to retailer outlets; primary to distributors.
        retailers = self._descendants_of_type(root, 'retailer')
        distributors = self._descendants_of_type(root, 'distributor')
        if Transaction.objects.filter(source='demo_seed', transaction_date__gte=period.start_date,
                                      transaction_date__lte=period.end_date).exists():
            self.stdout.write('  [~] demo transactions already present (use --clear-txns to reseed)')
            return

        month_salt = period.start_date.month * 1000
        rows = []
        for r in retailers:
            rng = random.Random(42 + r.id + month_salt)
            channel = r.channel.code if r.channel_id else 'GT'
            n_bills = rng.randint(4, 9)
            for b in range(n_bills):
                day = rng.randint(0, max(0, (as_of - period.start_date).days))
                tdate = period.start_date + timedelta(days=day)
                bill = f'B-{r.code}-{period.start_date:%m}-{b:02d}'
                for _ in range(rng.randint(2, 5)):
                    net = Decimal(rng.randint(400, 5000))
                    rows.append(self._txn(r, tdate, 'secondary', 'sale', channel, r.code, bill,
                                          rng.choice(SKUS), net))
            # occasional return
            if rng.random() < 0.5:
                rows.append(self._txn(r, period.start_date + timedelta(days=2), 'secondary',
                                      'return', channel, r.code, f'CN-{r.code}', rng.choice(SKUS),
                                      Decimal(rng.randint(200, 1500))))

        for d in distributors:
            rng = random.Random(7 + d.id + month_salt)
            channel = d.channel.code if d.channel_id else 'GT'
            for p in range(rng.randint(2, 4)):
                day = rng.randint(0, max(0, (as_of - period.start_date).days))
                tdate = period.start_date + timedelta(days=day)
                net = Decimal(rng.randint(50000, 200000))
                rows.append(self._txn(d, tdate, 'primary', 'sale', channel, d.code,
                                      f'PB-{d.code}-{period.start_date:%m}-{p:02d}', rng.choice(SKUS), net))

        Transaction.objects.bulk_create(rows)
        self.stdout.write(self.style.SUCCESS(f'  [+] {len(rows)} transactions'))

    @staticmethod
    def _node_id_for(entity):
        """The geography node the sale is attributed to. Most demo partners (retailers,
        distributors) own no territory themselves — the town is owned by their ASE — so
        climb the org tree to the nearest ancestor with an owning assignment."""
        from apps.assignments.models import Assignment
        node = entity
        while node is not None:
            a = Assignment.objects.filter(
                assignee_id=node.id, role_in_scope='owner', is_active=True,
            ).first()
            if a:
                return a.scope_id
            node = node.parent
        return entity.id

    def _txn(self, entity, tdate, level, ttype, channel, outlet, bill, sku, net):
        gross = (net * Decimal('1.12')).quantize(Decimal('0.01'))
        return Transaction(
            attributed_node_id=self._node_id_for(entity), transaction_date=tdate,
            transaction_level=level, transaction_type=ttype, channel_code=channel,
            outlet_code=outlet, bill_ref=bill, sku_code=sku, gross_amount=gross,
            net_amount=net, quantity=Decimal('1'), source='demo_seed',
        )

    # ── targets ──────────────────────────────────────────────────────────────────
    def _seed_targets(self, root, period, kpis, as_of, target_spread=(0.85, 1.2),
                      eco_story=False):
        total_wd = period.working_days or working_days_between(period.start_date, period.end_date)
        elapsed_wd = max(1, working_days_between(period.start_date, as_of))
        entities = [root] + list(
            Node.objects.filter(path__startswith=root.path, is_current=True, is_active=True,
                                  entity_type__code__in=FIELD_FORCE).exclude(pk=root.pk)
        )
        # The incentive demo gatekeeps on ECO ≥ 80% (achievement ≈ 1/factor). Pin one
        # ASE just below the gate and keep the rest safely above it, so a payout run
        # shows exactly one gatekeeper failure instead of a random number of them.
        gate_miss_ase_id = None
        if eco_story:
            ase_ids = sorted(e.id for e in entities if e.entity_type.code == 'ase')
            gate_miss_ase_id = ase_ids[-1] if ase_ids else None
        created = 0
        for entity in entities:
            # Targets are geography-anchored on the territory the entity owns; the per-entity
            # number is derived back through the Assignment bridge at achievement time.
            owned = AssignmentService.owned_scope_ids_for_entity(entity.id, on=period.end_date)
            if not owned:
                continue
            node_id = owned[0]
            for kpi in kpis.values():
                achieved_td = KPICalculator(kpi, period.start_date, as_of).compute_for_entity(entity.id)
                if achieved_td <= 0:
                    continue
                expected_full = achieved_td * Decimal(total_wd) / Decimal(elapsed_wd)
                rng = random.Random(hash((entity.id, kpi.code, period.start_date.month)) & 0xFFFFFFFF)
                if eco_story and kpi.code == 'ECO' and entity.entity_type.code == 'ase':
                    spread = (1.28, 1.32) if entity.id == gate_miss_ase_id else (0.85, 1.18)
                else:
                    spread = target_spread
                factor = Decimal(str(round(rng.uniform(*spread), 3)))
                target = (expected_full * factor).quantize(Decimal('0.0001'))
                _, was_created = TargetAllocation.objects.update_or_create(
                    target_period=period, kpi=kpi, geography_node_id=node_id, channel=None, sku_group=None,
                    defaults={'target_value': target, 'original_target_value': target,
                              'status': TargetAllocation.APPROVED, 'source': TargetAllocation.MANUAL},
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f'  [+] {created} target allocations'))

    # ── alert rules ──────────────────────────────────────────────────────────────
    def _ensure_alert_rules(self):
        rules = [
            dict(code='AT_RISK', name='Territory at risk', metric=AlertRule.PROJECTED_PCT,
                 comparator='lt', threshold=Decimal('90'), severity=AlertRule.CRITICAL,
                 scope_entity_types=['ase', 'asm'],
                 message_template='{entity}: projected {value}% — below 90% target'),
            dict(code='LOW_GROWTH', name='Declining vs last year', metric=AlertRule.GROWTH_PCT,
                 comparator='lt', threshold=Decimal('0'), severity=AlertRule.WARNING,
                 scope_entity_types=['ase'],
                 message_template='{entity}: down {value}% vs last year'),
        ]
        for r in rules:
            if not AlertRule.objects.filter(code=r['code'], is_current=True).exists():
                AlertRule.objects.create(**r, effective_from=date.today())
                self.stdout.write(self.style.SUCCESS(f"  [+] AlertRule {r['code']}"))
            else:
                self.stdout.write(f"  [~] AlertRule {r['code']}")

    @staticmethod
    def _descendants_of_type(root, type_code):
        return list(
            Node.objects.filter(path__startswith=root.path, is_current=True, is_active=True,
                                  entity_type__code=type_code)
        )
