"""P1 scale gate: 10k geography nodes × 5 KPIs computes in a bounded number of queries
(chunked bulk upserts + grouped aggregates — no per-row or per-node work) and lands the
right numbers on both layers."""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement, TerritoryAchievement
from apps.achievements.services import AchievementService
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.targets.models import TargetAllocation, TargetPeriod

N_NODES = 10_000
N_KPIS = 5


@pytest.mark.django_db
def test_10k_nodes_5_kpis_bounded_queries(django_assert_max_num_queries):
    period = TargetPeriod.objects.create(
        name='June 2026', code='JUN26S', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), working_days=26,
        status=TargetPeriod.PUBLISHED,
    )
    geo_type = GeographyType.objects.create(name='G', code='g', levels=['region', 'town'])
    region = GeographyNode.objects.create(
        geography_type=geo_type, name='R', code='R', level='region',
    )
    towns = GeographyNode.objects.bulk_create(
        [
            GeographyNode(geography_type=geo_type, name=f'T{i}', code=f'T{i}', level='town',
                          parent=region, path=f'{region.path}T{i}/', depth=1)
            for i in range(N_NODES)
        ],
        batch_size=1000,
    )

    nsm_type = NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, incentive_eligible=True,
        effective_from=date(2025, 1, 1),
    )
    nsm = Node.objects.create(
        entity_type=nsm_type, name='NSM', code='NSM', effective_from=date(2025, 1, 1),
    )
    AssignmentService.create(assignee_id=nsm.id, scope_id=region.id,
                             effective_from=date(2025, 1, 1))

    kpis = [
        KPIDefinition.objects.create(
            code=f'K{i}', name=f'K{i}', kpi_type=KPIDefinition.VALUE,
            applicable_entity_types=['NSM'], effective_from=date(2025, 1, 1),
            measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
        )
        for i in range(N_KPIS)
    ]

    TargetAllocation.objects.bulk_create(
        [
            TargetAllocation(target_period=period, kpi=k, geography_node=t,
                             target_value=Decimal('100'), original_target_value=Decimal('100'))
            for k in kpis for t in towns
        ],
        batch_size=1000,
    )

    # 200 sales of 40 on 200 distinct towns (including towns[0]).
    Transaction.objects.bulk_create([
        Transaction(attributed_node_id=towns[i * 37].id, transaction_date=date(2026, 6, 5),
                    transaction_type=Transaction.SALE, transaction_level=Transaction.SECONDARY,
                    channel_code='GT', gross_amount=Decimal('0'), net_amount=Decimal('40'),
                    quantity=Decimal('0'))
        for i in range(200)
    ])

    with django_assert_max_num_queries(600):
        result = AchievementService.compute_period(period.id, as_of=date(2026, 6, 11))

    assert result['errors'] == []
    assert result['territory_records'] == N_NODES * N_KPIS

    sample = TerritoryAchievement.objects.get(
        target_period=period, kpi=kpis[0], node=towns[0],
    )
    assert sample.achieved_value == Decimal('40.0000')
    assert sample.achievement_pct == Decimal('40.00')

    # Person layer: the NSM's actual is the whole-region sum; its target the plan rollup.
    ach = Achievement.objects.get(target_period=period, kpi=kpis[0], entity=nsm)
    assert ach.achieved_value == Decimal('8000.0000')       # 200 × 40
    assert ach.target_value == Decimal('1000000.0000')      # 10k towns × 100
