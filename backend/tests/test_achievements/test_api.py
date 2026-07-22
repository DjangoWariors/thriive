"""Achievement API — RBAC subtree scoping, role-adaptive dashboard, drilldown, compute gating."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.achievements.services import AchievementService

from .conftest import AS_OF, mk_alloc, mk_txn

BASE = '/api/v1/achievements/'


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


def _role(perms: dict):
    return Role.objects.create(code='r_' + '_'.join(perms), name='r', permissions=perms)


def _user(email, *, entity=None, perms=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        UserRole.objects.create(user=u, role=_role(perms), effective_from=date.today())
    return u


@pytest.fixture
def computed(tree, period, primary_kpi):
    mk_txn(tree['ase1'].id, net_amount=Decimal('85000'))
    mk_txn(tree['ase2'].id, net_amount=Decimal('40000'))
    mk_alloc(period, primary_kpi, tree['ase1'], 100000)
    mk_alloc(period, primary_kpi, tree['ase2'], 100000)
    AchievementService.compute_period(period.id, as_of=AS_OF)
    return tree


@pytest.mark.django_db
class TestScoping:
    def test_leaf_sees_only_own(self, computed, period):
        u = _user('ase1@x.com', entity=computed['ase1'], perms={'achievement_view': 'view_all'})
        resp = _client(u).get(BASE, {'period': period.id})
        assert resp.status_code == 200
        names = {r['entity_code'] for r in resp.data['results']}
        assert names == {'ASE1'}

    def test_manager_sees_subtree(self, computed, period):
        u = _user('asm@x.com', entity=computed['asm'], perms={'achievement_view': 'team'})
        resp = _client(u).get(BASE, {'period': period.id})
        codes = {r['entity_code'] for r in resp.data['results']}
        assert codes == {'ASM', 'ASE1', 'ASE2'}

    def test_superuser_sees_all(self, computed, period):
        su = User.objects.create_superuser(email='su@x.com', password='pass')
        resp = _client(su).get(BASE, {'period': period.id})
        codes = {r['entity_code'] for r in resp.data['results']}
        assert {'NSM', 'ASM', 'ASE1', 'ASE2'} == codes


@pytest.mark.django_db
class TestDashboard:
    def test_manager_gets_child_ranking(self, computed, period):
        u = _user('m@x.com', entity=computed['asm'], perms={'achievement_view': 'team'})
        resp = _client(u).get(f'{BASE}dashboard/', {'period': period.id})
        assert resp.status_code == 200, resp.data
        assert resp.data['child_ranking'] is not None
        ranks = {r['entity_code']: r['rank'] for r in resp.data['child_ranking']}
        assert ranks['ASE1'] == 1 and ranks['ASE2'] == 2  # 85% > 40%
        # No payout run computed yet → incentives module degrades gracefully
        assert resp.data['modules'] == {'incentives': False, 'exceptions': True}

    def test_leaf_has_no_child_ranking(self, computed, period):
        u = _user('l@x.com', entity=computed['ase1'], perms={'achievement_view': 'own_only'})
        resp = _client(u).get(f'{BASE}dashboard/', {'period': period.id})
        assert resp.status_code == 200
        assert resp.data['child_ranking'] is None
        assert any(c['kpi_code'] == 'PRIMARY' for c in resp.data['kpi_cards'])

    def test_dashboard_requires_period(self, computed):
        u = _user('np@x.com', entity=computed['ase1'], perms={'achievement_view': 'own_only'})
        resp = _client(u).get(f'{BASE}dashboard/')
        assert resp.status_code == 400

    def test_dashboard_bad_entity_is_404(self, computed, period):
        su = User.objects.create_superuser(email='su404@x.com', password='pass')
        resp = _client(su).get(f'{BASE}dashboard/', {'period': period.id, 'entity': 999999})
        assert resp.status_code == 404
        resp = _client(su).get(f'{BASE}dashboard/', {'period': period.id, 'entity': 'abc'})
        assert resp.status_code == 404


@pytest.mark.django_db
class TestSnapshots:
    def test_snapshots_scoped_to_subtree(self, computed, period, primary_kpi):
        # A leaf must not read a sibling's trend by passing its entity id.
        u = _user('snap1@x.com', entity=computed['ase1'], perms={'achievement_view': 'own_only'})
        resp = _client(u).get(f'{BASE}snapshots/', {
            'entity': computed['ase2'].id, 'kpi': primary_kpi.id, 'period': period.id,
        })
        assert resp.status_code == 403

        # Own entity → fine; manager → any child in the subtree.
        resp = _client(u).get(f'{BASE}snapshots/', {
            'entity': computed['ase1'].id, 'kpi': primary_kpi.id, 'period': period.id,
        })
        assert resp.status_code == 200 and len(resp.data) == 1

    def test_snapshots_manager_reaches_child(self, computed, period, primary_kpi):
        m = _user('snap2@x.com', entity=computed['asm'], perms={'achievement_view': 'team'})
        resp = _client(m).get(f'{BASE}snapshots/', {
            'entity': computed['ase1'].id, 'kpi': primary_kpi.id, 'period': period.id,
        })
        assert resp.status_code == 200 and len(resp.data) == 1

    def test_snapshots_requires_params(self, computed, period):
        u = _user('snap3@x.com', entity=computed['ase1'], perms={'achievement_view': 'own_only'})
        resp = _client(u).get(f'{BASE}snapshots/', {'entity': computed['ase1'].id, 'period': period.id})
        assert resp.status_code == 400


@pytest.mark.django_db
class TestDrilldownAndCompute:
    def test_drilldown_returns_breakdown_and_txns(self, computed, period):
        from apps.achievements.models import Achievement
        ach = Achievement.objects.get(entity=computed['ase1'], kpi__code='PRIMARY')
        u = _user('d@x.com', entity=computed['ase1'], perms={'achievement_view': 'own_only'})
        resp = _client(u).get(f'{BASE}{ach.id}/drilldown/')
        assert resp.status_code == 200
        assert resp.data['breakdown']['net_value'] == '85000.0000'
        assert resp.data['breakdown']['row_kind'] == 'transactions'
        assert resp.data['count'] >= 1

    def test_drilldown_outlet_and_sku_filters(self, tree, period, primary_kpi):
        from apps.achievements.models import Achievement
        mk_txn(tree['ase1'].id, net_amount=Decimal('50000'), outlet_code='OUT-A', sku_code='SKU-1')
        mk_txn(tree['ase1'].id, net_amount=Decimal('30000'), outlet_code='OUT-B', sku_code='SKU-2')
        mk_alloc(period, primary_kpi, tree['ase1'], 100000)
        AchievementService.compute_period(period.id, as_of=AS_OF)
        ach = Achievement.objects.get(entity=tree['ase1'], kpi__code='PRIMARY')
        u = _user('df@x.com', entity=tree['ase1'], perms={'achievement_view': 'own_only'})

        assert _client(u).get(f'{BASE}{ach.id}/drilldown/').data['count'] == 2
        # Outlet substring narrows to one row.
        r = _client(u).get(f'{BASE}{ach.id}/drilldown/', {'outlet': 'OUT-A'})
        assert r.data['count'] == 1
        assert r.data['results'][0]['sku_code'] == 'SKU-1'
        # SKU substring narrows independently.
        r = _client(u).get(f'{BASE}{ach.id}/drilldown/', {'sku': 'SKU-2'})
        assert r.data['count'] == 1
        assert r.data['results'][0]['outlet_code'] == 'OUT-B'
        # Both together, no match → empty (breakdown totals unchanged).
        r = _client(u).get(f'{BASE}{ach.id}/drilldown/', {'outlet': 'OUT-A', 'sku': 'SKU-2'})
        assert r.data['count'] == 0
        assert r.data['breakdown']['net_value'] == '80000.0000'

    def test_compute_denied_without_perm(self, tree, period):
        u = _user('v@x.com', entity=tree['asm'], perms={'achievement_view': 'team'})
        resp = _client(u).post(f'{BASE}compute/', {'period_id': period.id}, format='json')
        assert resp.status_code == 403

    def test_compute_allowed_for_superuser(self, tree, period, primary_kpi):
        su = User.objects.create_superuser(email='su2@x.com', password='pass')
        resp = _client(su).post(f'{BASE}compute/', {'period_id': period.id}, format='json')
        assert resp.status_code == 202

    def test_compute_allowed_with_grant(self, tree, period, primary_kpi):
        u = _user('g@x.com', entity=tree['asm'],
                  perms={'achievement_view': 'team', 'achievement_compute': 'full'})
        resp = _client(u).post(f'{BASE}compute/', {'period_id': period.id}, format='json')
        assert resp.status_code == 202


@pytest.mark.django_db
class TestAlertAcknowledgeAll:
    def _alerts(self, tree, period):
        from apps.achievements.models import Alert, AlertRule
        rule = AlertRule.objects.create(
            code='AT_RISK', name='Target at risk', effective_from=date.today(),
            metric=AlertRule.PROJECTED_PCT, comparator='lt', threshold=Decimal('90'),
        )
        return {
            code: Alert.objects.create(rule=rule, entity=tree[code], target_period=period)
            for code in ('ase1', 'ase2', 'nsm')
        }

    def test_acknowledges_only_open_alerts_in_scope(self, tree, period):
        from apps.achievements.models import Alert
        alerts = self._alerts(tree, period)
        u = _user('asm@x.com', entity=tree['asm'], perms={'achievement_view': 'team'})

        resp = _client(u).patch(f'{BASE}alerts/acknowledge-all/?period={period.id}')
        assert resp.status_code == 200
        assert resp.data['acknowledged'] == 2  # ase1 + ase2; nsm is outside the subtree

        for code, expected in (('ase1', Alert.ACKNOWLEDGED), ('ase2', Alert.ACKNOWLEDGED),
                               ('nsm', Alert.OPEN)):
            alerts[code].refresh_from_db()
            assert alerts[code].status == expected

    def test_skips_already_acknowledged_and_resolved(self, tree, period):
        from apps.achievements.models import Alert
        alerts = self._alerts(tree, period)
        alerts['ase1'].status = Alert.RESOLVED
        alerts['ase1'].save(update_fields=['status'])
        su = User.objects.create_superuser(email='su2@x.com', password='pass')

        resp = _client(su).patch(f'{BASE}alerts/acknowledge-all/')
        assert resp.status_code == 200
        assert resp.data['acknowledged'] == 2  # ase2 + nsm; resolved ase1 untouched
        alerts['ase1'].refresh_from_db()
        assert alerts['ase1'].status == Alert.RESOLVED
