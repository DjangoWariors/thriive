"""AchievementService.compute_period — persistence, snapshots, idempotent upsert."""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement, AchievementSnapshot
from apps.achievements.services import AchievementService
from apps.audit.models import ComputationLog

from .conftest import AS_OF, mk_alloc, mk_txn


@pytest.mark.django_db
def test_compute_period_persists(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('85000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    result = AchievementService.compute_period(period.id, as_of=AS_OF)
    assert result['records_processed'] >= 1

    ach = Achievement.objects.get(kpi=primary_kpi, entity=tree['ase1'])
    assert ach.achieved_value == Decimal('85000.0000')
    assert ach.achievement_pct == Decimal('85.00')
    assert ach.is_provisional is True  # period is PUBLISHED, not CLOSED

    snap = AchievementSnapshot.objects.get(achievement=ach, snapshot_date=AS_OF)
    assert snap.achievement_pct == Decimal('85.00')

    log = ComputationLog.objects.get(pk=result['computation_id'])
    assert log.computation_type == 'achievement'
    assert log.result_snapshot['records_processed'] == result['records_processed']


@pytest.mark.django_db
def test_recompute_upserts_no_duplicates(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('50000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    AchievementService.compute_period(period.id, as_of=AS_OF)
    AchievementService.compute_period(period.id, as_of=AS_OF)  # same day → update in place

    assert Achievement.objects.filter(kpi=primary_kpi, entity=tree['ase1']).count() == 1
    assert AchievementSnapshot.objects.filter(
        achievement__entity=tree['ase1'], snapshot_date=AS_OF,
    ).count() == 1


@pytest.mark.django_db
def test_two_snapshots_for_two_days(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('40000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    AchievementService.compute_period(period.id, as_of=date(2026, 6, 10))
    mk_txn(tree['ase1'].id, net_amount=Decimal('10000'))
    AchievementService.compute_period(period.id, as_of=date(2026, 6, 11))

    ach = Achievement.objects.get(kpi=primary_kpi, entity=tree['ase1'])
    assert ach.achieved_value == Decimal('50000.0000')  # latest
    assert ach.snapshots.count() == 2


@pytest.mark.django_db
def test_eligible_types_resolve_through_geography_targets(tree, period, primary_kpi):
    """A geography-anchored target must make its owner's type eligible even when the type is
    NOT incentive-eligible — guards the regression where reading entity-anchored targets
    returned an empty type set (silent zero achievements)."""
    from apps.assignments.services import AssignmentService
    from apps.hierarchy.models import GeographyNode, Node, NodeType

    dist_type = NodeType.objects.create(
        name='Distributor', code='DIST', level_order=4, incentive_eligible=False,
        effective_from=date(2025, 1, 1),
    )
    dist = Node.objects.create(entity_type=dist_type, name='D1', code='D1', effective_from=date(2025, 1, 1))
    node = GeographyNode.objects.create(
        geography_type=tree['town1'].geography_type, name='Beat', code='BEAT', level='town',
        parent=tree['area'],
    )
    AssignmentService.create(assignee_id=dist.id, scope_id=node.id, effective_from=date(2025, 1, 1))
    mk_alloc(period, primary_kpi, dist, 100000)  # target on BEAT, owned by the distributor

    codes = AchievementService._eligible_type_codes(period)
    assert 'DIST' in codes


@pytest.mark.django_db
def test_channel_mix_ignores_manager_rollup_rows(tree, period, primary_kpi):
    """A manager's achievement is already its subtree rollup — counting its channel-bearing
    row alongside the leaves would double-count every level of the hierarchy."""
    from apps.achievements.services import DashboardService
    from apps.hierarchy.models import Channel

    mt = Channel.objects.create(name='Modern Trade', code='MT')
    tree['ase2'].channel = mt
    tree['ase2'].save()
    tree['asm'].channel = tree['ase1'].channel  # GT — a channel-bearing manager row
    tree['asm'].save()

    mk_txn(tree['ase1'].id, net_amount=Decimal('85000'))
    mk_txn(tree['ase2'].id, net_amount=Decimal('40000'), channel_code='MT')
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    mk_alloc(period, primary_kpi, tree['ase2'], 100000)
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert Achievement.objects.filter(entity=tree['asm'], channel__isnull=False).exists()

    mix = {r['channel']: r['pct'] for r in DashboardService._channel_mix(period, tree['nsm'])}
    # Leaf rows only: 85000 GT + 40000 MT. With the ASM rollup row counted, GT would be 84%.
    assert mix == {'GT': '68.00', 'MT': '32.00'}


@pytest.mark.django_db
def test_active_entities_excludes_self(tree, period, primary_kpi):
    from apps.accounts.models import User
    from apps.achievements.services import DashboardService

    mk_txn(tree['ase1'].id, net_amount=Decimal('1000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 5000)
    AchievementService.compute_period(period.id, as_of=AS_OF)

    u = User.objects.create_user(email='asm-self@x.com', password='pass', entity=tree['asm'])
    data = DashboardService.build(u, period)
    assert data['summary']['active_entities'] == 2  # ASE1 + ASE2, not the ASM itself


@pytest.mark.django_db
def test_untargeted_rows_never_inflate_scores(tree, period, primary_kpi):
    """A row with achieved value but no target (untargeted tracking KPI) must not score:
    it would add to the numerator against nothing in the denominator — guards the
    '99.87% overall from a targetless KPI' regression."""
    from datetime import date

    from apps.accounts.models import User
    from apps.achievements.services import DashboardService
    from apps.kpi_engine.models import KPIDefinition

    tracking = KPIDefinition.objects.create(
        code='TRACKING', name='Tracking Only', kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum',
                        'net_logic': 'sales_minus_returns'},
    )
    mk_txn(tree['ase1'].id, net_amount=Decimal('85000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)  # no allocation for TRACKING
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert Achievement.objects.filter(
        entity=tree['ase1'], kpi=tracking, target_value=0,
    ).exists()  # the untargeted row exists…

    ase_user = User.objects.create_user(email='ase-cal@x.com', password='pass', entity=tree['ase1'])
    d = DashboardService.build(ase_user, period)
    # …but overall stays 85000/100000, not 170000/100000.
    assert d['summary']['overall_achievement_pct'] == '85.00'

    asm_user = User.objects.create_user(email='asm-cal@x.com', password='pass', entity=tree['asm'])
    d = DashboardService.build(asm_user, period)
    ase1_row = next(r for r in d['child_ranking'] if r['entity_code'] == 'ASE1')
    assert ase1_row['achievement_pct'] == '85.00'


@pytest.mark.django_db
def test_summary_falls_back_to_children_when_home_has_no_rows(tree, period, primary_kpi):
    """An unplaced admin lands on a root with no own facts — the tiles must reflect the
    direct children (disjoint rollups = network total), not read all-zero."""
    from apps.accounts.models import User
    from apps.achievements.services import DashboardService

    mk_txn(tree['ase1'].id, net_amount=Decimal('85000'))
    mk_txn(tree['ase2'].id, net_amount=Decimal('40000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    mk_alloc(period, primary_kpi, tree['ase2'], 100000)
    AchievementService.compute_period(period.id, as_of=AS_OF)

    Achievement.objects.filter(entity=tree['nsm']).delete()  # simulate a rowless root
    admin = User.objects.create_superuser(email='hq@x.com', password='pass')
    d = DashboardService.build(admin, period)

    assert d['summary']['overall_achievement_pct'] == '62.50'  # 125000 / 200000 via ASM
    assert d['summary']['primary_kpi_name'] == 'Primary Sales'
    assert d['summary']['primary_target'] == '200000.0000'
    assert d['kpi_cards'] == []  # cards stay real — only the tiles fall back


@pytest.mark.django_db
def test_skips_zero_zero_rows(tree, period, primary_kpi):
    # No transactions, no allocation for ase2 → no Achievement row.
    mk_txn(tree['ase1'].id, net_amount=Decimal('1000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 5000)
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert not Achievement.objects.filter(entity=tree['ase2'], kpi=primary_kpi).exists()
