"""Achievements over external-metric KPIs — fixed-target scores and territory counts."""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Achievement
from apps.achievements.services import AchievementService
from apps.kpi_engine.models import ExternalMetric, ExternalMetricValue, KPIDefinition

from .conftest import AS_OF, mk_alloc


@pytest.fixture
def rcpa(db):
    return ExternalMetric.objects.create(
        code='RCPA_PCT', name='RCPA %', granularity=ExternalMetric.ENTITY,
        period_grain=ExternalMetric.MONTHLY, default_aggregation=ExternalMetric.LATEST, unit='%',
    )


@pytest.fixture
def rcpa_kpi(db, rcpa):
    """Score KPI: fixed benchmark 100 so achievement_pct reads as the raw score."""
    return KPIDefinition.objects.create(
        code='RCPA', name='RCPA Coverage', kpi_type=KPIDefinition.EXTERNAL,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        external_config={'metric_code': 'RCPA_PCT', 'aggregation': 'latest',
                         'target_source': 'fixed', 'fixed_target': 100},
    )


@pytest.mark.django_db
def test_fixed_target_score_achievement_pct_is_raw_score(tree, period, rcpa, rcpa_kpi):
    ExternalMetricValue.objects.create(
        metric=rcpa, entity=tree['ase1'], measured_on=date(2026, 6, 1), value=Decimal('85'),
    )
    AchievementService.compute_period(period.id, as_of=AS_OF)

    ach = Achievement.objects.get(kpi=rcpa_kpi, entity=tree['ase1'])
    assert ach.target_value == Decimal('100.0000')
    assert ach.achieved_value == Decimal('85.0000')
    assert ach.achievement_pct == Decimal('85.00')


@pytest.mark.django_db
def test_territory_metric_uses_geography_allocation(tree, period):
    tlsd = ExternalMetric.objects.create(
        code='TLSD', name='TLSD', granularity=ExternalMetric.GEOGRAPHY_NODE,
        period_grain=ExternalMetric.DAILY, default_aggregation=ExternalMetric.SUM,
    )
    kpi = KPIDefinition.objects.create(
        code='TLSD', name='TLSD', kpi_type=KPIDefinition.EXTERNAL,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        external_config={'metric_code': 'TLSD', 'target_source': 'allocation'},
    )
    ExternalMetricValue.objects.create(
        metric=tlsd, node_id=tree['town1'].id, measured_on=date(2026, 6, 3), value=Decimal('12'),
    )
    ExternalMetricValue.objects.create(
        metric=tlsd, node_id=tree['town1'].id, measured_on=date(2026, 6, 4), value=Decimal('8'),
    )
    mk_alloc(period, kpi, tree['ase1'], 25)

    AchievementService.compute_period(period.id, as_of=AS_OF)

    ach = Achievement.objects.get(kpi=kpi, entity=tree['ase1'])
    assert ach.achieved_value == Decimal('20.0000')
    assert ach.target_value == Decimal('25.0000')
    assert ach.achievement_pct == Decimal('80.00')


@pytest.mark.django_db
def test_drilldown_returns_metric_values_for_external_kpi(tree, period, rcpa, rcpa_kpi):
    from apps.accounts.models import User

    ExternalMetricValue.objects.create(
        metric=rcpa, entity=tree['ase1'], measured_on=date(2026, 6, 1), value=Decimal('85'),
    )
    AchievementService.compute_period(period.id, as_of=AS_OF)
    ach = Achievement.objects.get(kpi=rcpa_kpi, entity=tree['ase1'])

    admin = User.objects.create_superuser(email='drill_admin@test.com', password='x')
    _, rows, row_kind = AchievementService.drilldown(ach.id, admin)
    assert row_kind == 'metric_values'
    assert list(rows.values_list('value', flat=True)) == [Decimal('85.0000')]
