"""AchievementCalculator correctness — exact Decimal assertions."""
from decimal import Decimal

import pytest

from apps.achievements.calculator import AchievementCalculator

from .conftest import AS_OF, mk_alloc, mk_txn


@pytest.mark.django_db
def test_achievement_pct_and_breakdown(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('60000'))
    mk_txn(tree['ase1'].id, net_amount=Decimal('30000'))
    mk_txn(tree['ase1'].id, transaction_type='return', net_amount=Decimal('5000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    [r] = [x for x in AchievementCalculator(period, as_of=AS_OF).compute_for_kpi(primary_kpi, [tree['ase1']])]
    assert r['achieved_value'] == Decimal('85000.0000')   # 60000 + 30000 - 5000
    assert r['gross_value'] == Decimal('90000.0000')
    assert r['returns_value'] == Decimal('5000.0000')
    assert r['target_value'] == Decimal('100000.0000')
    assert r['achievement_pct'] == Decimal('85.00')
    assert r['gap_to_target'] == Decimal('15000.0000')


@pytest.mark.django_db
def test_zero_target_is_zero_pct(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('50000'))
    # no allocation → target 0
    [r] = AchievementCalculator(period, as_of=AS_OF).compute_for_kpi(primary_kpi, [tree['ase1']])
    assert r['target_value'] == Decimal('0.0000')
    assert r['achievement_pct'] == Decimal('0.00')


@pytest.mark.django_db
def test_run_rate_projection(tree, period, primary_kpi):
    # working_days=20, as_of Jun 11 → 10 elapsed; achieved 50000 → projected 100000.
    mk_txn(tree['ase1'].id, net_amount=Decimal('50000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    [r] = AchievementCalculator(period, as_of=AS_OF).compute_for_kpi(primary_kpi, [tree['ase1']])
    assert r['working_days_elapsed'] == 10
    assert r['working_days_total'] == 20
    assert r['daily_run_rate'] == Decimal('5000.0000')
    assert r['projected_value'] == Decimal('100000.0000')
    assert r['projected_pct'] == Decimal('100.00')
    assert r['required_run_rate'] == Decimal('5000.0000')  # (100000-50000)/10 remaining


@pytest.mark.django_db
def test_growth_vs_last_year(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('50000'))  # current June 2026
    mk_txn(tree['ase1'].id, transaction_date=__import__('datetime').date(2025, 6, 5),
           net_amount=Decimal('40000'))  # LY June 2025
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)

    [r] = AchievementCalculator(period, as_of=AS_OF).compute_for_kpi(primary_kpi, [tree['ase1']])
    assert r['ly_value'] == Decimal('40000.0000')
    assert r['growth_pct'] == Decimal('25.00')  # (50000-40000)/40000


@pytest.mark.django_db
def test_manager_rolls_up_subtree(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('30000'))
    mk_txn(tree['ase2'].id, net_amount=Decimal('20000'))
    # ASM has incentive_eligible type; its subtree aggregate = 50000
    [r] = AchievementCalculator(period, as_of=AS_OF).compute_for_kpi(primary_kpi, [tree['asm']])
    assert r['achieved_value'] == Decimal('50000.0000')
