"""TerritoryAchievement — the plan-tracking fact (P1, payout & achievements revamp).

One row per committed TargetAllocation dimension; actuals aggregate the node's own
subtree (no Assignment resolution). Exact-Decimal assertions per the engine testing
standard; re-run convergence and stale-dimension cleanup guard the nightly semantics.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement, TerritoryAchievement
from apps.achievements.services import AchievementService
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.master_data.models import SKU, SKUGroup
from apps.targets.models import TargetAllocation

from .conftest import AS_OF, mk_alloc, mk_txn


def geo_alloc(period, kpi, node, value, channel=None, sku_group=None):
    return TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=node,
        channel=channel, sku_group=sku_group,
        target_value=Decimal(str(value)), original_target_value=Decimal(str(value)),
    )


def txn_on(node, **kw):
    defaults = dict(
        transaction_date=date(2026, 6, 5), transaction_type=Transaction.SALE,
        transaction_level=Transaction.SECONDARY, channel_code='GT',
        gross_amount=Decimal('0'), net_amount=Decimal('0'), quantity=Decimal('0'),
    )
    defaults.update(kw)
    return Transaction.objects.create(attributed_node_id=node.id, **defaults)


def fact(period, kpi, node, **extra):
    return TerritoryAchievement.objects.get(
        target_period=period, kpi=kpi, node=node, **extra,
    )


@pytest.mark.django_db
def test_multi_level_facts_exact(tree, period, primary_kpi):
    """Allocations at several levels at once: every level's actual is its own subtree sum."""
    geo_alloc(period, primary_kpi, tree['town1'], 1000)
    geo_alloc(period, primary_kpi, tree['town2'], 2000)
    geo_alloc(period, primary_kpi, tree['area'], 3000)
    geo_alloc(period, primary_kpi, tree['region'], 4000)
    txn_on(tree['town1'], net_amount=Decimal('850'))
    txn_on(tree['town2'], net_amount=Decimal('500'))

    result = AchievementService.compute_period(period.id, as_of=AS_OF)
    assert result['territory_records'] == 4

    t1 = fact(period, primary_kpi, tree['town1'])
    assert t1.achieved_value == Decimal('850.0000')
    assert t1.achievement_pct == Decimal('85.00')
    assert t1.gap_to_target == Decimal('150.0000')

    t2 = fact(period, primary_kpi, tree['town2'])
    assert t2.achieved_value == Decimal('500.0000')
    assert t2.achievement_pct == Decimal('25.00')

    area = fact(period, primary_kpi, tree['area'])
    assert area.achieved_value == Decimal('1350.0000')
    assert area.achievement_pct == Decimal('45.00')

    region = fact(period, primary_kpi, tree['region'])
    assert region.achieved_value == Decimal('1350.0000')
    assert region.achievement_pct == Decimal('33.75')


@pytest.mark.django_db
def test_channel_dimension_scopes_actuals(tree, period, primary_kpi, gt):
    geo_alloc(period, primary_kpi, tree['town1'], 1000, channel=gt)
    txn_on(tree['town1'], net_amount=Decimal('600'), channel_code='GT')
    txn_on(tree['town1'], net_amount=Decimal('400'), channel_code='MT')

    AchievementService.compute_period(period.id, as_of=AS_OF)
    row = fact(period, primary_kpi, tree['town1'], channel=gt)
    assert row.achieved_value == Decimal('600.0000')
    assert row.achievement_pct == Decimal('60.00')


@pytest.mark.django_db
def test_sku_group_dimension_scopes_actuals(tree, period, primary_kpi):
    a1 = SKU.objects.create(code='A1', name='Brand A 100g')
    SKU.objects.create(code='B1', name='Brand B 100g')
    grp = SKUGroup.objects.create(code='BRAND_A', name='Brand A')
    grp.skus.add(a1)
    geo_alloc(period, primary_kpi, tree['town1'], 1000, sku_group=grp)
    txn_on(tree['town1'], net_amount=Decimal('300'), sku_code='A1')
    txn_on(tree['town1'], net_amount=Decimal('999'), sku_code='B1')

    AchievementService.compute_period(period.id, as_of=AS_OF)
    row = fact(period, primary_kpi, tree['town1'], sku_group=grp)
    assert row.achieved_value == Decimal('300.0000')
    assert row.achievement_pct == Decimal('30.00')


@pytest.mark.django_db
def test_non_foldable_kpi_aggregates_per_subtree(tree, period):
    """Ratio KPIs can't fold from per-node values — the area's ratio is recomputed over
    its whole subtree, not averaged from the towns."""
    kpi = KPIDefinition.objects.create(
        code='ATV', name='Avg transaction value', kpi_type=KPIDefinition.RATIO,
        applicable_entity_types=['ASE', 'ASM', 'NSM'], effective_from=date.today(),
        ratio_config={'numerator': {'measure_field': 'net_amount', 'aggregation': 'sum'},
                      'denominator': {'aggregation': 'count'}},
    )
    geo_alloc(period, kpi, tree['area'], 100)
    txn_on(tree['town1'], net_amount=Decimal('100'))
    txn_on(tree['town2'], net_amount=Decimal('200'))

    AchievementService.compute_period(period.id, as_of=AS_OF)
    row = fact(period, kpi, tree['area'])
    assert row.achieved_value == Decimal('150.0000')  # (100+200) / 2 bills


@pytest.mark.django_db
def test_rerun_converges_and_mirrors_committed_dimensions(tree, period, primary_kpi):
    alloc = geo_alloc(period, primary_kpi, tree['town1'], 1000)
    geo_alloc(period, primary_kpi, tree['town2'], 2000)
    txn_on(tree['town1'], net_amount=Decimal('850'))

    AchievementService.compute_period(period.id, as_of=AS_OF)
    AchievementService.compute_period(period.id, as_of=AS_OF)

    assert TerritoryAchievement.objects.filter(target_period=period).count() == 2
    assert fact(period, primary_kpi, tree['town1']).achieved_value == Decimal('850.0000')

    # A withdrawn allocation dimension disappears from the fact table on the next run.
    alloc.is_active = False
    alloc.save(update_fields=['is_active'])
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert not TerritoryAchievement.objects.filter(node=tree['town1']).exists()
    assert TerritoryAchievement.objects.filter(target_period=period).count() == 1


@pytest.mark.django_db
def test_one_bad_kpi_does_not_abort_the_run(tree, period, primary_kpi, monkeypatch):
    KPIDefinition.objects.create(
        code='BROKEN', name='Broken', kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    from apps.achievements.calculator import AchievementCalculator
    orig = AchievementCalculator.compute_for_kpi

    def boom(self, kpi, entities):
        if kpi.code == 'BROKEN':
            raise RuntimeError('kaput')
        return orig(self, kpi, entities)

    monkeypatch.setattr(AchievementCalculator, 'compute_for_kpi', boom)

    mk_txn(tree['ase1'].id, net_amount=Decimal('100'))
    mk_alloc(period, primary_kpi, tree['ase1'], 1000)
    result = AchievementService.compute_period(period.id, as_of=AS_OF)

    assert result['errors'] == ['BROKEN: kaput']
    assert Achievement.objects.filter(kpi=primary_kpi, entity=tree['ase1']).exists()


@pytest.mark.django_db
def test_fanout_job_tracks_per_kpi_progress(tree, period, primary_kpi):
    from apps.achievements.tasks import compute_daily_achievements
    from apps.jobs.models import BulkJob
    from apps.jobs.services import JobService

    mk_txn(tree['ase1'].id, net_amount=Decimal('100'))
    mk_alloc(period, primary_kpi, tree['ase1'], 1000)

    job = JobService.create(BulkJob.JobType.ACHIEVEMENT_COMPUTE, None)
    compute_daily_achievements.apply(args=(job.id, period.id, None))
    job.refresh_from_db()

    assert job.status == BulkJob.Status.COMPLETED
    assert job.total_rows == 1  # one KPI unit
    assert job.processed_rows == 1
    assert job.result['records_processed'] >= 1
    assert job.result['territory_records'] == 1
