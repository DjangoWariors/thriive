import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import LoginAttempt, User
from apps.hierarchy.models import Node

LOGIN_URL = '/api/v1/auth/login/'


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email='rep@example.com',
        password='correct_pass',
        first_name='Deepa',
        last_name='Sharma',
    )


def _post(client, identifier, password):
    return client.post(LOGIN_URL, {'identifier': identifier, 'password': password}, format='json')


# ── Test 1 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_success_returns_tokens(client, user):
    resp = _post(client, 'rep@example.com', 'correct_pass')
    assert resp.status_code == 200
    assert 'access' in resp.data
    assert 'refresh' in resp.data
    assert resp.data['user']['email'] == 'rep@example.com'


# ── Test 2 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_wrong_password_returns_401(client, user):
    resp = _post(client, 'rep@example.com', 'wrong_pass')
    assert resp.status_code == 401
    assert resp.data['error'] is True


# ── Test 3 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_wrong_password_increments_failed_count(client, user):
    _post(client, 'rep@example.com', 'wrong')
    user.refresh_from_db()
    assert user.failed_login_count == 1


# ── Test 4 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_five_failures_locks_account(client, user, settings):
    settings.THRIIVE_MAX_LOGIN_ATTEMPTS = 5
    for _ in range(4):
        resp = _post(client, 'rep@example.com', 'wrong')
        assert resp.status_code == 401
    resp = _post(client, 'rep@example.com', 'wrong')
    assert resp.status_code == 423
    assert resp.data['error'] is True
    user.refresh_from_db()
    assert user.locked_until is not None


# ── Test 5 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_lockout_expires_allows_login(client, user):
    from datetime import timedelta
    user.locked_until = timezone.now() - timedelta(minutes=1)
    user.failed_login_count = 5
    user.save()
    resp = _post(client, 'rep@example.com', 'correct_pass')
    assert resp.status_code == 200
    assert 'access' in resp.data


# ── Test 6 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_login_by_mobile(client, db):
    User.objects.create_user(mobile='9876543210', password='mobilepass')
    resp = _post(client, '9876543210', 'mobilepass')
    assert resp.status_code == 200
    assert resp.data['user']['mobile'] == '9876543210'


# ── Test 7 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_login_by_employee_id(client, db):
    User.objects.create_user(employee_id='EMP001', password='emppass')
    resp = _post(client, 'EMP001', 'emppass')
    assert resp.status_code == 200
    assert resp.data['user']['employee_id'] == 'EMP001'


# ── Test 8 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_unknown_identifier_returns_401_same_as_wrong_password(client, db):
    # No user enumeration: same 401 as wrong password
    resp = _post(client, 'nobody@example.com', 'any_pass')
    assert resp.status_code == 401
    assert resp.data['error'] is True
    assert resp.data['detail'] == 'Invalid credentials.'


# ── Test 9 ──────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_inactive_user_returns_401(client, db):
    User.objects.create_user(email='inactive@example.com', password='pass', is_active=False)
    resp = _post(client, 'inactive@example.com', 'pass')
    assert resp.status_code == 401


# ── Test 10 ─────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_login_attempt_is_logged(client, user):
    before = LoginAttempt.objects.count()
    _post(client, 'rep@example.com', 'wrong')
    assert LoginAttempt.objects.count() == before + 1
    attempt = LoginAttempt.objects.filter(identifier='rep@example.com').latest('timestamp')
    assert not attempt.success
    assert attempt.method == 'password'


# ── Test 11 ─────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_entity_info_in_response(client, user):
    from datetime import date
    from apps.hierarchy.models import NodeType

    entity_type = NodeType.objects.create(
        name='National Sales Manager',
        code='NSM',
        level_order=1,
        effective_from=date.today(),
    )
    entity = Node.objects.create(
        entity_type=entity_type,
        name='North Zone Sales',
        code='NZ001',
        effective_from=date.today(),
    )
    user.entity = entity
    user.save()
    resp = _post(client, 'rep@example.com', 'correct_pass')
    assert resp.status_code == 200
    entity_info = resp.data['user']['entity_info']
    assert entity_info is not None
    assert entity_info['id'] == entity.id
    assert entity_info['name'] == 'North Zone Sales'


# ── Test 12 ─────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_user_without_entity_returns_null_entity_info(client, user):
    assert user.entity_id is None
    resp = _post(client, 'rep@example.com', 'correct_pass')
    assert resp.status_code == 200
    assert resp.data['user']['entity_info'] is None


# ── Test 13 (portal_type) ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_portal_type_field_present_in_response(client, user):
    # A user with no entity defaults to the 'admin' portal — see User.portal_type
    # and FOUNDATION_BLUEPRINT test_user_without_entity. The field must always be
    # present in the user payload and is never null.
    resp = _post(client, 'rep@example.com', 'correct_pass')
    assert resp.status_code == 200
    assert 'portal_type' in resp.data['user']
    assert resp.data['user']['portal_type'] == 'admin'
