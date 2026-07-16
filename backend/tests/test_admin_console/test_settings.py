"""SystemSetting service + API: typed reads, audit on change, sensitive masking,
feature flags, and TDS-config-drives-output (the configurable-platform promise)."""
from decimal import Decimal

import pytest

from apps.admin_console.models import FeatureFlag, SystemSetting
from apps.admin_console.services import FeatureService, SystemSettingService
from apps.audit.models import AuditLog

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db
BASE = '/api/v1/admin/'


class TestSettingService:
    def test_get_falls_back_to_default(self, db):
        # No row seeded — service returns the documented platform default.
        assert SystemSettingService.get('tds.194h.rate') == 2

    def test_set_updates_and_audits(self, db, settings_seeded):
        admin = make_user('a@x.com', perms={'system_admin': 'full'})
        SystemSettingService.set('tds.194h.rate', 5, admin)
        assert SystemSettingService.get('tds.194h.rate') == 5
        assert AuditLog.objects.filter(
            entity_type='admin_console.SystemSetting', action='update').exists()

    def test_tds_config_typed(self, db, settings_seeded):
        cfg = SystemSettingService.get_tds_config()
        assert cfg['r_rate'] == Decimal('10')
        assert cfg['no_pan_rate'] == Decimal('20')

    def test_change_is_visible_without_code_change(self, db, settings_seeded):
        admin = make_user('a@x.com', perms={'system_admin': 'full'})
        SystemSettingService.set('tds.194r.rate', 15, admin)
        assert SystemSettingService.get_tds_config()['r_rate'] == Decimal('15')


class TestFeatureFlags:
    def test_global_flag(self, db):
        FeatureFlag.objects.create(code='x', is_enabled=True)
        assert FeatureService.is_enabled('x') is True

    def test_disabled_flag(self, db):
        FeatureFlag.objects.create(code='x', is_enabled=False)
        assert FeatureService.is_enabled('x') is False

    def test_missing_flag_is_off(self, db):
        assert FeatureService.is_enabled('nope') is False


class TestSettingsApi:
    def test_requires_system_admin(self, settings_seeded):
        nobody = make_user('n@x.com', perms={'dashboard': 'own_only'})
        assert client_for(nobody).get(f'{BASE}settings/').status_code == 403

    def test_list_and_filter(self, settings_seeded, admin):
        resp = client_for(admin).get(f'{BASE}settings/', {'category': 'tds'})
        assert resp.status_code == 200
        assert all(r['category'] == 'tds' for r in resp.data)
        assert len(resp.data) == 5

    def test_update_value_endpoint(self, settings_seeded, admin):
        setting = SystemSetting.objects.get(key='tds.194h.rate')
        resp = client_for(admin).post(
            f'{BASE}settings/{setting.pk}/update_value/', {'value': 3}, format='json')
        assert resp.status_code == 200
        assert SystemSettingService.get('tds.194h.rate') == 3

    def test_sensitive_value_masked_for_non_superuser(self, db, admin):
        SystemSetting.objects.create(key='secret.api', category='security',
                                     value='shhh', value_type='string', is_sensitive=True)
        resp = client_for(admin).get(f'{BASE}settings/')
        secret = next(r for r in resp.data if r['key'] == 'secret.api')
        assert secret['value'] == '••••••'


class TestMonitoring:
    def test_system_health(self, admin):
        resp = client_for(admin).get(f'{BASE}system/health/')
        assert resp.status_code == 200
        assert resp.data['database'] == 'ok'
        assert 'queued_jobs' in resp.data

    def test_schedules_health(self, admin):
        resp = client_for(admin).get(f'{BASE}schedules/')
        assert resp.status_code == 200
        assert isinstance(resp.data, list)
