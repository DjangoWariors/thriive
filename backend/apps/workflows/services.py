"""WorkflowService — the only layer that writes workflow state.

Lifecycle: ``initiate`` builds the (non-skipped) step chain and activates step 1.
``act`` records a human decision, enforces eligibility + segregation-of-duties, and
advances or finalizes. ``escalate`` applies an overdue step's SLA policy. On terminal
approve/reject the registered ``SubjectAdapter`` writes the decision back onto the domain
object (e.g. ``PayoutException.status``), keeping the domain its own source of truth.
"""
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.notifications.services import NotificationService

from . import adapters, routing
from .engine import evaluate_condition, sla_due_at, step_satisfied
from .models import (
    ApprovalDelegation, WorkflowAction, WorkflowDefinition, WorkflowInstance, WorkflowStep,
)


class WorkflowService:

    # ── definition lookup ────────────────────────────────────────────────────
    @staticmethod
    def current_definition(code: str) -> WorkflowDefinition:
        definition = (
            WorkflowDefinition.objects
            .filter(code=code, is_current=True, is_active=True)
            .order_by('-version').first()
        )
        if definition is None:
            raise BusinessError(f'No active workflow definition for "{code}".')
        return definition

    # ── initiation ───────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def initiate(subject, definition_code: str, initiated_by=None,
                 context_overrides: dict | None = None) -> WorkflowInstance:
        definition = WorkflowService.current_definition(definition_code)
        adapter = adapters.get(definition.subject_type)
        if adapter is None:
            raise BusinessError(f'No adapter registered for "{definition.subject_type}".')

        context = adapter.build_context(subject) or {}
        if context_overrides:
            context.update(context_overrides)
        anchor = adapter.anchor_entity(subject)

        instance = WorkflowInstance.objects.create(
            definition=definition,
            subject_type=definition.subject_type,
            subject_id=subject.pk,
            initiated_by=initiated_by,
            anchor_entity=anchor,
            current_step=1,
            status=WorkflowInstance.PENDING,
            context_data=context,
        )
        WorkflowAction.objects.create(
            workflow=instance, step_order=0, action_by=initiated_by,
            action=WorkflowAction.INITIATE, comments='',
        )

        # Build the chain from steps whose condition holds against the frozen context.
        order = 0
        chain: list[WorkflowStep] = []
        for cfg in sorted(definition.steps, key=lambda s: s.get('order', 0)):
            if not evaluate_condition(context, cfg.get('condition')):
                continue
            order += 1
            chain.append(WorkflowStep(
                workflow=instance, order=order, name=cfg.get('name', f'Step {order}'),
                approval_mode=cfg.get('approval_mode', 'single'),
                condition=cfg.get('condition'), config=cfg, status=WorkflowStep.PENDING,
            ))
        if not chain:
            # Nothing to approve → auto-approve immediately.
            WorkflowService._finalize(instance, None, approved=True, actor=initiated_by,
                                      auto=True)
            return instance

        WorkflowStep.objects.bulk_create(chain)
        first = instance.steps.order_by('order').first()
        WorkflowService._activate_step(first)
        AuditService.log('initiate', 'workflows.WorkflowInstance', instance.pk, initiated_by,
                         {'definition': definition.code, 'steps': order})
        return instance

    # ── acting ───────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def act(instance: WorkflowInstance, actor, action: str, comments: str = '') -> WorkflowInstance:
        instance = (
            WorkflowInstance.objects.select_for_update().get(pk=instance.pk)
        )
        if instance.status not in WorkflowInstance.OPEN_STATUSES:
            raise BusinessError(f'This request is already {instance.status}.')
        step = WorkflowService._active_step(instance)
        if step is None:
            raise BusinessError('There is no step awaiting a decision.')
        WorkflowService._check_eligibility(instance, step, actor)

        WorkflowAction.objects.create(
            workflow=instance, step=step, step_order=step.order,
            action_by=actor, action=action, comments=comments,
        )
        if action == WorkflowAction.REJECT:
            return WorkflowService._finalize(instance, step, approved=False, actor=actor,
                                             reason=comments)

        # Approve: tally distinct approvers on this step.
        approvals = (
            instance.actions
            .filter(step=step, action__in=(WorkflowAction.APPROVE, WorkflowAction.AUTO_APPROVE))
            .values('action_by').distinct().count()
        )
        outcome = step_satisfied(step.approval_mode, approvals, 0, len(step.assignee_user_ids or []))
        if outcome != 'approved':
            AuditService.log('approve_step', 'workflows.WorkflowInstance', instance.pk, actor,
                             {'step': step.order, 'partial': True})
            return instance
        return WorkflowService._advance(instance, step, actor)

    @staticmethod
    def approve(instance, actor, comments: str = '') -> WorkflowInstance:
        return WorkflowService.act(instance, actor, WorkflowAction.APPROVE, comments)

    @staticmethod
    def reject(instance, actor, reason: str) -> WorkflowInstance:
        if not (reason or '').strip():
            raise BusinessError('A reason is required to reject.')
        return WorkflowService.act(instance, actor, WorkflowAction.REJECT, reason)

    @staticmethod
    def bulk_act(instance_ids: list[int], actor, action: str, comments: str = '') -> dict:
        processed, errors = [], []
        for iid in instance_ids:
            try:
                with transaction.atomic():
                    inst = WorkflowInstance.objects.get(pk=iid)
                    WorkflowService.act(inst, actor, action, comments)
                processed.append(iid)
            except Exception as exc:  # noqa: BLE001 — collect per-item, never abort the batch
                errors.append({'id': iid, 'error': str(exc)})
        return {'processed': processed, 'errors': errors}

    # ── escalation (SLA) ─────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def escalate(instance: WorkflowInstance) -> WorkflowInstance:
        instance = WorkflowInstance.objects.select_for_update().get(pk=instance.pk)
        if instance.status not in WorkflowInstance.OPEN_STATUSES:
            return instance
        step = WorkflowService._active_step(instance)
        if step is None:
            return instance
        behaviour = (step.config or {}).get('on_sla_breach', 'escalate')

        if behaviour == 'auto_approve':
            WorkflowAction.objects.create(
                workflow=instance, step=step, step_order=step.order, action_by=None,
                action=WorkflowAction.AUTO_APPROVE, comments='SLA breached — auto-approved',
            )
            return WorkflowService._advance(instance, step, actor=None, auto=True)

        if behaviour == 'notify_only':
            for user in WorkflowService._step_users(step):
                NotificationService.send(user, 'workflow_reminder',
                                         WorkflowService._notify_ctx(instance, step))
            return instance

        # escalate → reassign one loginable level above the current assignee.
        now = timezone.now()
        above = routing.manager_at_level(step.assignee_entity or instance.anchor_entity, 1)
        WorkflowAction.objects.create(
            workflow=instance, step=step, step_order=step.order, action_by=None,
            action=WorkflowAction.ESCALATE, comments='SLA breached — escalated',
        )
        if above:
            step.assignee_user = above[0]
            step.assignee_user_ids = [u.pk for u in above]
            step.assignee_entity = getattr(above[0], 'entity', None)
        step.status = WorkflowStep.ESCALATED
        step.sla_due_at = sla_due_at(now, (step.config or {}).get('sla_hours'))
        step.save()
        instance.status = WorkflowInstance.ESCALATED
        instance.sla_due_at = step.sla_due_at
        instance.save(update_fields=['status', 'sla_due_at', 'updated_at'])
        for user in WorkflowService._step_users(step):
            NotificationService.send(user, 'workflow_escalated',
                                     WorkflowService._notify_ctx(instance, step))
        AuditService.log('escalate', 'workflows.WorkflowInstance', instance.pk, None,
                         {'step': step.order})
        return instance

    @staticmethod
    @transaction.atomic
    def cancel(instance: WorkflowInstance, actor=None, reason: str = '') -> WorkflowInstance:
        """Withdraw an open request (e.g. the maker withdrew). No domain callback fires."""
        instance = WorkflowInstance.objects.select_for_update().get(pk=instance.pk)
        if instance.status not in WorkflowInstance.OPEN_STATUSES:
            return instance
        now = timezone.now()
        instance.status = WorkflowInstance.CANCELLED
        instance.resolved_at = now
        instance.sla_due_at = None
        instance.save(update_fields=['status', 'resolved_at', 'sla_due_at', 'updated_at'])
        instance.steps.filter(
            status__in=(WorkflowStep.PENDING, WorkflowStep.ACTIVE, WorkflowStep.ESCALATED),
        ).update(status=WorkflowStep.SKIPPED, resolved_at=now)
        WorkflowAction.objects.create(
            workflow=instance, step_order=instance.current_step, action_by=actor,
            action=WorkflowAction.COMMENT, comments=reason or 'Cancelled',
        )
        AuditService.log('cancel', 'workflows.WorkflowInstance', instance.pk, actor, {})
        return instance

    @staticmethod
    def sweep_overdue() -> int:
        """Escalate every open instance whose active step is past its SLA. Returns count."""
        now = timezone.now()
        due = (
            WorkflowInstance.objects
            .filter(status__in=WorkflowInstance.OPEN_STATUSES, sla_due_at__lt=now)
            .values_list('pk', flat=True)
        )
        count = 0
        for pk in list(due):
            WorkflowService.escalate(WorkflowInstance.objects.get(pk=pk))
            count += 1
        return count

    # ── inbox ────────────────────────────────────────────────────────────────
    @staticmethod
    def get_pending(user):
        """Open instances whose active step ``user`` may action (assignee or active delegate)."""
        base = (
            WorkflowInstance.objects
            .filter(status__in=WorkflowInstance.OPEN_STATUSES)
            .prefetch_related('steps')
        )
        if getattr(user, 'is_superuser', False):
            ids = [i.pk for i in base if WorkflowService._active_step(i) is not None]
        else:
            eligible = {user.pk} | set(WorkflowService._delegators_for(user))
            ids = []
            for inst in base:
                step = WorkflowService._active_step(inst)
                if step and eligible & set(step.assignee_user_ids or []):
                    ids.append(inst.pk)
        return (
            WorkflowInstance.objects.filter(pk__in=ids)
            .select_related('definition', 'anchor_entity', 'initiated_by')
            .prefetch_related('steps')
            .order_by('sla_due_at', '-created_at')
        )

    @staticmethod
    def pending_count(user) -> int:
        return WorkflowService.get_pending(user).count()

    @staticmethod
    def for_subject(subject_type: str, subject_id: int) -> WorkflowInstance | None:
        """The live instance governing a domain object, if any."""
        return (
            WorkflowInstance.objects
            .filter(subject_type=subject_type, subject_id=subject_id)
            .order_by('-created_at').first()
        )

    # ── internals ────────────────────────────────────────────────────────────
    @staticmethod
    def _active_step(instance) -> WorkflowStep | None:
        return next(
            (s for s in instance.steps.all() if s.status in WorkflowStep.OPEN_STATUSES),
            None,
        )

    @staticmethod
    def _resolve_step_assignees(cfg: dict, instance) -> list:
        """Resolve a step's approvers, never assigning the request to its own raiser.

        For manager routing this climbs past the initiator (the common FMCG case: a manager
        raises on a subordinate's behalf, so the approval must go to *their* manager)."""
        anchor = instance.anchor_entity
        init_id = instance.initiated_by_id
        rule = cfg.get('assignee_rule', 'hierarchy_manager')
        if rule in ('hierarchy_manager', 'initiator_manager'):
            levels = int(cfg.get('hierarchy_levels_up', 1) or 1)
            chain = [u for u in routing.managers_up(anchor, levels + 6) if u.pk != init_id]
            if not chain:
                return []
            return [chain[min(levels, len(chain)) - 1]]
        users = routing.resolve_assignees(cfg, anchor)
        filtered = [u for u in users if u.pk != init_id]
        return filtered or users

    @staticmethod
    def _activate_step(step: WorkflowStep, notify: bool = True) -> None:
        cfg = step.config or {}
        users = WorkflowService._resolve_step_assignees(cfg, step.workflow)
        now = timezone.now()
        step.status = WorkflowStep.ACTIVE
        step.activated_at = now
        step.assignee_user_ids = [u.pk for u in users]
        step.assignee_user = users[0] if users else None
        step.assignee_role_code = cfg.get('role_code', '') or ''
        step.assignee_entity = getattr(users[0], 'entity', None) if users else None
        step.sla_due_at = sla_due_at(now, cfg.get('sla_hours'))
        step.save()

        inst = step.workflow
        inst.current_step = step.order
        inst.status = WorkflowInstance.IN_REVIEW
        inst.sla_due_at = step.sla_due_at
        inst.save(update_fields=['current_step', 'status', 'sla_due_at', 'updated_at'])
        if notify:
            for user in users:
                NotificationService.send(user, 'workflow_pending',
                                         WorkflowService._notify_ctx(inst, step))

    @staticmethod
    def _advance(instance, step, actor, auto: bool = False) -> WorkflowInstance:
        now = timezone.now()
        step.status = WorkflowStep.AUTO_APPROVED if auto else WorkflowStep.APPROVED
        step.resolved_at = now
        step.save(update_fields=['status', 'resolved_at', 'updated_at'])
        nxt = instance.steps.filter(
            order__gt=step.order, status=WorkflowStep.PENDING,
        ).order_by('order').first()
        if nxt is None:
            return WorkflowService._finalize(instance, step, approved=True, actor=actor, auto=auto)
        WorkflowService._activate_step(nxt)
        AuditService.log('approve_step', 'workflows.WorkflowInstance', instance.pk, actor,
                         {'step': step.order, 'auto': auto})
        return instance

    @staticmethod
    def _finalize(instance, step, approved: bool, actor, reason: str = '',
                  auto: bool = False) -> WorkflowInstance:
        now = timezone.now()
        if approved:
            instance.status = (
                WorkflowInstance.AUTO_APPROVED if auto else WorkflowInstance.APPROVED
            )
        else:
            instance.status = WorkflowInstance.REJECTED
            # remaining steps never run
            instance.steps.filter(status=WorkflowStep.PENDING).update(
                status=WorkflowStep.SKIPPED, resolved_at=now,
            )
        instance.resolved_at = now
        instance.sla_due_at = None
        instance.save(update_fields=['status', 'resolved_at', 'sla_due_at', 'updated_at'])

        adapter = adapters.get(instance.subject_type)
        subject = adapter.load(instance.subject_id) if adapter else None
        if adapter is not None and subject is not None:
            if approved:
                adapter.on_approved(instance, subject)
            else:
                adapter.on_rejected(instance, subject)
        AuditService.log('approve' if approved else 'reject',
                         'workflows.WorkflowInstance', instance.pk, actor,
                         {'reason': reason, 'auto': auto})
        if instance.initiated_by_id:
            NotificationService.send(
                instance.initiated_by, 'workflow_resolved',
                {**WorkflowService._notify_ctx(instance, step),
                 'outcome': instance.status},
            )
        return instance

    @staticmethod
    def _check_eligibility(instance, step, actor) -> None:
        if actor is None:
            raise BusinessError('An actor is required to act on a workflow.')
        # Segregation of duties: the raiser and any earlier-step approver cannot decide here.
        if instance.initiated_by_id and actor.pk == instance.initiated_by_id:
            raise BusinessError('You raised this request and cannot approve it (maker-checker).')
        prior_approvers = set(
            instance.actions
            .filter(action__in=(WorkflowAction.APPROVE, WorkflowAction.AUTO_APPROVE))
            .exclude(step=step)
            .values_list('action_by_id', flat=True)
        )
        if actor.pk in prior_approvers:
            raise BusinessError('You already approved an earlier step (segregation of duties).')
        if getattr(actor, 'is_superuser', False):
            return
        assignees = set(step.assignee_user_ids or [])
        if actor.pk in assignees:
            return
        if assignees & set(WorkflowService._delegators_for(actor)):
            return  # actor is an active delegate of an assignee
        raise BusinessError('You are not an assigned approver for this step.')

    @staticmethod
    def _delegators_for(user) -> list[int]:
        today = date.today()
        return list(
            ApprovalDelegation.objects
            .filter(delegate=user, is_active=True, start_date__lte=today, end_date__gte=today)
            .values_list('delegator_id', flat=True)
        )

    @staticmethod
    def _step_users(step):
        User = WorkflowStep._meta.get_field('assignee_user').related_model
        return User.objects.filter(pk__in=step.assignee_user_ids or [])

    @staticmethod
    def _notify_ctx(instance, step) -> dict:
        ctx = dict(instance.context_data or {})
        ctx.update({
            'workflow_id': instance.pk,
            'title': (instance.context_data or {}).get('title', 'Approval request'),
            'step_name': step.name if step else '',
            'link': '/workflows/pending',
        })
        return ctx
