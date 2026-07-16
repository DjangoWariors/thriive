"""Seed a demo FMCG field-force incentive scheme so payout runs work end-to-end.

Creates (idempotently) scheme FF_MONTHLY targeting the ASE entity type:
  PRIMARY_SALES (sales, 40%) + SECONDARY_NSV (sales, 30%) +
  ECO (execution, 15%) + BILLS_CUT (execution, 15%),
  step multiplier grids, per-KPI cap 1.5x, overall cap 150% of variable pay,
  ECO >= 80% gatekeeper (zero payout on failure).

The KPI set deliberately matches what seed_demo_achievements computes, so a payout
run on the closed previous demo month produces a believable spread of multipliers.

Note: industry plans sometimes ramp linearly inside a band ("80-100% → 0.8-1.0x");
the tier model intentionally approximates this with fine-grained steps.

With --demo, also seeds VariablePay (₹60,000, full eligibility) for every active ASE
on every DEMO-* monthly period, plus one pending example exception on the closed month.

Illustrative configuration only — a real client builds these through the UI.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hierarchy.models import Node, NodeType
from apps.incentives.models import IncentiveScheme, PayoutException, VariablePay
from apps.incentives.services import SchemeService
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetPeriod

SCHEME_CODE = 'FF_MONTHLY'
ASE_TYPE_CODE = 'ase'
DEMO_VP = Decimal('60000.00')

# Step approximation of the classic 80-100 ramp; below 80 pays nothing.
VALUE_GRID = [
    ('0', '80', '0.000'),
    ('80', '90', '0.800'),
    ('90', '100', '0.900'),
    ('100', '120', '1.200'),
    ('120', None, '1.300'),
]

KPI_SPEC = [
    ('PRIMARY_SALES', 'sales', '40.00', VALUE_GRID),
    ('SECONDARY_NSV', 'sales', '30.00', VALUE_GRID),
    ('ECO', 'execution', '15.00', VALUE_GRID),
    ('BILLS_CUT', 'execution', '15.00', VALUE_GRID),
]
GATEKEEPER_KPI = 'ECO'


class Command(BaseCommand):
    help = 'Seed a demo FMCG field-force incentive scheme (run seed_fmcg_kpis first).'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true',
                            help='Also seed VariablePay for active ASEs + an example exception.')

    @transaction.atomic
    def handle(self, *args, **options):
        ase_type = NodeType.objects.filter(code=ASE_TYPE_CODE, is_current=True).first()
        if ase_type is None:
            self.stdout.write(self.style.WARNING(
                f"NodeType '{ASE_TYPE_CODE}' not found — run seed_demo first. Nothing seeded."))
            return
        kpis = {
            k.code: k for k in KPIDefinition.objects.filter(
                code__in=[code for code, *_ in KPI_SPEC], is_current=True,
            )
        }
        missing = [code for code, *_ in KPI_SPEC if code not in kpis]
        if missing:
            self.stdout.write(self.style.WARNING(
                f'Missing KPIs {missing} — run seed_demo_achievements (or seed_fmcg_kpis) first. '
                f'Nothing seeded.'))
            return
        if not ase_type.incentive_eligible:
            ase_type.incentive_eligible = True
            ase_type.save(update_fields=['incentive_eligible', 'updated_at'])
            self.stdout.write(f'  [~] NodeType {ASE_TYPE_CODE}: marked incentive_eligible')

        scheme = IncentiveScheme.objects.filter(code=SCHEME_CODE, is_current=True).first()
        if scheme:
            self.stdout.write(f'  [~] Scheme {SCHEME_CODE} already exists (v{scheme.version})')
        else:
            scheme = SchemeService.create({
                'name': 'Field Force Monthly Incentive',
                'code': SCHEME_CODE,
                'description': 'Monthly field-force plan: variable pay × KPI weightage × '
                               'multiplier grid, effective-coverage gatekeeper at 80%.',
                'target_entity_type': ase_type,
                'channel': None,
                'vp_basis_pct': Decimal('100.00'),
                'overall_cap_pct': Decimal('150.00'),
                'gates': [{'kpi': kpis[GATEKEEPER_KPI], 'operator': 'gte',
                           'threshold_pct': Decimal('80.00')}],
                'gatekeeper_action': IncentiveScheme.ZERO_PAYOUT,
                'effective_from': date.today(),
                'kpis': [
                    {
                        'kpi': kpis[code],
                        'incentive_category': category,
                        'weightage': Decimal(weight),
                        'multiplier_cap': Decimal('1.500'),
                        'display_order': order,
                        'tiers': [
                            {'min_achievement_pct': Decimal(tmin),
                             'max_achievement_pct': Decimal(tmax) if tmax is not None else None,
                             'multiplier': Decimal(mult)}
                            for tmin, tmax, mult in grid
                        ],
                    }
                    for order, (code, category, weight, grid) in enumerate(KPI_SPEC)
                ],
            })
            self.stdout.write(self.style.SUCCESS(f'  [+] Scheme {SCHEME_CODE} (v1) created'))

        if options['demo']:
            self._seed_demo_data(scheme, ase_type)

        self.stdout.write(self.style.SUCCESS('FMCG incentive scheme seeded.'))

    def _seed_demo_data(self, scheme, ase_type):
        today = date.today()
        periods = list(TargetPeriod.objects.filter(
            period_type=TargetPeriod.MONTHLY, code__startswith='DEMO-',
        ).order_by('start_date'))
        if not periods:
            periods = list(TargetPeriod.objects.filter(
                period_type=TargetPeriod.MONTHLY,
            ).order_by('start_date')[:1])
        if not periods:
            self.stdout.write(self.style.WARNING(
                '  No monthly period found — run seed_demo_achievements first; demo data skipped.'))
            return

        ases = list(Node.objects.filter(
            entity_type__code=ASE_TYPE_CODE, is_current=True, is_active=True, status='active',
        ))
        for period in periods:
            created = 0
            for entity in ases:
                _, was_created = VariablePay.objects.get_or_create(
                    entity=entity, target_period=period,
                    defaults={'amount': DEMO_VP, 'source': VariablePay.MANUAL},
                )
                created += was_created
            self.stdout.write(f'  [+] VariablePay for {created}/{len(ases)} ASEs on {period.code}')

        # The example exception goes on the closed month — that's where payout runs demo.
        closed = [p for p in periods if p.end_date < today]
        exc_period = closed[-1] if closed else periods[0]
        if ases and not PayoutException.objects.filter(
            entity=ases[0], target_period=exc_period, is_active=True,
        ).exists():
            PayoutException.objects.create(
                entity=ases[0], target_period=exc_period, category='new_joiner',
                sales_kpi_action=PayoutException.DEFAULT_1X,
                execution_kpi_action=PayoutException.ACTUAL,
                gatekeeper_action=PayoutException.NO_EXEMPTION,
                reason='Joined mid-month; sales KPIs defaulted to 1x for the ramp-up period.',
                status=PayoutException.PENDING,
            )
            self.stdout.write(f'  [+] Example pending exception for {ases[0].code} on {exc_period.code}')
