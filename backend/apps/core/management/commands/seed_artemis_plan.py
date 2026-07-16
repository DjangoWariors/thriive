"""Seed a complete demo plan — the whole plan workflow, one command.

Builds on the demo world (`seed_demo` + `seed_fmcg_kpis`): LY history on the demo
districts, a blended split recipe, then drives the real pipeline end-to-end through
PlanService — baseline → top numbers → spatial commit → review cascade (tasks land with
the RSMs). Targets are set monthly, so the plan anchors to the April month of the fiscal
year. The plan is left *in review*, which is the most demoable state: grid, explain,
gap board and reviewer inbox all live.

Idempotent: skips everything that already exists; re-running a partly-built plan says so.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hierarchy.models import GeographyNode
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.targets.models import AllocationRecipe, PlanRun, TargetPeriod, TargetPlan
from apps.targets.plan_services import PlanService
from apps.targets.services import TargetService

PLAN_CODE = 'PLAN-2026-04'
RECIPE_CODE = 'AOP_CONTRIB'
FY = '2026-27'

# LY (Apr'25–Mar'26) secondary sales per demo district — the contribution signal.
LY_HISTORY = {
    'GEO_DL_NEW': ('400000', 3),   # (monthly amount, outlets billed)
    'GEO_DL_WEST': ('250000', 2),
    'GEO_UP_NOIDA': ('150000', 2),
    'GEO_KA_BLR': ('200000', 2),
}


class Command(BaseCommand):
    help = 'Seed a complete demo monthly plan (LY history + recipe + plan driven to in-review).'

    @transaction.atomic
    def handle(self, *args, **options):
        root = GeographyNode.objects.filter(code='GEO_IN', is_active=True).first()
        nsv = KPIDefinition.objects.filter(code='SECONDARY_NSV', is_current=True).first()
        eco = KPIDefinition.objects.filter(code='ECO', is_current=True).first()
        if root is None or nsv is None:
            raise CommandError('Demo world missing — run seed_demo and seed_fmcg_kpis first.')

        if TargetPlan.objects.filter(code=PLAN_CODE).exists():
            self.stdout.write(self.style.WARNING(f'Plan {PLAN_CODE} already exists — nothing to do.'))
            return

        TargetService.generate_fiscal_year(FY, start_month=4)
        month = TargetPeriod.objects.get(period_type=TargetPeriod.MONTHLY, start_date=date(2026, 4, 1))
        self.stdout.write(f'  + planning calendar FY{FY[:4]} (plan month: {month.code})')
        self._ly_history()
        recipe = self._recipe()

        kpis = [{'kpi_id': nsv.id, 'recipe_id': recipe.id,
                 'baseline_spec': {'components': [{'basis': 'ly_same_period', 'weight': 100}]}}]
        if eco is not None:
            kpis.append({'kpi_id': eco.id, 'recipe_id': recipe.id,
                         'baseline_spec': {'components': [{'basis': 'ly_same_period', 'weight': 100}]}})
        plan = PlanService.create_plan(
            {'name': f'{month.name} Operating Plan', 'code': PLAN_CODE,
             'period_id': month.id, 'root_geography_id': root.id,
             'review_levels': ['region']},
            kpis=kpis,
        )
        self.stdout.write(f'  + plan {PLAN_CODE} ({len(kpis)} KPI(s))')

        self._run(plan, PlanRun.BASELINE, commit=False)
        for plan_kpi in plan.plan_kpis.select_related('kpi'):
            plan_kpi.refresh_from_db()
            top = plan_kpi.derived_top_value or Decimal('1000000')
            PlanService.set_top_number(plan, plan_kpi.kpi, top)
            self.stdout.write(f'  + top number {plan_kpi.kpi.code}: {top} (derived suggestion)')

        self._run(plan, PlanRun.SPATIAL, commit=True)

        PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)
        tasks = plan.review_tasks.count()
        self.stdout.write(self.style.SUCCESS(
            f'Demo plan ready: {PLAN_CODE} is in review with {tasks} region task(s) '
            f'(RSM North/South). Open /targets to walk the whole flow.'))

    def _ly_history(self):
        created = 0
        for code, (amount, outlets) in LY_HISTORY.items():
            node = GeographyNode.objects.filter(code=code, is_active=True).first()
            if node is None:
                continue
            for month in (4, 7, 10, 1):  # one quarter-marker sale per season, LY
                year = 2026 if month == 1 else 2025
                for o in range(outlets):
                    _, was_created = Transaction.objects.get_or_create(
                        source='demo_seed', external_ref=f'AOP-LY-{code}-{year}{month:02d}-{o}',
                        defaults={
                            'attributed_node_id': node.id, 'transaction_date': date(year, month, 15),
                            'transaction_type': Transaction.SALE,
                            'transaction_level': Transaction.SECONDARY,
                            'outlet_code': f'OUT-{code}-{o}', 'channel_code': 'GT',
                            'gross_amount': Decimal(amount), 'net_amount': Decimal(amount),
                            'quantity': Decimal('1'),
                        },
                    )
                    created += int(was_created)
        self.stdout.write(f'  + {created} LY history transaction(s)')

    def _recipe(self) -> AllocationRecipe:
        recipe = AllocationRecipe.objects.filter(code=RECIPE_CODE, is_current=True).first()
        if recipe:
            return recipe
        recipe = AllocationRecipe.objects.create(
            name='70% contribution + 30% equal, +10% growth', code=RECIPE_CODE,
            effective_from=date.today(),
            weight_components=[{'source': 'contribution', 'weight': 70},
                               {'source': 'equal', 'weight': 30}],
            base_window={'basis': 'ly_same_period'},
            growth={'default_pct': 10},
            constraints={'no_negative': True},
            rounding={'unit': 1000},
        )
        self.stdout.write(f'  + recipe {RECIPE_CODE}')
        return recipe

    def _run(self, plan, kind, commit):
        run = PlanService.start_run(plan, kind)
        if run.status != PlanRun.STAGED:
            errors = run.job.errors if run.job else []
            raise CommandError(f'{kind} run ended {run.status}: {errors}')
        stats = run.stats or {}
        self.stdout.write(f'  + {kind} run staged ({stats.get("staged_rows", 0)} rows)')
        if commit:
            result = PlanService.commit_run(run)
            self.stdout.write(f'  + {kind} committed ({result["created"]} created, {result["updated"]} updated)')
