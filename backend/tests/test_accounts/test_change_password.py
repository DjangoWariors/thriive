"""Change-password endpoint — success, wrong old password, OTP-only, weak password."""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

URL = '/api/v1/auth/me/change-password/'


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def user(db):
    return User.objects.create_user(email='rep@example.com', password='OldPass@123')


@pytest.mark.django_db
class TestChangePassword:
    def test_success(self, user):
        resp = client_for(user).post(
            URL, {'old_password': 'OldPass@123', 'new_password': 'BrandNew@987'}, format='json')
        assert resp.status_code == 200
        user.refresh_from_db()
        assert user.check_password('BrandNew@987')

    def test_wrong_old_password(self, user):
        resp = client_for(user).post(
            URL, {'old_password': 'nope', 'new_password': 'BrandNew@987'}, format='json')
        assert resp.status_code == 422
        user.refresh_from_db()
        assert user.check_password('OldPass@123')

    def test_weak_new_password_rejected(self, user):
        resp = client_for(user).post(
            URL, {'old_password': 'OldPass@123', 'new_password': '123'}, format='json')
        assert resp.status_code == 422
        user.refresh_from_db()
        assert user.check_password('OldPass@123')

    def test_otp_only_account_rejected(self, db):
        otp_user = User.objects.create(email='otp@example.com')
        otp_user.set_unusable_password()
        otp_user.save()
        resp = client_for(otp_user).post(
            URL, {'old_password': 'anything', 'new_password': 'BrandNew@987'}, format='json')
        assert resp.status_code == 422

    def test_requires_auth(self, db):
        resp = APIClient().post(
            URL, {'old_password': 'x', 'new_password': 'y'}, format='json')
        assert resp.status_code == 401
