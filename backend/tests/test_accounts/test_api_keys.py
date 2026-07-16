"""API-key issue / revoke / authenticate."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import APIKey, User
from apps.accounts.services import ApiKeyService


@pytest.fixture
def service_user(db):
    return User.objects.create_user(email='dms-bot@test.com')


@pytest.fixture
def admin_client(db):
    admin = User.objects.create_superuser(email='keys_admin@test.com', password='x')
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def _client_with_key(plaintext):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=plaintext)
    return client


# ── service ──────────────────────────────────────────────────────────────────
def test_issue_returns_plaintext_once_and_stores_hash_only(service_user):
    key, plaintext = ApiKeyService.issue('DMS sync', service_user)
    prefix, _, secret = plaintext.partition('.')
    assert key.key_prefix == prefix
    assert secret and secret not in key.hashed_key
    assert len(key.hashed_key) == 64  # sha256 hex


# ── authentication ───────────────────────────────────────────────────────────
def test_valid_key_authenticates_as_service_user(service_user):
    _, plaintext = ApiKeyService.issue('DMS sync', service_user)
    resp = _client_with_key(plaintext).get('/api/v1/auth/me/')
    assert resp.status_code == 200
    assert resp.data['email'] == 'dms-bot@test.com'


def test_revoked_key_is_401(service_user):
    key, plaintext = ApiKeyService.issue('DMS sync', service_user)
    ApiKeyService.revoke(key)
    resp = _client_with_key(plaintext).get('/api/v1/auth/me/')
    assert resp.status_code == 401


def test_expired_key_is_401(service_user):
    _, plaintext = ApiKeyService.issue(
        'DMS sync', service_user, expires_at=timezone.now() - timedelta(minutes=1),
    )
    resp = _client_with_key(plaintext).get('/api/v1/auth/me/')
    assert resp.status_code == 401


def test_wrong_secret_is_401(service_user):
    key, _ = ApiKeyService.issue('DMS sync', service_user)
    resp = _client_with_key(f'{key.key_prefix}.not-the-secret').get('/api/v1/auth/me/')
    assert resp.status_code == 401


def test_inactive_service_user_is_401(service_user):
    _, plaintext = ApiKeyService.issue('DMS sync', service_user)
    service_user.is_active = False
    service_user.save(update_fields=['is_active'])
    resp = _client_with_key(plaintext).get('/api/v1/auth/me/')
    assert resp.status_code == 401


def test_last_used_at_is_stamped(service_user):
    key, plaintext = ApiKeyService.issue('DMS sync', service_user)
    assert key.last_used_at is None
    _client_with_key(plaintext).get('/api/v1/auth/me/')
    key.refresh_from_db()
    assert key.last_used_at is not None


# ── admin endpoints ──────────────────────────────────────────────────────────
def test_create_endpoint_returns_key_exactly_once(admin_client, service_user):
    resp = admin_client.post('/api/v1/auth/api-keys/', {'name': 'SFA push', 'user': service_user.id})
    assert resp.status_code == 201
    assert '.' in resp.data['key']
    # List never exposes the plaintext or hash.
    listing = admin_client.get('/api/v1/auth/api-keys/')
    row = listing.data['results'][0]
    assert 'key' not in row and 'hashed_key' not in row


def test_delete_endpoint_revokes(admin_client, service_user):
    resp = admin_client.post('/api/v1/auth/api-keys/', {'name': 'SFA push', 'user': service_user.id})
    key_id = resp.data['id']
    assert admin_client.delete(f'/api/v1/auth/api-keys/{key_id}/').status_code == 204
    assert APIKey.objects.get(pk=key_id).is_active is False


def test_api_keys_require_system_admin(db, service_user):
    plain = User.objects.create_user(email='plain@test.com', password='x')
    client = APIClient()
    client.force_authenticate(user=plain)
    assert client.get('/api/v1/auth/api-keys/').status_code == 403
