"""Sprint 12.1: the entity-type blueprint is cached and invalidated on writes.

Uses the LocMemCache configured for dev/test; the global _clear_throttle_cache
fixture (tests/conftest.py) clears the cache between tests.
"""
import datetime

import pytest
from django.core.cache import cache

from apps.hierarchy.config_services import ENTITY_TYPE_BLUEPRINT_CACHE_KEY, NodeTypeService


@pytest.mark.django_db
def test_blueprint_write_invalidates_cache():
    # Prime the cache as the blueprint endpoint would.
    cache.set(ENTITY_TYPE_BLUEPRINT_CACHE_KEY, [{'stale': True}], timeout=3600)
    assert cache.get(ENTITY_TYPE_BLUEPRINT_CACHE_KEY) is not None

    NodeTypeService.create({
        'name': 'Distributor', 'code': 'DIST', 'level_order': 1,
        'effective_from': datetime.date.today(),
    })

    # Creating an entity type must drop the stale blueprint.
    assert cache.get(ENTITY_TYPE_BLUEPRINT_CACHE_KEY) is None


@pytest.mark.django_db
def test_blueprint_endpoint_caches_payload(client=None):
    from rest_framework.test import APIClient

    from apps.accounts.models import User

    admin = User.objects.create_superuser(email='admin@example.com', password='x')
    api = APIClient()
    api.force_authenticate(admin)

    NodeTypeService.create({
        'name': 'Retailer', 'code': 'RET', 'level_order': 1,
        'effective_from': datetime.date.today(),
    })
    assert cache.get(ENTITY_TYPE_BLUEPRINT_CACHE_KEY) is None  # write cleared it

    resp = api.get('/api/v1/entity-types/blueprint/')
    assert resp.status_code == 200
    # The endpoint populated the cache for subsequent reads.
    assert cache.get(ENTITY_TYPE_BLUEPRINT_CACHE_KEY) is not None
    assert any(row['code'] == 'RET' for row in resp.data)
