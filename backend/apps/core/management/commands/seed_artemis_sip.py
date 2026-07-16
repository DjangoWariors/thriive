"""Seed the Artemis SIP layer: external metrics, external KPIs, the Expert 80/20
monthly+annual SIP with gate criteria, a GT SIP, and multi-month exception reasons.

Idempotent and ADDITIVE — existing rows (by code) are reused, never duplicated.
Illustrative *configuration* derived from ``docs/RFP - Project Artemis v1.pdf``
(SIP structures + exception table + gatekeeper grid), not platform logic.

Run AFTER ``seed_artemis_kpis`` (this needs its channels + KPI codes) and, for demo
people, ``seed_artemis_org`` (this reuses its ``ese`` / ``xse`` role types).
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hierarchy.models import Channel, NodeType
from apps.incentives.models import ExceptionCategory, IncentiveScheme
from apps.incentives.services import SchemeService
from apps.kpi_engine.models import ExternalMetric, KPIDefinition
from apps.kpi_engine.services import KPIService

D = Decimal

# code, name, unit, granularity, grain, aggregation
EXTERNAL_METRICS = [
    ('PRODUCTIVE_CALLS', 'Productive Calls', 'calls', 'geography_node', 'daily', 'sum'),
    ('ACTIVATION_ADHERENCE', 'Activation Adherence Score', '%', 'entity', 'monthly', 'latest'),
    ('BLUE_LINE_COUNT', 'Blue Line Count', 'lines', 'geography_node', 'daily', 'sum'),
    ('TLSD', 'Total Lines Sold per Day', 'lines', 'geography_node', 'daily', 'sum'),
    ('RCPA_PCT', 'RCPA Coverage', '%', 'entity', 'monthly', 'latest'),
    ('GEOFENCED_COVERAGE_PCT', 'Geofenced Coverage', '%', 'entity', 'monthly', 'latest'),
    ('IQUEST_SCORE', 'iQuest Score', '%', 'entity', 'monthly', 'latest'),
    ('COMPLIANCE_CLEAN', 'Clean Compliance Record', '%', 'entity', 'monthly', 'latest'),
]

# External KPIs over those feeds. Score metrics use a fixed benchmark of 100 so
# achievement % reads as the raw score; count metrics use geography allocations.
EXTERNAL_KPIS = [
    dict(code='PRODUCTIVE_CALLS', name='Productive Calls', category='execution', unit='calls',
         decimal_places=0, external_config={'metric_code': 'PRODUCTIVE_CALLS',
                                            'target_source': 'allocation'}),
    dict(code='ACTIVATION_ADHERENCE', name='Activation Adherence', category='execution', unit='%',
         external_config={'metric_code': 'ACTIVATION_ADHERENCE',
                          'target_source': 'fixed', 'fixed_target': 100}),
    dict(code='BLUE_LINE_COUNT', name='Blue Line Count', category='execution', unit='lines',
         decimal_places=0, external_config={'metric_code': 'BLUE_LINE_COUNT',
                                            'target_source': 'allocation'}),
    dict(code='TLSD', name='TLSD', category='execution', unit='lines', decimal_places=0,
         external_config={'metric_code': 'TLSD', 'target_source': 'allocation'}),
    dict(code='RCPA', name='RCPA Coverage', category='compliance', unit='%',
         external_config={'metric_code': 'RCPA_PCT', 'target_source': 'fixed', 'fixed_target': 100}),
    dict(code='GEOFENCE', name='Geofenced Coverage', category='compliance', unit='%',
         external_config={'metric_code': 'GEOFENCED_COVERAGE_PCT',
                          'target_source': 'fixed', 'fixed_target': 100}),
    dict(code='IQUEST', name='iQuest Score', category='compliance', unit='%',
         external_config={'metric_code': 'IQUEST_SCORE', 'target_source': 'fixed', 'fixed_target': 100}),
    dict(code='COMPLIANCE', name='Clean Compliance', category='compliance', unit='%',
         external_config={'metric_code': 'COMPLIANCE_CLEAN',
                          'target_source': 'fixed', 'fixed_target': 100}),
]

# A generic multiplier slab grid (RFP sample-calculation shape): pays from 90%,
# 1.0 at 100, accelerates to 1.8 past 105.
GRID = [
    ('0', '90', '0'), ('90', '100', '0.90'), ('100', '102', '1.00'),
    ('102', '105', '1.50'), ('105', None, '1.80'),
]

# RFP "SIP Structure Expert": monthly KPIs 80% of VP. kpi_code, category, weight
EXPERT_MONTHLY = [
    ('CORE_VALUE', 'sales', '15.00'),        # Sales — all Expert SKUs
    ('FOCUS_VALUE', 'sales', '10.00'),
    ('NPI_VALUE', 'sales', '10.00'),
    ('NHDD_VALUE', 'sales', '15.00'),
    ('FOCUS_EC', 'execution', '25.00'),
    ('ACTIVATION_ADHERENCE', 'execution', '25.00'),
]
# RFP gatekeeper grid for the Expert persona (all must pass).
EXPERT_GATES = [
    ('RCPA', '85.00'), ('GEOFENCE', '85.00'), ('IQUEST', '80.00'), ('COMPLIANCE', '100.00'),
]

# RFP "SIP Structure GT" example mix.
GT_MONTHLY = [
    ('CORE_VALUE', 'sales', '35.00'),
    ('FOCUS_NPI_VALUE', 'sales', '15.00'),
    ('EC_OVERALL', 'execution', '12.50'),
    ('TLSD', 'execution', '12.50'),
    ('BRAND_EC', 'execution', '12.50'),
    ('BRAND_VALUE_ENO', 'execution', '12.50'),
]

# RFP exception table (Expert channel) — duration expressed entirely as config.
EXCEPTION_CATEGORIES = [
    dict(code='new_joiner', name='New Joiner',
         description='Joined on/before the 20th → default 1x for the join month + 1; '
                     'after the 20th → join month + 2.',
         duration_config={'type': 'join_day_cutoff', 'cutoff_day': 20,
                          'months_on_or_before': 2, 'months_after': 3},
         default_sales='default_1x', default_execution='default_1x', default_gate='exempted'),
    dict(code='maternity_leave', name='Maternity / Paternity Leave',
         description='Leaves ≥ 7 working days, marked and approved in HRMS.',
         duration_config={'type': 'fixed', 'effect_months': 6}, requires_dates=True,
         default_sales='default_1x', default_execution='default_1x', default_gate='exempted'),
    dict(code='medical_leave', name='Medical Leave',
         duration_config={'type': 'fixed', 'effect_months': 2}, requires_dates=True,
         default_sales='default_1x', default_execution='default_1x', default_gate='exempted'),
    dict(code='transfer', name='Territory / Division Transfer',
         description='Default 1x for 1 month (2 for a newly formed territory).',
         duration_config={'type': 'fixed', 'effect_months': 2},
         default_sales='default_1x', default_execution='default_1x', default_gate='exempted'),
    dict(code='device_issue', name='Device Not Working (iPad)', channel='EXPERT',
         description='Actual performance; gate criteria exempted while the device is replaced.',
         default_sales='actual_performance', default_execution='actual_performance',
         default_gate='exempted'),
    dict(code='natural_calamity', name='Natural Calamity',
         description='> 5 working days impacted → default 1x for the month.',
         default_sales='default_1x', default_execution='default_1x', default_gate='exempted'),
]


class Command(BaseCommand):
    help = ('Seed the Artemis SIP layer: external metrics + KPIs, Expert 80/20 SIP with '
            'gates, GT SIP, exception reasons. Run after seed_artemis_kpis.')

    @transaction.atomic
    def handle(self, *args, **options):
        self._ensure_external_metrics()
        self._ensure_external_kpis()
        self._ensure_exception_categories()
        expert_type = self._role_type('ese', 'Expert Sales Executive', 'EXPERT')
        gt_type = self._role_type('xse', 'Extended Sales Executive', 'GT')
        self._ensure_scheme(
            code='EXPERT_SIP_MONTHLY', name='Expert SIP — Monthly KPIs (80%)',
            entity_type=expert_type, channel='EXPERT', frequency=IncentiveScheme.MONTHLY,
            vp_basis='80.00', kpis=EXPERT_MONTHLY, gates=EXPERT_GATES,
        )
        self._ensure_scheme(
            code='EXPERT_SIP_ANNUAL', name='Expert SIP — Annual Performance (20%)',
            entity_type=expert_type, channel='EXPERT', frequency=IncentiveScheme.ANNUAL,
            vp_basis='20.00', kpis=[('CORE_VALUE', 'sales', '100.00')], gates=[],
        )
        self._ensure_scheme(
            code='GT_SIP_MONTHLY', name='GT SIP — Monthly KPIs',
            entity_type=gt_type, channel='GT', frequency=IncentiveScheme.MONTHLY,
            vp_basis='100.00', kpis=GT_MONTHLY,
            gates=[('EC_OVERALL', '80.00')],
        )
        self.stdout.write(self.style.SUCCESS('Artemis SIP layer seeded.'))

    # ── building blocks ───────────────────────────────────────────────────────
    def _ensure_external_metrics(self):
        for code, name, unit, granularity, grain, agg in EXTERNAL_METRICS:
            _, created = ExternalMetric.objects.get_or_create(
                code=code,
                defaults={'name': name, 'unit': unit, 'granularity': granularity,
                          'period_grain': grain, 'default_aggregation': agg},
            )
            if created:
                self.stdout.write(f'  + metric {code}')

    def _ensure_external_kpis(self):
        for spec in EXTERNAL_KPIS:
            if KPIDefinition.objects.filter(code=spec['code'], is_current=True).exists():
                continue
            KPIService.create_kpi({**spec, 'kpi_type': KPIDefinition.EXTERNAL}, actor=None)
            self.stdout.write(f'  + external KPI {spec["code"]}')

    def _ensure_exception_categories(self):
        for spec in EXCEPTION_CATEGORIES:
            if ExceptionCategory.objects.filter(code=spec['code'], is_current=True).exists():
                continue
            channel = None
            if spec.get('channel'):
                channel = Channel.objects.filter(code=spec['channel'], is_active=True).first()
            ExceptionCategory.objects.create(
                code=spec['code'], name=spec['name'],
                description=spec.get('description', ''),
                channel=channel,
                duration_config=spec.get('duration_config', {}),
                requires_dates=spec.get('requires_dates', False),
                default_sales_kpi_action=spec['default_sales'],
                default_execution_kpi_action=spec['default_execution'],
                default_gatekeeper_action=spec['default_gate'],
                effective_from=date.today(),
            )
            self.stdout.write(f'  + exception reason {spec["code"]}')

    def _role_type(self, code: str, name: str, channel_code: str) -> NodeType:
        existing = NodeType.objects.filter(code=code, is_current=True).first()
        if existing:
            if not existing.incentive_eligible:
                existing.incentive_eligible = True
                existing.save(update_fields=['incentive_eligible', 'updated_at'])
            return existing
        return NodeType.objects.create(
            name=name, code=code, level_order=6, incentive_eligible=True,
            channel=Channel.objects.filter(code=channel_code).first(),
            effective_from=date.today(),
        )

    def _ensure_scheme(self, *, code, name, entity_type, channel, frequency,
                       vp_basis, kpis, gates):
        if IncentiveScheme.objects.filter(code=code, is_current=True).exists():
            self.stdout.write(f'  [~] scheme {code} already exists')
            return
        kpi_by_code = {
            k.code: k for k in KPIDefinition.objects.filter(
                code__in=[c for c, _, _ in kpis] + [c for c, _ in gates], is_current=True,
            )
        }
        missing = ({c for c, _, _ in kpis} | {c for c, _ in gates}) - set(kpi_by_code)
        if missing:
            self.stdout.write(self.style.WARNING(
                f'  [!] scheme {code} skipped — missing KPIs {sorted(missing)} '
                f'(run seed_artemis_kpis first).'
            ))
            return
        SchemeService.create({
            'name': name, 'code': code, 'description': 'Illustrative Artemis SIP component.',
            'target_entity_type': entity_type,
            'channel': Channel.objects.filter(code=channel).first(),
            'payout_frequency': frequency,
            'vp_basis_pct': D(vp_basis), 'overall_cap_pct': D('180.00'),
            'gates': [
                {'kpi': kpi_by_code[c], 'operator': 'gte', 'threshold_pct': D(t),
                 'display_order': i}
                for i, (c, t) in enumerate(gates)
            ],
            'gatekeeper_action': IncentiveScheme.ZERO_PAYOUT,
            'effective_from': date.today(),
            'kpis': [
                {'kpi': kpi_by_code[c], 'incentive_category': cat, 'weightage': D(w),
                 'display_order': i,
                 'tiers': [
                     {'min_achievement_pct': D(mn),
                      'max_achievement_pct': D(mx) if mx is not None else None,
                      'multiplier': D(mult)}
                     for mn, mx, mult in GRID
                 ]}
                for i, (c, cat, w) in enumerate(kpis)
            ],
        }, actor=None)
        self.stdout.write(self.style.SUCCESS(f'  + scheme {code} ({frequency}, VP {vp_basis}%)'))
