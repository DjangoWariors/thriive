"""Seed the demo FMCG planning calendar + a starter top target.

Creates (idempotently): an FY container period with its 12 months, and a top target on the
root geography for SECONDARY_NSV on the first month. Targets are always set monthly; the
annual period only groups the months. Plan-based disaggregation (TargetPlan + runs) is
seeded by seed_artemis_plan.

Illustrative configuration only — a real client builds these through the UI.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hierarchy.models import GeographyNode
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod
from apps.targets.services import TargetService

FY = '2026-27'
ANNUAL_CODE = 'FY2026'


class Command(BaseCommand):
    help = 'Seed the demo FMCG planning calendar (FY + 12 months, monthly top target).'

    @transaction.atomic
    def handle(self, *args, **options):
        # The planning calendar (annual container → 12 months) is built by the same service the UI uses.
        TargetService.generate_fiscal_year(FY, start_month=4)
        self.stdout.write(f'  + planning calendar {ANNUAL_CODE} (annual container + 12 months)')

        month = TargetPeriod.objects.get(period_type=TargetPeriod.MONTHLY, start_date=date(2026, 4, 1))
        self._top_target(month)
        self.stdout.write(self.style.SUCCESS('FMCG target calendar seeded.'))

    def _top_target(self, month):
        kpi = KPIDefinition.objects.filter(code='SECONDARY_NSV', is_current=True).first()
        root = GeographyNode.objects.filter(parent__isnull=True, is_active=True).order_by('id').first()
        if kpi is None or root is None:
            self.stdout.write(self.style.WARNING(
                'Skipped top target (need SECONDARY_NSV KPI + a root geography node — run seed_fmcg_kpis and seed_demo).'))
            return
        TargetAllocation.objects.update_or_create(
            target_period=month, kpi=kpi, geography_node=root, channel=None, sku_group=None,
            defaults={'target_value': Decimal('10000000'), 'original_target_value': Decimal('10000000'),
                      'source': TargetAllocation.MANUAL, 'status': TargetAllocation.APPROVED},
        )
        self.stdout.write(f'  + top target 1,00,00,000 on {root.code} for SECONDARY_NSV ({month.code})')
