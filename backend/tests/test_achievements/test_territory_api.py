"""Territory achievements endpoint — the plan-tracking grid (P4).

One geography level, lazy, and territory-RBAC-scoped: a placed user sees only nodes inside
the territories they own via assignments; an unscoped admin sees the whole level.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.achievements.services import AchievementService

from .conftest import AS_OF
from .test_territory import geo_alloc, txn_on

BASE = '/api/v1/achievements/territory/'


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


def _user(email, *, entity=None, perms=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        role = Role.objects.create(code=email, name=email, permissions=perms)
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
    return u


@pytest.fixture
def facts(tree, period, primary_kpi):
    """Committed territory targets at region/area/town levels, computed to TerritoryAchievement."""
    geo_alloc(period, primary_kpi, tree['region'], 4000)
    geo_alloc(period, primary_kpi, tree['area'], 3000)
    geo_alloc(period, primary_kpi, tree['town1'], 1000)
    geo_alloc(period, primary_kpi, tree['town2'], 2000)
    txn_on(tree['town1'], net_amount='850')
    txn_on(tree['town2'], net_amount='500')
    AchievementService.compute_period(period.id, as_of=AS_OF)
    return tree


@pytest.mark.django_db
class TestTerritoryEndpoint:
    def test_admin_sees_level_with_values(self, facts, period, primary_kpi):
        admin = User.objects.create_superuser(email='a@x.com', password='pass')
        resp = _client(admin).get(BASE, {
            'kpi': primary_kpi.id, 'period': period.id, 'parent': facts['area'].id,
        })
        assert resp.status_code == 200
        rows = {r['code']: r for r in resp.data['rows']}
        assert set(rows) == {'TOWN1', 'TOWN2'}
        assert rows['TOWN1']['target'] == '1000.0000'
        assert rows['TOWN1']['actual'] == '850.0000'
        assert rows['TOWN1']['achievement_pct'] == '85.00'

    def test_requires_kpi_and_period(self, facts):
        admin = User.objects.create_superuser(email='a2@x.com', password='pass')
        assert _client(admin).get(BASE).status_code == 400

    def test_territory_scoping_limits_rows(self, facts, period, primary_kpi):
        """A user placed at ase1 (owns TOWN1 only) sees just TOWN1 under the area."""
        scoped = _user('ase1@x.com', entity=facts['ase1'],
                       perms={'achievement_view': 'own_only'})
        resp = _client(scoped).get(BASE, {
            'kpi': primary_kpi.id, 'period': period.id, 'parent': facts['area'].id,
        })
        assert resp.status_code == 200
        assert {r['code'] for r in resp.data['rows']} == {'TOWN1'}

    def test_targets_show_before_any_compute(self, tree, period, primary_kpi):
        """A fresh publish has committed targets but no facts yet — the grid must show
        the target column immediately (actuals stay empty until a compute)."""
        geo_alloc(period, primary_kpi, tree['town1'], 1000)
        admin = User.objects.create_superuser(email='a3@x.com', password='pass')
        resp = _client(admin).get(BASE, {
            'kpi': primary_kpi.id, 'period': period.id, 'parent': tree['area'].id,
        })
        rows = {r['code']: r for r in resp.data['rows']}
        assert rows['TOWN1']['target'] == '1000.0000'
        assert rows['TOWN1']['actual'] is None
        assert rows['TOWN1']['achievement_pct'] is None

    def test_override_moves_target_without_recompute(self, facts, period, primary_kpi):
        """An approved override shows (and re-derives pct/gap) straight away — the grid
        reads the live committed axis, not the fact snapshot."""
        from apps.targets.models import TargetAllocation
        alloc = TargetAllocation.objects.get(
            target_period=period, kpi=primary_kpi, geography_node=facts['town1'])
        alloc.override_value = '850.0000'
        alloc.save(update_fields=['override_value'])
        admin = User.objects.create_superuser(email='a4@x.com', password='pass')
        resp = _client(admin).get(BASE, {
            'kpi': primary_kpi.id, 'period': period.id, 'parent': facts['area'].id,
        })
        rows = {r['code']: r for r in resp.data['rows']}
        assert rows['TOWN1']['target'] == '850.0000'
        assert rows['TOWN1']['achievement_pct'] == '100.00'  # 850 actual / 850 live target
        assert rows['TOWN1']['gap'] == '0.0000'
