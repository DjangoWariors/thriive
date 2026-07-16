"""Notification API — own-only scoping, unread-count, mark read/all."""
import pytest

from apps.accounts.models import User
from apps.notifications.models import Notification

from .conftest import client_for

BASE = '/api/v1/notifications/'


@pytest.fixture
def two_users(db):
    a = User.objects.create_user(email='a@x.com', password='pass')
    b = User.objects.create_user(email='b@x.com', password='pass')
    Notification.objects.create(user=a, title='a1', code='payout_ready')
    Notification.objects.create(user=a, title='a2', code='exception_raised')
    Notification.objects.create(user=b, title='b1', code='payout_ready')
    return a, b


@pytest.mark.django_db
class TestNotificationApi:
    def test_list_scoped_to_self(self, two_users):
        a, _ = two_users
        resp = client_for(a).get(BASE)
        assert resp.status_code == 200
        assert resp.data['count'] == 2

    def test_unread_count(self, two_users):
        a, _ = two_users
        resp = client_for(a).get(f'{BASE}unread-count/')
        assert resp.data == {'count': 2}

    def test_unread_filter(self, two_users):
        a, _ = two_users
        Notification.objects.filter(user=a, title='a1').update(is_read=True)
        resp = client_for(a).get(BASE, {'unread': 'true'})
        assert resp.data['count'] == 1

    def test_mark_one_read(self, two_users):
        a, _ = two_users
        nid = Notification.objects.filter(user=a, title='a1').first().pk
        resp = client_for(a).post(f'{BASE}{nid}/read/')
        assert resp.status_code == 200
        assert resp.data['is_read'] is True

    def test_cannot_read_others_notification(self, two_users):
        a, b = two_users
        other = Notification.objects.filter(user=b).first().pk
        resp = client_for(a).post(f'{BASE}{other}/read/')
        assert resp.status_code == 404

    def test_mark_all_read(self, two_users):
        a, _ = two_users
        resp = client_for(a).post(f'{BASE}read-all/')
        assert resp.data == {'marked': 2}
        assert client_for(a).get(f'{BASE}unread-count/').data == {'count': 0}
