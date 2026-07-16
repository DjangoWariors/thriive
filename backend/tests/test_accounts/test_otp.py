"""
7 OTP tests + /me/ smoke tests (verify criteria: portal_type + token refresh).
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import OTPToken, User

OTP_REQUEST_URL = '/api/v1/auth/login/otp/request/'
OTP_VERIFY_URL = '/api/v1/auth/login/otp/verify/'
TOKEN_REFRESH_URL = '/api/v1/auth/token/refresh/'
LOGOUT_URL = '/api/v1/auth/logout/'
ME_URL = '/api/v1/auth/me/'


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email='otp@example.com',
        mobile='9876543210',
    )


@pytest.fixture
def valid_token(user):
    return OTPToken.objects.create(
        identifier='otp@example.com',
        otp='123456',
        purpose='login',
        expires_at=timezone.now() + timedelta(minutes=5),
    )


# ── Test 1: OTP created ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_otp_created(client, user):
    resp = client.post(OTP_REQUEST_URL, {'identifier': 'otp@example.com'}, format='json')
    assert resp.status_code == 200
    assert OTPToken.objects.filter(identifier='otp@example.com', purpose='login').exists()
    assert resp.data['masked_identifier'].startswith('o')  # 'o***@example.com'
    assert resp.data['expires_in'] > 0


# ── Test 2: Correct OTP → tokens ───────────────────────────────────────────────

@pytest.mark.django_db
def test_correct_otp_returns_tokens(client, user, valid_token):
    resp = client.post(OTP_VERIFY_URL, {'identifier': 'otp@example.com', 'otp': '123456'}, format='json')
    assert resp.status_code == 200
    assert 'access' in resp.data
    assert 'refresh' in resp.data
    assert resp.data['user']['email'] == 'otp@example.com'
    valid_token.refresh_from_db()
    assert valid_token.is_used is True


# ── Test 3: Wrong OTP → 401 + increments attempts ─────────────────────────────

@pytest.mark.django_db
def test_wrong_otp_returns_401_and_increments_attempts(client, user, valid_token):
    resp = client.post(OTP_VERIFY_URL, {'identifier': 'otp@example.com', 'otp': '000000'}, format='json')
    assert resp.status_code == 401
    valid_token.refresh_from_db()
    assert valid_token.attempts == 1


# ── Test 4: Expired OTP → 401 ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_expired_otp_returns_401(client, user):
    OTPToken.objects.create(
        identifier='otp@example.com',
        otp='123456',
        purpose='login',
        expires_at=timezone.now() - timedelta(minutes=1),  # expired
    )
    resp = client.post(OTP_VERIFY_URL, {'identifier': 'otp@example.com', 'otp': '123456'}, format='json')
    assert resp.status_code == 401


# ── Test 5: Already-used OTP → 401 ────────────────────────────────────────────

@pytest.mark.django_db
def test_used_otp_returns_401(client, user):
    OTPToken.objects.create(
        identifier='otp@example.com',
        otp='123456',
        purpose='login',
        expires_at=timezone.now() + timedelta(minutes=5),
        is_used=True,  # already consumed
    )
    resp = client.post(OTP_VERIFY_URL, {'identifier': 'otp@example.com', 'otp': '123456'}, format='json')
    assert resp.status_code == 401


# ── Test 6: Max attempts exhausted ────────────────────────────────────────────

@pytest.mark.django_db
def test_max_attempts_rejects_without_incrementing(client, user):
    token = OTPToken.objects.create(
        identifier='otp@example.com',
        otp='123456',
        purpose='login',
        expires_at=timezone.now() + timedelta(minutes=5),
        attempts=3,
        max_attempts=3,  # already exhausted
    )
    resp = client.post(OTP_VERIFY_URL, {'identifier': 'otp@example.com', 'otp': '123456'}, format='json')
    assert resp.status_code == 401
    token.refresh_from_db()
    assert token.attempts == 3  # not incremented


# ── Test 7: Rate limit — 6th request returns 429 ──────────────────────────────

@pytest.mark.django_db
def test_rate_limit_sixth_request_returns_429(client, user, settings):
    settings.THRIIVE_OTP_RATE_LIMIT = 5
    # Pre-create 5 tokens in the rate-limit window
    for _ in range(5):
        OTPToken.objects.create(
            identifier='otp@example.com',
            otp='000000',
            purpose='login',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
    # 6th request should be rate-limited
    resp = client.post(OTP_REQUEST_URL, {'identifier': 'otp@example.com'}, format='json')
    assert resp.status_code == 429
    assert resp.data['error'] is True


# ── /me/ smoke tests (verify criteria) ────────────────────────────────────────

@pytest.mark.django_db
def test_me_returns_portal_type_field(client, user):
    # Authenticate via password login first
    user.set_password('pass')
    user.save()
    login_resp = client.post('/api/v1/auth/login/', {'identifier': 'otp@example.com', 'password': 'pass'}, format='json')
    assert login_resp.status_code == 200

    client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')
    resp = client.get(ME_URL)
    assert resp.status_code == 200
    assert 'portal_type' in resp.data
    assert resp.data['email'] == 'otp@example.com'


@pytest.mark.django_db
def test_me_patch_updates_profile(client, user):
    user.set_password('pass')
    user.save()
    login_resp = client.post('/api/v1/auth/login/', {'identifier': 'otp@example.com', 'password': 'pass'}, format='json')
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')

    resp = client.patch(ME_URL, {'first_name': 'Priya', 'designation': 'ASE'}, format='json')
    assert resp.status_code == 200
    assert resp.data['first_name'] == 'Priya'
    assert resp.data['designation'] == 'ASE'


@pytest.mark.django_db
def test_token_refresh_rotates(client, user):
    user.set_password('pass')
    user.save()
    login_resp = client.post('/api/v1/auth/login/', {'identifier': 'otp@example.com', 'password': 'pass'}, format='json')
    old_refresh = login_resp.data['refresh']

    resp = client.post(TOKEN_REFRESH_URL, {'refresh': old_refresh}, format='json')
    assert resp.status_code == 200
    assert 'access' in resp.data
    # Rotation: a new refresh token is issued
    assert 'refresh' in resp.data
    assert resp.data['refresh'] != old_refresh
