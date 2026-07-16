"""Notification preferences — default-on, opt-out blocks send, categories, API."""
import pytest

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference, NotificationTemplate
from apps.notifications.services import NotificationPreferenceService, NotificationService

from .conftest import client_for

URL = '/api/v1/notifications/preferences/'


@pytest.fixture
def user(db):
    return User.objects.create_user(email='u@x.com', password='pass')


@pytest.mark.django_db
class TestPreferenceService:
    def test_default_allowed_when_unset(self, user):
        assert NotificationPreferenceService.is_allowed(user, 'payout', 'in_app') is True

    def test_opt_out_blocks_send(self, user):
        NotificationPreferenceService.set(user, {'payout': {'in_app': False}})
        n = NotificationService.send(user, 'payout_ready', {'category': 'payout', 'title': 'x'})
        assert n is None
        assert Notification.objects.filter(user=user).count() == 0

    def test_other_category_still_sends(self, user):
        NotificationPreferenceService.set(user, {'payout': {'in_app': False}})
        n = NotificationService.send(user, 'kyc_approved', {'category': 'kyc', 'title': 'x'})
        assert n is not None

    def test_available_categories_reflects_templates(self, user):
        NotificationTemplate.objects.create(code='a', category='payout')
        NotificationTemplate.objects.create(code='b', category='kyc')
        NotificationTemplate.objects.create(code='c', category='')  # blank excluded
        cats = NotificationPreferenceService.available_categories()
        assert cats == ['kyc', 'payout']


@pytest.mark.django_db
class TestPreferenceApi:
    def test_get_returns_payload(self, user):
        NotificationTemplate.objects.create(code='a', category='payout')
        resp = client_for(user).get(URL)
        assert resp.status_code == 200
        assert resp.data['prefs'] == {}
        assert 'payout' in resp.data['available_categories']
        assert resp.data['channels'] == ['in_app', 'email', 'sms']

    def test_patch_persists(self, user):
        resp = client_for(user).patch(
            URL, {'prefs': {'payout': {'in_app': False}}}, format='json')
        assert resp.status_code == 200
        assert resp.data['prefs'] == {'payout': {'in_app': False}}
        assert NotificationPreference.objects.get(user=user).prefs == {'payout': {'in_app': False}}

    def test_requires_auth(self, db):
        from rest_framework.test import APIClient
        assert APIClient().get(URL).status_code == 401
