"""Alert rule evaluation + service sync (open/resolve lifecycle)."""
from datetime import date
from decimal import Decimal

import pytest

from apps.achievements.models import Alert, AlertRule
from apps.achievements.services import AchievementService

from .conftest import AS_OF, mk_alloc, mk_txn


def _rule(**kw):
    kw.setdefault('effective_from', date.today())
    kw.setdefault('code', 'AT_RISK')
    kw.setdefault('name', 'Target at risk')
    return AlertRule.objects.create(**kw)


@pytest.mark.django_db
def test_projected_pct_below_threshold_opens_alert(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('20000'))  # 10 wd elapsed → projected 40000
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)    # projected_pct = 40 < 90
    _rule(metric=AlertRule.PROJECTED_PCT, comparator='lt', threshold=Decimal('90'),
          severity=AlertRule.CRITICAL, scope_entity_types=['ASE'])

    AchievementService.compute_period(period.id, as_of=AS_OF)
    alert = Alert.objects.get(entity=tree['ase1'])
    assert alert.severity == AlertRule.CRITICAL
    assert alert.status == Alert.OPEN


@pytest.mark.django_db
def test_alert_resolves_on_recovery(tree, period, primary_kpi):
    rule = _rule(metric=AlertRule.PROJECTED_PCT, comparator='lt', threshold=Decimal('90'),
                 scope_entity_types=['ASE'])
    txn = mk_txn(tree['ase1'].id, net_amount=Decimal('20000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert Alert.objects.get(entity=tree['ase1']).status == Alert.OPEN

    # Recover: bump achieved so projected ≥ target
    txn.net_amount = Decimal('60000')  # projected 120000 → 120% ≥ 90
    txn.save()
    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert Alert.objects.get(entity=tree['ase1']).status == Alert.RESOLVED


@pytest.mark.django_db
def test_scope_excludes_other_entity_types(tree, period, primary_kpi):
    # Rule scoped to a type nobody has → no alerts even though projection is low.
    mk_txn(tree['ase1'].id, net_amount=Decimal('1000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    _rule(metric=AlertRule.PROJECTED_PCT, comparator='lt', threshold=Decimal('90'),
          scope_entity_types=['DISTRIBUTOR'])

    AchievementService.compute_period(period.id, as_of=AS_OF)
    assert Alert.objects.count() == 0


@pytest.mark.django_db
def test_message_template_interpolates_kpi(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('20000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    _rule(metric=AlertRule.PROJECTED_PCT, comparator='lt', threshold=Decimal('90'),
          scope_entity_types=['ASE'], message_template='{entity} {kpi} at {value}')

    AchievementService.compute_period(period.id, as_of=AS_OF)
    alert = Alert.objects.get(entity=tree['ase1'])
    assert 'PRIMARY' in alert.message
    assert alert.message.startswith('Deepa')


@pytest.mark.django_db
def test_no_sale_days_alert(tree, period, primary_kpi):
    # ase1 last billed Jun 5; as_of Jun 30 → 25 days no sale ≥ 7.
    mk_txn(tree['ase1'].id, transaction_date=date(2026, 6, 5), net_amount=Decimal('1000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 5000)
    _rule(code='NO_SALE', name='No sale', metric=AlertRule.NO_SALE_DAYS, comparator='gte',
          threshold=Decimal('7'), scope_entity_types=['ASE'])

    AchievementService.compute_period(period.id, as_of=date(2026, 6, 30))
    assert Alert.objects.filter(entity=tree['ase1'], rule__code='NO_SALE').exists()
