"""
Tests for the permission catalog (single source of truth) and its endpoint.

These are the regression guard against the backend resource set and the admin-UI
permission matrix drifting apart.
"""
import pytest
from datetime import date
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.accounts.permission_catalog import (
    ALL_RESOURCES,
    LEVELS,
    PERMISSION_CATALOG,
)

CATALOG_URL = '/api/v1/auth/permission-catalog/'


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


class TestCatalogModule:

    def test_all_resources_derived_from_catalog(self):
        flat = [r['code'] for g in PERMISSION_CATALOG for r in g['resources']]
        assert ALL_RESOURCES == flat

    def test_resource_codes_unique(self):
        assert len(ALL_RESOURCES) == len(set(ALL_RESOURCES))

    def test_every_resource_level_is_valid(self):
        for group in PERMISSION_CATALOG:
            for res in group['resources']:
                assert res['levels'], f'{res["code"]} has no levels'
                for lvl in res['levels']:
                    assert lvl in LEVELS, f'{res["code"]} has unknown level {lvl}'

    def test_full_and_none_offered_everywhere(self):
        # Every resource must at least be grantable (full) or deniable (none).
        for group in PERMISSION_CATALOG:
            for res in group['resources']:
                assert 'full' in res['levels']
                assert 'none' in res['levels']


@pytest.mark.django_db
class TestSeededRolesMatchCatalog:

    def test_seeded_role_codes_all_in_catalog(self):
        """Every permission code in every seeded role must exist in the catalog —
        this fails the moment a role references a resource the UI cannot show."""
        call_command('seed_roles', verbosity=0)
        catalog_codes = set(ALL_RESOURCES)
        for role in Role.objects.all():
            for code in role.permissions:
                assert code in catalog_codes, \
                    f'role {role.code} references unknown resource {code}'

    def test_seeded_roles_cover_full_catalog(self):
        """seed_roles bases every role on ALL_RESOURCES, so each role's matrix
        should span the entire catalog (no missing resources)."""
        call_command('seed_roles', verbosity=0)
        catalog_codes = set(ALL_RESOURCES)
        admin = Role.objects.get(code='admin')
        assert set(admin.permissions) == catalog_codes


@pytest.mark.django_db
class TestCatalogEndpoint:

    def test_requires_authentication(self):
        assert APIClient().get(CATALOG_URL).status_code == 401

    def test_returns_catalog_for_authenticated_user(self):
        user = User.objects.create_user(email='plain@example.com', password='pass')
        resp = _auth_client(user).get(CATALOG_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert 'groups' in body and 'levels' in body and 'level_labels' in body
        codes = [r['code'] for g in body['groups'] for r in g['resources']]
        assert set(codes) == set(ALL_RESOURCES)
        assert body['levels'] == LEVELS
