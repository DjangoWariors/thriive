from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.incentives.models import PayoutException
from apps.incentives.services import ExceptionService
from apps.workflows.models import (
    ApprovalDelegation, WorkflowDefinition, WorkflowInstance, WorkflowStep,
)
from apps.workflows.services import WorkflowService

from .conftest import make_exception, make_user

pytestmark = pytest.mark.django_db


def _raise(org, period, **kw):
    """Create an exception + its workflow (raised by the area manager)."""
    exc = make_exception(org['ase1'], period, actor=org['asm_user'], **kw)
    WorkflowService.initiate(exc, 'payout_exception_standard',
                             initiated_by=org['asm_user'])
    return exc


class TestInitiation:
    def test_single_step_chain_when_impact_below_threshold(self, org, period, seeded):
        exc = _raise(org, period)  # no impact → step 2 condition false → skipped
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        assert inst.steps.count() == 1
        step = inst.steps.first()
        assert step.status == WorkflowStep.ACTIVE
        # routed to the manager above the *raiser* (asm raised → goes to nsm)
        assert step.assignee_user == org['nsm_user']

    def test_high_impact_adds_national_head_step(self, org, period, seeded):
        exc = make_exception(org['ase1'], period, actor=org['asm_user'])
        WorkflowService.initiate(exc, 'payout_exception_standard',
                                 initiated_by=org['asm_user'],
                                 context_overrides={'impact_amount': '60000'})
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        assert inst.steps.count() == 2
        assert [s.name for s in inst.steps.all()] == ['Manager Review', 'National Head Sign-off']


class TestApprovalMirrors:
    def test_final_approve_mirrors_exception_status(self, org, period, seeded):
        exc = _raise(org, period)
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        WorkflowService.approve(inst, org['nsm_user'], 'ok')
        exc.refresh_from_db()
        assert exc.status == PayoutException.APPROVED
        assert exc.approved_by == org['nsm_user']
        # critical retrofit invariant: the payout engine's resolver now sees it.
        resolved = ExceptionService.approved_for(period, None)
        assert exc.entity_id in resolved

    def test_reject_mirrors_exception_status(self, org, period, seeded):
        exc = _raise(org, period)
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        WorkflowService.reject(inst, org['nsm_user'], 'not justified')
        exc.refresh_from_db()
        assert exc.status == PayoutException.REJECTED
        assert exc.rejection_reason == 'not justified'

    def test_two_step_advances_then_finalizes(self, org, period, seeded):
        exc = make_exception(org['ase1'], period, actor=org['asm_user'])
        inst = WorkflowService.initiate(
            exc, 'payout_exception_standard', initiated_by=org['asm_user'],
            context_overrides={'impact_amount': '60000'},
        )
        # step 1 → manager (nsm). step 2 role national_head also resolves to nsm, but nsm
        # already approved step 1, so a second approver is needed → use superuser.
        WorkflowService.approve(inst, org['nsm_user'], 'step1')
        inst.refresh_from_db()
        assert inst.status == WorkflowInstance.IN_REVIEW
        boss = make_user('boss@x.com', superuser=True)
        WorkflowService.approve(inst, boss, 'step2')
        inst.refresh_from_db()
        assert inst.status == WorkflowInstance.APPROVED


class TestSegregationOfDuties:
    def test_initiator_cannot_approve(self, org, period, seeded):
        exc = _raise(org, period)
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        with pytest.raises(BusinessError, match='maker-checker'):
            WorkflowService.approve(inst, org['asm_user'], 'self')

    def test_non_assignee_cannot_approve(self, org, period, seeded):
        exc = _raise(org, period)
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        stranger = make_user('stranger@x.com')
        with pytest.raises(BusinessError, match='not an assigned approver'):
            WorkflowService.approve(inst, stranger, 'nope')


class TestDelegation:
    def test_delegate_can_act_for_assignee(self, org, period, seeded):
        exc = _raise(org, period)
        inst = WorkflowService.for_subject('incentives.PayoutException', exc.pk)
        delegate = make_user('deleg@x.com')
        today = date.today()
        ApprovalDelegation.objects.create(
            delegator=org['nsm_user'], delegate=delegate, scope='all',
            start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
        )
        WorkflowService.approve(inst, delegate, 'on behalf')
        exc.refresh_from_db()
        assert exc.status == PayoutException.APPROVED


class TestSLA:
    def _auto_approve_def(self):
        return WorkflowDefinition.objects.create(
            name='Auto', code='auto_sla', subject_type='incentives.PayoutException',
            steps=[{'order': 1, 'name': 'Review', 'assignee_rule': 'hierarchy_manager',
                    'hierarchy_levels_up': 1, 'approval_mode': 'single',
                    'sla_hours': 24, 'on_sla_breach': 'auto_approve'}],
            effective_from=date.today(),
        )

    def test_overdue_auto_approves(self, org, period):
        self._auto_approve_def()
        exc = make_exception(org['ase1'], period, actor=org['asm_user'])
        inst = WorkflowService.initiate(exc, 'auto_sla', initiated_by=org['asm_user'])
        # force the SLA into the past
        WorkflowStep.objects.filter(workflow=inst).update(sla_due_at=timezone.now() - timedelta(hours=1))
        WorkflowInstance.objects.filter(pk=inst.pk).update(sla_due_at=timezone.now() - timedelta(hours=1))
        escalated = WorkflowService.sweep_overdue()
        assert escalated == 1
        inst.refresh_from_db()
        exc.refresh_from_db()
        # Auto-approval is a distinct terminal status, but it still mirrors to the domain.
        assert inst.status == WorkflowInstance.AUTO_APPROVED
        assert exc.status == PayoutException.APPROVED


class TestBulkAndInbox:
    def test_bulk_approve(self, org, period, seeded):
        e1 = _raise(org, period)
        e2 = make_exception(org['ase2'], period, actor=org['asm_user'])
        WorkflowService.initiate(e2, 'payout_exception_standard', initiated_by=org['asm_user'])
        i1 = WorkflowService.for_subject('incentives.PayoutException', e1.pk)
        i2 = WorkflowService.for_subject('incentives.PayoutException', e2.pk)
        result = WorkflowService.bulk_act([i1.pk, i2.pk], org['nsm_user'], 'approve', 'batch')
        assert set(result['processed']) == {i1.pk, i2.pk}
        assert result['errors'] == []
        e1.refresh_from_db(); e2.refresh_from_db()
        assert e1.status == PayoutException.APPROVED
        assert e2.status == PayoutException.APPROVED

    def test_get_pending_scoped_to_assignee(self, org, period, seeded):
        _raise(org, period)
        assert WorkflowService.pending_count(org['nsm_user']) == 1
        stranger = make_user('stranger2@x.com')
        assert WorkflowService.pending_count(stranger) == 0
