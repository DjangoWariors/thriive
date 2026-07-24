"""Scale gate for the planning-grid export.

A whole-root export must stay bounded in BOTH memory and queries as the territory tree
grows — the file streams, so nothing may accumulate per row. The first cut of the owner
columns built a ``{path: Node}`` index for the whole subtree and peaked at **563 MB on a
200k-outlet root**; resolving ownership inside the cursor (plus a cached ancestor walk for
unowned territories) brought the same export to **25 MB**. This test pins that.

Measured at 200k outlets before landing: 25 MB peak, ~100 queries, ~93 s streamed. Run here
at a smaller N so CI stays quick — the invariants under test are size-independent, and the
memory ceiling below is deliberately far under what an O(territories) index would need.

The shape that matters is one owner per outlet (every retailer owns their own node), the
worst case for owner resolution.
"""
import tracemalloc
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.models import Assignment
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import PlanKpi, TargetAllocation, TargetPeriod, TargetPlan
from apps.targets.plan_services import PlanService

N_NODES = 50_000
_FROM = date(2025, 1, 1)


@pytest.fixture
def big_world(db):
    geo_type = GeographyType.objects.create(name='G', code='g', levels=['region', 'outlet'])
    region = GeographyNode.objects.create(geography_type=geo_type, name='R', code='R', level='region')
    GeographyNode.objects.bulk_create(
        [GeographyNode(geography_type=geo_type, name=f'O{i}', code=f'O{i}', level='outlet',
                       parent=region, path=f'{region.path}O{i}/', depth=1)
         for i in range(N_NODES)],
        batch_size=5000,
    )
    node_ids = list(GeographyNode.objects.filter(depth=1).values_list('id', flat=True))

    ret_type = NodeType.objects.create(name='Retailer', code='RET', level_order=2, effective_from=_FROM)
    Node.objects.bulk_create(
        [Node(entity_type=ret_type, name=f'Ret{i}', code=f'RET{i}', effective_from=_FROM,
              path=f'/RET{i}/', depth=0)
         for i in range(N_NODES)],
        batch_size=5000,
    )
    owner_ids = list(Node.objects.filter(entity_type=ret_type).values_list('id', flat=True))
    Assignment.objects.bulk_create(
        [Assignment(assignee_id=o, scope_id=s, role_in_scope=Assignment.Role.OWNER,
                    effective_from=_FROM)
         for o, s in zip(owner_ids, node_ids)],
        batch_size=5000,
    )

    period = TargetPeriod.objects.create(
        code='SCALE-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    kpi = KPIDefinition.objects.create(
        code='K', name='K', kpi_type=KPIDefinition.VALUE, effective_from=_FROM,
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'})
    plan = TargetPlan.objects.create(name='Scale', code='SCALE', period=period,
                                     root_geography=region, status=TargetPlan.PUBLISHED)
    PlanKpi.objects.create(plan=plan, kpi=kpi, top_value=Decimal('1'))
    TargetAllocation.objects.bulk_create(
        [TargetAllocation(target_period=period, plan=plan, kpi=kpi, geography_node_id=n,
                          target_value=Decimal('100'), original_target_value=Decimal('100'))
         for n in node_ids],
        batch_size=5000,
    )
    return {'plan': plan, 'kpi': kpi, 'region': region}


@pytest.mark.django_db
def test_whole_root_export_stays_bounded(big_world, django_assert_max_num_queries):
    plan, kpi = big_world['plan'], big_world['kpi']

    tracemalloc.start()
    try:
        # Neither budget may scale with N_NODES: the cursor streams and ownership resolves
        # inside it, so this holds at 200k just as it does here.
        with django_assert_max_num_queries(120):
            fields, rows = PlanService.export_rows(plan, [kpi], parent=big_world['region'])
            count = owners_seen = 0
            for row in rows:
                count += 1
                owners_seen += bool(row['owner_code'])
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == N_NODES
    assert owners_seen == N_NODES  # every outlet resolved its own direct owner
    assert fields[:6] == PlanService.IMPORT_FIELDS
    # A whole-subtree owner index needed ~2.8 KB/territory; the streamed form needs none.
    assert peak_bytes < 80 * 1024 * 1024, f'export peaked at {peak_bytes / 1e6:.0f} MB'
