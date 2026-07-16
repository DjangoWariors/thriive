import hashlib
import json

from django.db import transaction

from apps.audit.middleware import get_current_request
from apps.audit.models import AccessLog, AuditChainHead, AuditLog, ComputationLog


def _row_hash(prev_hash: str, action: str, entity_type: str,
              entity_id: int, user_id: int | None, changes: dict) -> str:
    """Deterministic sha256 over the immutable content of an audit row,
    chained to its predecessor's hash. ``timestamp`` is intentionally excluded:
    it is server-set (auto_now_add) and immutable under the append-only grant,
    and excluding it keeps the hash reproducible without clock-format coupling."""
    payload = json.dumps(
        {
            'prev': prev_hash,
            'action': action,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'user_id': user_id,
            'changes': changes or {},
        },
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class AuditService:

    @staticmethod
    def log(action: str, entity_type: str, entity_id: int, user, changes: dict | None = None) -> AuditLog:
        """
        Append an immutable, hash-chained AuditLog entry.

        Args:
            action:      Verb describing the mutation ('create', 'update', 'move', 'deactivate', …).
            entity_type: Dotted model label, e.g. 'hierarchy.Node'.
            entity_id:   PK of the affected record.
            user:        The acting User instance (or None for system tasks).
            changes:     Dict of field-level before/after values.
        """
        user_id = user.pk if user is not None else None
        changes = changes or {}
        with transaction.atomic():
            head = AuditChainHead.objects.select_for_update().first()
            if head is None:
                head = AuditChainHead.objects.create(last_hash='')
                head = AuditChainHead.objects.select_for_update().get(pk=head.pk)
            prev = head.last_hash
            row_hash = _row_hash(prev, action, entity_type, entity_id, user_id, changes)
            entry = AuditLog.objects.create(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                changes=changes,
                prev_hash=prev,
                row_hash=row_hash,
            )
            head.last_hash = row_hash
            head.save(update_fields=['last_hash', 'updated_at'])
        return entry

    @staticmethod
    def verify_chain(start_id: int | None = None, end_id: int | None = None) -> dict:
        """
        Recompute the hash chain over a (optionally bounded) range and report the
        first tampered row. ``ok=True`` means every row's content still matches
        its stored row_hash and each links cleanly to its predecessor.
        """
        qs = AuditLog.objects.all().order_by('id')
        if start_id is not None:
            qs = qs.filter(id__gte=start_id)
        if end_id is not None:
            qs = qs.filter(id__lte=end_id)

        prev_row_hash = None
        count = 0
        for row in qs.iterator():
            count += 1
            expected = _row_hash(
                row.prev_hash, row.action, row.entity_type,
                row.entity_id, row.user_id, row.changes,
            )
            if expected != row.row_hash:
                return {'ok': False, 'broken_at': row.id,
                        'reason': 'content_hash_mismatch', 'checked': count}
            # First in-window row links to a row before the window — skip the link check.
            if prev_row_hash is not None and row.prev_hash != prev_row_hash:
                return {'ok': False, 'broken_at': row.id,
                        'reason': 'chain_link_mismatch', 'checked': count}
            prev_row_hash = row.row_hash

        return {'ok': True, 'broken_at': None, 'reason': None, 'checked': count}


class AccessService:
    """Records disclosure of confidential data (payout / variable-pay reads)."""

    @staticmethod
    def record(user, resource: str, subject_entity_id: int | None = None,
               action: str = 'view', object_id: int | None = None) -> AccessLog:
        req = get_current_request()
        return AccessLog.objects.create(
            user_id=getattr(user, 'pk', None),
            resource=resource,
            object_id=object_id,
            subject_entity_id=subject_entity_id,
            action=action,
            request_id=getattr(req, 'request_id', '') if req is not None else '',
            ip_address=getattr(req, 'client_ip', '') if req is not None else '',
        )


class ComputationService:
    """Read access to stored computation snapshots — the 'explain this number'
    path for a disputed payout/achievement/earning, without re-running."""

    @staticmethod
    def get_snapshot(computation_id: int) -> dict | None:
        log = ComputationLog.objects.filter(pk=computation_id).first()
        if log is None:
            return None
        return {
            'id': log.pk,
            'computation_type': log.computation_type,
            'entity_id': log.entity_id,
            'period_id': log.period_id,
            'triggered_by_id': log.triggered_by_id,
            'config_snapshot': log.config_snapshot,
            'result_snapshot': log.result_snapshot,
            'timestamp': log.timestamp,
        }
