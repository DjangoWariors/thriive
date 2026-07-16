"""MTD / run-rate projection — pure date math + the preview projection."""
from datetime import date
from decimal import Decimal

from apps.kpi_engine import periods


def test_working_days_excludes_sundays():
    # June 2026: 1st is a Monday. Full month has 30 days, 4 Sundays (7,14,21,28) → 26 working days.
    assert periods.working_days_between(date(2026, 6, 1), date(2026, 6, 30)) == 26


def test_project_full_period_doubles_at_half():
    # 13 working days elapsed of 26 at a run-rate of 5,000,000 → projects to 10,000,000.
    projected = periods.project_full_period(Decimal('5000000'), 13, 26)
    assert projected == Decimal('10000000')


def test_project_zero_elapsed_is_safe():
    assert periods.project_full_period(Decimal('100'), 0, 26) == Decimal('100')


def test_preview_returns_projection(db):
    from apps.assignments.services import AssignmentService
    from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
    from apps.kpi_engine.models import Transaction
    from apps.kpi_engine.services import KPIService

    et = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    e = Node.objects.create(entity_type=et, name='ASE', code='ASE1', effective_from=date.today())
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['town'])
    node = GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN1', level='town')
    AssignmentService.create(assignee_id=e.id, scope_id=node.id, effective_from=date(2025, 1, 1))
    # 5,000,000 booked in the first half of June, attributed to the owned territory.
    Transaction.objects.create(attributed_node_id=node.id, transaction_date=date(2026, 6, 5),
                               transaction_type=Transaction.SALE, net_amount=Decimal('5000000'))
    config = {'code': 'NSV', 'name': 'NSV', 'kpi_type': 'value',
              'measure_config': {'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'all'}}
    out = KPIService.preview_kpi(config, e.id, date(2026, 6, 1), date(2026, 6, 30), as_of=date(2026, 6, 15))
    assert out['mtd_value'] == '5000000.00'
    # 13 working days elapsed (Jun 1-15 minus Sundays 7 & 14), 26 total → 5M × 26/13 = 10M.
    assert out['working_days_elapsed'] == 13
    assert out['projected_full_period'] == '10000000.00'
