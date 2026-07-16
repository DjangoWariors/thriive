"""Hash-chain integrity + access logging + retention. Service-layer unit tests."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AccessLog, AuditLog, ComputationLog, RetentionPolicy
from apps.audit.services import AccessService, AuditService, ComputationService
from apps.audit.tasks import sweep_retention

pytestmark = pytest.mark.django_db


class TestHashChain:
    def test_chain_links_across_appends(self):
        a = AuditService.log('create', 'hierarchy.Node', 1, None, {'name': 'A'})
        b = AuditService.log('update', 'hierarchy.Node', 1, None, {'name': 'B'})
        c = AuditService.log('update', 'hierarchy.Node', 1, None, {'name': 'C'})

        assert a.prev_hash == ''           # genesis
        assert b.prev_hash == a.row_hash   # each links to its predecessor
        assert c.prev_hash == b.row_hash
        assert len({a.row_hash, b.row_hash, c.row_hash}) == 3  # all distinct

    def test_verify_intact_chain(self):
        for i in range(5):
            AuditService.log('create', 'x.Y', i, None, {'i': i})
        result = AuditService.verify_chain()
        assert result['ok'] is True
        assert result['broken_at'] is None
        assert result['checked'] == 5

    def test_tampering_a_historical_row_is_detected(self):
        AuditService.log('create', 'x.Y', 1, None, {'amt': '100'})
        target = AuditService.log('create', 'x.Y', 2, None, {'amt': '200'})
        AuditService.log('create', 'x.Y', 3, None, {'amt': '300'})

        # Someone edits the middle row directly in the DB (bypassing the service).
        AuditLog.objects.filter(pk=target.pk).update(changes={'amt': '999999'})

        result = AuditService.verify_chain()
        assert result['ok'] is False
        assert result['broken_at'] == target.pk
        assert result['reason'] == 'content_hash_mismatch'

    def test_verify_respects_window(self):
        rows = [AuditService.log('create', 'x.Y', i, None, {'i': i}) for i in range(4)]
        # Window starting mid-chain still verifies cleanly (first in-window row's
        # link to a pre-window row is not falsely flagged).
        result = AuditService.verify_chain(start_id=rows[1].pk, end_id=rows[3].pk)
        assert result['ok'] is True
        assert result['checked'] == 3


class TestAccessLog:
    def test_record_captures_subject_and_actor(self):
        from tests.test_audit.conftest import make_user
        viewer = make_user('viewer@x.com')
        entry = AccessService.record(viewer, 'payout', subject_entity_id=42, object_id=7)
        assert entry.resource == 'payout'
        assert entry.subject_entity_id == 42
        assert entry.object_id == 7
        assert entry.user_id == viewer.pk
        assert AccessLog.objects.count() == 1


class TestComputationSnapshot:
    def test_get_snapshot_round_trips(self):
        log = ComputationLog.objects.create(
            computation_type='payout', entity_id=5, period_id=2,
            config_snapshot={'scheme_version': 3, 'multiplier': '1.20'},
            result_snapshot={'total': '71000.00'},
        )
        snap = ComputationService.get_snapshot(log.pk)
        assert snap['computation_type'] == 'payout'
        assert snap['config_snapshot']['multiplier'] == '1.20'
        assert snap['result_snapshot']['total'] == '71000.00'

    def test_missing_snapshot_returns_none(self):
        assert ComputationService.get_snapshot(999999) is None


class TestRetention:
    def test_sweep_deletes_only_aged_rows(self):
        RetentionPolicy.objects.create(log_type='access', retain_days=30)
        old = AccessLog.objects.create(resource='payout', action='view')
        AccessLog.objects.filter(pk=old.pk).update(
            timestamp=timezone.now() - timedelta(days=60))
        AccessLog.objects.create(resource='payout', action='view')  # fresh

        summary = sweep_retention()
        assert summary.get('access') == 1
        assert AccessLog.objects.count() == 1  # only the fresh one remains

    def test_sweep_archive_strategy_skips_deletion(self):
        RetentionPolicy.objects.create(log_type='access', retain_days=1,
                                       archive_strategy='archive')
        old = AccessLog.objects.create(resource='payout', action='view')
        AccessLog.objects.filter(pk=old.pk).update(
            timestamp=timezone.now() - timedelta(days=10))
        sweep_retention()
        assert AccessLog.objects.count() == 1  # archive strategy does not delete

    def test_sweep_is_beat_scheduled(self):
        from django.conf import settings
        tasks = {e['task'] for e in settings.CELERY_BEAT_SCHEDULE.values()}
        assert 'apps.audit.tasks.sweep_retention' in tasks
