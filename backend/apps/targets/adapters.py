"""Workflow subject adapter for target revisions. Registered in ``TargetsConfig.ready()``.

Follows the same inversion as incentives: the generic ``workflows`` app never imports targets.
An escalated ``TargetRevision`` (a published-period edit beyond the auto-approve band) routes to
the editor's **org immediate manager** — approvals follow reporting lines even though the target
itself is geography-anchored. The terminal callbacks flip the revision + its allocation so the
rest of the system (achievements read ``effective_target``) stays consistent.
"""
from django.utils import timezone

from apps.audit.services import AuditService
from apps.workflows import adapters as wf
from apps.workflows.adapters import SubjectAdapter

from .models import TargetAllocation, TargetRevision

TARGET_REVISION_WF = 'target_revision'


class TargetRevisionAdapter(SubjectAdapter):
    subject_type = 'targets.TargetRevision'

    def load(self, subject_id):
        return (
            TargetRevision.objects
            .filter(pk=subject_id)
            .select_related('allocation', 'allocation__geography_node', 'requested_by')
            .first()
        )

    def anchor_entity(self, subject):
        # Route from the editor's org entity; managers above it approve (Entity.parent chain).
        user = subject.requested_by
        return getattr(user, 'entity', None) if user else None

    def build_context(self, subject) -> dict:
        alloc = subject.allocation
        geo = alloc.geography_node
        label = geo.name if geo else f'allocation {alloc.id}'
        return {
            'kind': 'target_revision',
            'allocation_id': alloc.id,
            'geography_node_id': alloc.geography_node_id,
            'geography_name': geo.name if geo else None,
            'kpi_id': alloc.kpi_id,
            'period_id': alloc.target_period_id,
            'old_value': str(subject.old_value),
            'new_value': str(subject.new_value),
            'delta_pct': str(subject.delta_pct),
            'impact_amount': str(abs(subject.delta)),
            'reason': subject.reason,
            # Round for the title: the raw Decimals render as "78806.7000→69350" in the
            # approvals inbox, which is a model dump, not a number a reviewer reads.
            'title': (
                f'Target revision — {label} '
                f'({subject.old_value:,.0f} → {subject.new_value:,.0f})'
            ),
        }

    def summary(self, subject) -> dict:
        alloc = subject.allocation
        return {
            'kind': 'target_revision',
            'geography_name': alloc.geography_node.name if alloc.geography_node else None,
            'kpi_id': alloc.kpi_id,
            'period_id': alloc.target_period_id,
            'old_value': str(subject.old_value),
            'new_value': str(subject.new_value),
            'delta_pct': str(subject.delta_pct),
            # The approval drawer renders subject_summary.reason — the editor's "why" is
            # exactly what the deciding manager needs in front of them.
            'reason': subject.reason,
        }

    def on_approved(self, instance, subject) -> None:
        if self._locked(instance, subject):
            return
        # The override is already applied on the allocation (PENDING); approval confirms it.
        last = (
            instance.actions
            .filter(action__in=('approve', 'auto_approve'))
            .order_by('-created_at').first()
        )
        subject.status = TargetRevision.APPROVED
        subject.approved_by_id = last.action_by_id if last else None
        subject.approved_at = timezone.now()
        subject.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        alloc = subject.allocation
        if alloc.status == TargetAllocation.PENDING:
            alloc.status = TargetAllocation.APPROVED
            alloc.save(update_fields=['status', 'updated_at'])
        from .review_services import ReviewService
        ReviewService.resolve_escalation(alloc, approved=True)

    def on_rejected(self, instance, subject) -> None:
        if self._locked(instance, subject):
            return
        # Revert the allocation to its pre-change value (mirrors TargetService.reject_allocation).
        last = instance.actions.filter(action='reject').order_by('-created_at').first()
        subject.status = TargetRevision.REJECTED
        if last and last.comments:
            subject.reason = (subject.reason + f' | rejected: {last.comments}').strip(' |')
        subject.approved_by_id = last.action_by_id if last else None
        subject.approved_at = timezone.now()
        subject.save(update_fields=['status', 'reason', 'approved_by', 'approved_at', 'updated_at'])
        alloc = subject.allocation
        alloc.override_value = None if subject.old_value == alloc.target_value else subject.old_value
        alloc.is_modified = alloc.override_value is not None
        alloc.status = TargetAllocation.APPROVED
        alloc.save(update_fields=['override_value', 'is_modified', 'status', 'updated_at'])
        from .services import TargetService
        TargetService._revert_side_effects(subject)
        from .review_services import ReviewService
        ReviewService.resolve_escalation(alloc, approved=False)

    @staticmethod
    def _locked(instance, subject) -> bool:
        """A locked allocation is a frozen, already-paid base — a late workflow decision
        (the race window around a payout-cycle finalize) must not move it."""
        if subject.allocation.status != TargetAllocation.LOCKED:
            return False
        AuditService.log('update', 'targets.TargetRevision', subject.id, None,
                         {'workflow_decision_ignored': 'allocation locked by payout cycle',
                          'workflow_instance': instance.pk})
        return True


def register() -> None:
    wf.register(TargetRevisionAdapter.subject_type, TargetRevisionAdapter())
