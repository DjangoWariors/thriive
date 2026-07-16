"""Notification triggers — achievements, payouts, exceptions fire to the right users."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.achievements.notifications import notify_achievements_computed
from apps.incentives.models import PayoutException
from apps.incentives.notifications import notify_payout_ready
from apps.incentives.services import ExceptionService
from apps.notifications.models import Notification


@pytest.mark.django_db
class TestAchievementTrigger:
    def test_one_per_entity_with_user_deduped(self, org):
        ase, asm = org['ase'], org['asm']
        User.objects.create_user(email='ase@x.com', password='pass', entity=ase)
        period = SimpleNamespace(code='JUN26', name='June 2026')
        # ase has a user, asm has a user (asm_user fixture), duplicates collapse to one each
        notify_achievements_computed(period, [ase.id, asm.id, ase.id])
        codes = list(Notification.objects.filter(code='achievement_computed')
                     .values_list('user__email', flat=True))
        assert sorted(codes) == ['ase@x.com', 'asm@x.com']

    def test_entity_without_user_skipped(self, org):
        period = SimpleNamespace(code='JUN26', name='June 2026')
        notify_achievements_computed(period, [org['ase'].id])  # ase has no user
        assert Notification.objects.filter(code='achievement_computed').count() == 0


@pytest.mark.django_db
class TestPayoutTrigger:
    def test_notifies_paid_entity_user(self, org):
        ase = org['ase']
        ase_user = User.objects.create_user(email='ase@x.com', password='pass', entity=ase)
        run = SimpleNamespace(scheme=SimpleNamespace(name='FF'),
                              target_period=SimpleNamespace(name='June 2026'))
        notify_payout_ready(run, [(ase, Decimal('71000.00'))])
        n = Notification.objects.get(code='payout_ready', user=ase_user)
        assert n.metadata['total_payout'] == '71000.00'


@pytest.mark.django_db
class TestExceptionTriggers:
    def _create(self, org):
        return ExceptionService.create(
            {'entity': org['ase'], 'target_period': org['period'], 'reason': 'leave'},
            actor=org['requester'],
        )

    def test_create_notifies_checker(self, org, period):
        org['period'] = period
        self._create(org)
        # No workflow seeded → direct path notifies the nearest manager (asm_user).
        assert Notification.objects.filter(
            code='exception_raised', user=org['asm_user']).exists()

    def test_approve_notifies_raiser(self, org, period):
        org['period'] = period
        exc = self._create(org)
        ExceptionService.approve(exc, org['asm_user'])
        n = Notification.objects.get(code='exception_resolved', user=org['requester'])
        assert n.metadata['status'] == PayoutException.APPROVED

    def test_reject_notifies_raiser(self, org, period):
        org['period'] = period
        exc = self._create(org)
        ExceptionService.reject(exc, org['asm_user'], 'insufficient proof')
        n = Notification.objects.get(code='exception_resolved', user=org['requester'])
        assert n.metadata['status'] == PayoutException.REJECTED
        assert 'insufficient proof' in n.body or n.metadata['rejection_reason'] == 'insufficient proof'
