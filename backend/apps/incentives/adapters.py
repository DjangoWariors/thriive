"""Workflow subject adapters for incentives. Registered in ``IncentivesConfig.ready()``.

These invert the dependency: the generic ``workflows`` app never imports incentives; instead
incentives teaches the engine how to route, summarize, and finalize its objects. The terminal
callbacks write the decision back onto the domain object so the rest of the system (the payout
engine reads ``PayoutException.status``) is unaffected.
"""
from django.utils import timezone

from apps.workflows import adapters as wf
from apps.workflows.adapters import SubjectAdapter

from .models import PayoutException, PayoutRun, VariablePay


def exception_pay_at_stake(exc) -> object | None:
    """The money an exception's treatment governs: the person's variable pay for the period.

    Not a simulated payout delta — computing that needs achievements that often don't exist
    yet when the exception is raised, and it would change under the approver's feet. The VP
    is the pot every multiplier in that month is applied to, so it is the honest ceiling on
    what this decision moves. ``None`` when no VP is on file yet.
    """
    vp = (
        VariablePay.objects
        .filter(entity_id=exc.entity_id, target_period_id=exc.target_period_id, is_active=True)
        .values_list('amount', flat=True)
        .first()
    )
    return vp


class PayoutExceptionAdapter(SubjectAdapter):
    subject_type = 'incentives.PayoutException'

    def load(self, subject_id):
        return PayoutException.objects.filter(pk=subject_id).select_related('entity').first()

    def anchor_entity(self, subject):
        return subject.entity

    def build_context(self, subject) -> dict:
        context = {
            'kind': 'payout_exception',
            'category_code': subject.category or '',
            'entity_id': subject.entity_id,
            'entity_name': subject.entity.name,
            'entity_code': subject.entity.code,
            'entity_path': subject.entity.path,
            'scheme_id': subject.scheme_id,
            'period_id': subject.target_period_id,
            'reason': subject.reason,
            'title': f'{subject.entity.name} — {subject.category or "exception"}',
        }
        amount = exception_pay_at_stake(subject)
        if amount is not None:
            # Confidential: serializers strip this for readers without payout access.
            context['impact_amount'] = str(amount)
        return context

    def summary(self, subject) -> dict:
        return {
            'kind': 'payout_exception',
            'entity_name': subject.entity.name,
            'entity_code': subject.entity.code,
            'category': subject.category,
            'reason': subject.reason,
            'period_id': subject.target_period_id,
            'scheme_id': subject.scheme_id,
        }

    def on_approved(self, instance, subject) -> None:
        from .services import ExceptionService

        last = (
            instance.actions
            .filter(action__in=('approve', 'auto_approve'))
            .order_by('-created_at').first()
        )
        subject.status = PayoutException.APPROVED
        subject.approved_by_id = last.action_by_id if last else None
        subject.approved_at = timezone.now()
        subject.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        # Multi-month categories cover the following periods with approved children.
        ExceptionService.materialize_children(subject)

    def on_rejected(self, instance, subject) -> None:
        last = instance.actions.filter(action='reject').order_by('-created_at').first()
        subject.status = PayoutException.REJECTED
        subject.rejection_reason = last.comments if last else ''
        # Mirror on_approved: the decision columns record who settled the request either way.
        subject.approved_by_id = last.action_by_id if last else None
        subject.approved_at = timezone.now()
        subject.save(update_fields=['status', 'rejection_reason', 'approved_by', 'approved_at',
                                    'updated_at'])


class PayoutRunAdapter(SubjectAdapter):
    """Second adapter — proves the engine is generic. Registered and ready, but not seeded:
    run governance defaults to the cycle-level maker-checker (PayoutCycleService). A client
    that wants per-run sign-off can configure a 'payout_run_approval' WorkflowDefinition and
    initiate it at submit time."""

    subject_type = 'incentives.PayoutRun'

    def load(self, subject_id):
        return PayoutRun.objects.filter(pk=subject_id).select_related('scheme', 'target_period').first()

    def anchor_entity(self, subject):
        return None  # plan-wide object → role-based routing only

    def build_context(self, subject) -> dict:
        return {
            'kind': 'payout_run',
            'scheme_code': subject.scheme.code,
            'period_id': subject.target_period_id,
            'total_payout': str(subject.total_payout),
            'impact_amount': str(subject.total_payout),
            'title': f'Payout run {subject.scheme.code}@{subject.target_period.code}',
        }

    def summary(self, subject) -> dict:
        return {
            'kind': 'payout_run',
            'scheme_code': subject.scheme.code,
            'period_id': subject.target_period_id,
            'total_payout': str(subject.total_payout),
            'entities_processed': subject.entities_processed,
        }

    def on_approved(self, instance, subject) -> None:
        last = (
            instance.actions
            .filter(action__in=('approve', 'auto_approve'))
            .order_by('-created_at').first()
        )
        subject.status = PayoutRun.APPROVED
        subject.approved_by_id = last.action_by_id if last else None
        subject.approved_at = timezone.now()
        subject.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def on_rejected(self, instance, subject) -> None:
        # Mirror PayoutService.reject: a rejected run returns to COMPUTED for recompute.
        last = instance.actions.filter(action='reject').order_by('-created_at').first()
        subject.status = PayoutRun.COMPUTED
        subject.rejection_reason = last.comments if last else ''
        subject.save(update_fields=['status', 'rejection_reason', 'updated_at'])


def register() -> None:
    wf.register(PayoutExceptionAdapter.subject_type, PayoutExceptionAdapter())
    wf.register(PayoutRunAdapter.subject_type, PayoutRunAdapter())
