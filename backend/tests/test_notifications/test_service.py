"""NotificationService — rendering, fallback, unread count, mark read/all."""
import pytest

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationTemplate
from apps.notifications.services import NotificationService


@pytest.fixture
def user(db):
    return User.objects.create_user(email='u@x.com', password='pass')


@pytest.mark.django_db
class TestSend:
    def test_renders_from_template(self, user):
        NotificationTemplate.objects.create(
            code='payout_ready', category='payout', channel=NotificationTemplate.IN_APP,
            title_template='Payout ready', body_template='₹{total_payout} for {scheme}.',
            link_template='/incentives/payouts',
        )
        n = NotificationService.send(user, 'payout_ready',
                                     {'total_payout': '71000.00', 'scheme': 'FF'})
        assert n.title == 'Payout ready'
        assert n.body == '₹71000.00 for FF.'
        assert n.link == '/incentives/payouts'
        assert n.category == 'payout'
        assert n.is_read is False

    def test_unknown_code_falls_back_to_humanized_title(self, user):
        n = NotificationService.send(user, 'some_new_event', {})
        assert n.title == 'Some New Event'
        assert n.code == 'some_new_event'

    def test_none_user_returns_none(self, db):
        assert NotificationService.send(None, 'payout_ready', {}) is None

    def test_email_template_dispatches_email_task(self, user, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        NotificationTemplate.objects.create(
            code='payout_ready', category='payout', channel=NotificationTemplate.EMAIL,
            title_template='Payout ready', body_template='Done.',
        )
        n = NotificationService.send(user, 'payout_ready', {})
        assert n is not None  # in-app row is always created
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [user.email]
        assert mailoutbox[0].subject == 'Payout ready'

    def test_missing_context_key_renders_empty(self, user):
        NotificationTemplate.objects.create(
            code='exception_resolved', category='exception',
            title_template='Exception {status}', body_template='Reason: {rejection_reason}',
        )
        n = NotificationService.send(user, 'exception_resolved', {'status': 'approved'})
        assert n.title == 'Exception approved'
        assert n.body == 'Reason: '


@pytest.mark.django_db
class TestSendBulk:
    def test_bulk_renders_skips_none_and_respects_optout(self, django_assert_max_num_queries):
        from apps.notifications.services import NotificationPreferenceService

        NotificationTemplate.objects.create(
            code='payout_ready', category='payout', channel=NotificationTemplate.IN_APP,
            title_template='Payout ready', body_template='₹{total_payout} for {scheme}.',
        )
        users = [User.objects.create_user(email=f'b{i}@x.com', password='p') for i in range(4)]
        NotificationPreferenceService.set(users[0], {'payout': {'in_app': False}})  # opted out

        recipients = [(None, {'total_payout': '1', 'scheme': 'S'})] + [
            (u, {'total_payout': str(100 + i), 'scheme': 'S'}) for i, u in enumerate(users)
        ]
        # One template fetch + one preference fetch + one insert — never a query per user.
        with django_assert_max_num_queries(4):
            sent = NotificationService.send_bulk('payout_ready', recipients)
        assert sent == 3  # 4 users − 1 opted out; the None user silently skipped
        assert Notification.objects.filter(user=users[0]).count() == 0
        n = Notification.objects.get(user=users[1])
        assert n.title == 'Payout ready' and n.body == '₹101 for S.' and n.category == 'payout'

    def test_bulk_empty_is_noop(self, db):
        assert NotificationService.send_bulk('payout_ready', []) == 0


@pytest.mark.django_db
class TestReadState:
    def test_unread_count(self, user):
        Notification.objects.create(user=user, title='a')
        Notification.objects.create(user=user, title='b')
        assert NotificationService.unread_count(user) == 2

    def test_mark_read_sets_timestamp(self, user):
        n = Notification.objects.create(user=user, title='a')
        NotificationService.mark_read(n)
        n.refresh_from_db()
        assert n.is_read is True
        assert n.read_at is not None
        assert NotificationService.unread_count(user) == 0

    def test_mark_all_read(self, user):
        Notification.objects.create(user=user, title='a')
        Notification.objects.create(user=user, title='b')
        marked = NotificationService.mark_all_read(user)
        assert marked == 2
        assert NotificationService.unread_count(user) == 0
