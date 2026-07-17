"""ReviewService — the cascade review on a plan (docs/TARGET_MODULE_REVAMP_PLAN.md §6).

When a plan moves to ``in_review``, every territory at the plan's review levels gets one
``ReviewTask`` addressed to its owner (resolved through the Assignment bridge). Owners
accept or adjust their numbers; an adjustment goes through the same governed path as any
target edit (``TargetService.modify_allocation`` → RevisionPolicy band → within-cap
auto-approves, beyond-cap escalates to the editor's immediate manager via the
``target_revision`` workflow). This service only does the *bookkeeping* — who has
responded, and the HO gap board — the approval machinery is untouched.
"""
from django.db import transaction
from django.db.models import Case, Count, DecimalField, F, Sum, When
from django.utils import timezone

from apps.assignments.services import AssignmentService
from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode

from .models import ReviewTask, TargetAllocation, TargetPlan, TargetRevision
from .services import TargetService

_EFFECTIVE = Case(
    When(override_value__isnull=False, then=F('override_value')),
    default=F('target_value'),
    output_field=DecimalField(max_digits=18, decimal_places=4),
)

_TERMINAL = {ReviewTask.ACCEPTED, ReviewTask.ADJUSTED, ReviewTask.FORCE_CLOSED}

# A cascade is a managed negotiation, not a broadcast: pointed at a wide level (beats,
# outlets) it would open thousands of tasks + notifications nobody can shepherd.
_MAX_CASCADE_TASKS = 1000


class ReviewService:

    # ── cascade lifecycle ────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def open_cascade(plan: TargetPlan, actor=None) -> int:
        """One task per review-level territory, addressed to its current owner. Idempotent
        on (plan, node) — reopening tops up new territories without resetting responses."""
        if not plan.review_levels:
            return 0
        nodes = list(GeographyNode.objects.filter(
            path__startswith=plan.root_geography.path, is_active=True,
            level__in=plan.review_levels,
        ))
        if len(nodes) > _MAX_CASCADE_TASKS:
            raise BusinessError(
                f'Review level(s) {", ".join(plan.review_levels)} cover {len(nodes)} territories '
                f'under {plan.root_geography.name} — a cascade wider than {_MAX_CASCADE_TASKS} is '
                'unmanageable. Pick a higher geography level for the field review.')
        # One query for all owners — never owner_of per territory.
        owners = AssignmentService.owners_for_scopes(
            [n.id for n in nodes], on=timezone.localdate())
        created = 0
        for node in nodes:
            owner = owners.get(node.id)
            if owner is None:
                continue  # a task nobody can answer only wedges publish behind force-close
            _, was_created = ReviewTask.objects.get_or_create(
                plan=plan, node=node, defaults={'owner_node': owner},
            )
            created += int(was_created)
        if created:
            AuditService.log('create', 'targets.ReviewTask', plan.id, actor,
                             {'plan': plan.code, 'tasks_created': created})
            ReviewService.nudge(plan, actor=actor, only_new=True)
        return created

    @staticmethod
    @transaction.atomic
    def cancel_cascade(plan: TargetPlan, actor=None) -> int:
        """Plan pulled back to draft — the cascade restarts fresh next time."""
        count, _ = plan.review_tasks.all().delete()
        if count:
            AuditService.log('delete', 'targets.ReviewTask', plan.id, actor,
                             {'plan': plan.code, 'tasks_deleted': count})
        return count

    # ── owner responses ──────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def accept(task: ReviewTask, actor=None, notes: str = '') -> ReviewTask:
        ReviewService._assert_respondable(task, allowed={ReviewTask.PENDING})
        task.status = ReviewTask.ACCEPTED
        task.submitted_by = actor if getattr(actor, 'pk', None) else None
        task.submitted_at = timezone.now()
        task.notes = notes
        task.save(update_fields=['status', 'submitted_by', 'submitted_at', 'notes', 'updated_at'])
        AuditService.log('update', 'targets.ReviewTask', task.id, actor, {'status': 'accepted'})
        return task

    @staticmethod
    @transaction.atomic
    def adjust(task: ReviewTask, allocation: TargetAllocation, override_value, reason='',
               actor=None, rebalance=True) -> ReviewTask:
        """An owner adjusts a number inside their territory. The edit itself goes through
        the standard governed path; this only records the response: within-cap → adjusted,
        beyond-cap → escalated (until the manager decides — see resolve_escalation)."""
        # Re-adjusting (or adjusting after an accept) while the review is open is legitimate;
        # an ESCALATED task is parked with the manager and can't be touched until they decide.
        ReviewService._assert_respondable(
            task, allowed={ReviewTask.PENDING, ReviewTask.ADJUSTED, ReviewTask.ACCEPTED})
        if not allocation.geography_node.path.startswith(task.node.path):
            raise BusinessError('That allocation is outside this review territory.')
        TargetService.modify_allocation(
            allocation, override_value, reason=reason, actor=actor, rebalance=rebalance)
        revision = allocation.revisions.order_by('-created_at').first()
        escalated = revision is not None and revision.status == TargetRevision.PENDING
        task.status = ReviewTask.ESCALATED if escalated else ReviewTask.ADJUSTED
        task.submitted_by = actor if getattr(actor, 'pk', None) else None
        task.submitted_at = timezone.now()
        task.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        AuditService.log('update', 'targets.ReviewTask', task.id, actor,
                         {'status': task.status, 'allocation': allocation.id})
        return task

    @staticmethod
    def open_task_for(plan: TargetPlan, owner_node, allocation: TargetAllocation) -> ReviewTask:
        """The caller's respondable task containing this allocation — deepest match wins
        when review levels are nested. Raises if the allocation is outside every task."""
        tasks = ReviewTask.objects.filter(
            plan=plan, owner_node=owner_node,
            status__in=[ReviewTask.PENDING, ReviewTask.ADJUSTED, ReviewTask.ACCEPTED],
        ).select_related('node')
        containing = [t for t in tasks if allocation.geography_node.path.startswith(t.node.path)]
        if not containing:
            raise BusinessError('That territory is not in your open review tasks.')
        return max(containing, key=lambda t: t.node.depth)

    @staticmethod
    def resolve_escalation(allocation: TargetAllocation, approved: bool) -> None:
        """Called by the target_revision workflow adapter when a manager decides an
        escalated edit: approved → the response stands (adjusted); rejected → the task
        reopens so the owner can try again or accept."""
        if allocation.plan_id is None:
            return
        tasks = ReviewTask.objects.filter(
            plan_id=allocation.plan_id, status=ReviewTask.ESCALATED).select_related('node')
        # With nested review levels several escalated tasks can contain the allocation;
        # only the deepest (the one whose owner actually made the edit) is resolved.
        containing = [t for t in tasks if allocation.geography_node.path.startswith(t.node.path)]
        if not containing:
            return
        task = max(containing, key=lambda t: t.node.depth)
        task.status = ReviewTask.ADJUSTED if approved else ReviewTask.PENDING
        task.save(update_fields=['status', 'updated_at'])

    # ── HO controls ──────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def force_close(plan: TargetPlan, actor=None, reason: str = '') -> int:
        """Close every open task so the plan can publish — an explicit, audited HO act."""
        if not (reason or '').strip():
            raise BusinessError('Force-closing the review needs a reason.')
        open_tasks = plan.review_tasks.filter(status__in=[ReviewTask.PENDING, ReviewTask.ESCALATED])
        count = open_tasks.update(status=ReviewTask.FORCE_CLOSED, submitted_at=timezone.now())
        AuditService.log('update', 'targets.ReviewTask', plan.id, actor,
                         {'plan': plan.code, 'force_closed': count, 'reason': reason})
        return count

    @staticmethod
    def nudge(plan: TargetPlan, actor=None, only_new: bool = False) -> int:
        """In-app reminder to every owner with an open task (best-effort: silently no-op
        for unowned territories, owners without users, or a missing template)."""
        from apps.notifications.services import NotificationService
        tasks = plan.review_tasks.filter(status=ReviewTask.PENDING).select_related('owner_node')
        sent = 0
        for task in tasks:
            user = getattr(task.owner_node, 'user', None) if task.owner_node else None
            if user is None:
                continue
            if NotificationService.send(user, 'target_review_pending', {
                'plan_name': plan.name, 'territory': task.node.name,
            }) is not None:
                sent += 1
        if sent and not only_new:
            AuditService.log('update', 'targets.TargetPlan', plan.id, actor, {'nudged': sent})
        return sent

    # ── gap board ────────────────────────────────────────────────────────────
    @staticmethod
    def gap_board(plan: TargetPlan, top_n: int = 10) -> dict:
        """The HO view of the cascade: response progress per level, and top-down vs
        bottom-up per KPI (original committed numbers vs current effective numbers,
        adjustments included) with the biggest movers."""
        tasks = list(plan.review_tasks.select_related('node', 'owner_node'))
        by_level: dict = {}
        for task in tasks:
            bucket = by_level.setdefault(task.node.level, {s: 0 for s, _ in ReviewTask.STATUS_CHOICES})
            bucket[task.status] += 1

        review_node_ids = [t.node_id for t in tasks]
        kpi_rows = (
            TargetAllocation.objects.filter(
                plan=plan, target_period=plan.period, sku_group=None,
                geography_node_id__in=review_node_ids,
            )
            .values('kpi__code')
            .annotate(top_down=Sum('original_target_value'), bottom_up=Sum(_EFFECTIVE))
        )
        movers = (
            TargetAllocation.objects.filter(
                plan=plan, target_period=plan.period, sku_group=None, is_modified=True,
                geography_node_id__in=review_node_ids,
            )
            .annotate(effective=_EFFECTIVE)
            .select_related('geography_node', 'kpi')
        )
        deltas = sorted(
            ({'geography_node': m.geography_node.code, 'kpi': m.kpi.code,
              'top_down': str(m.original_target_value), 'current': str(m.effective),
              'delta': str(m.effective - m.original_target_value)} for m in movers),
            key=lambda d: abs(float(d['delta'])), reverse=True,
        )
        open_count = sum(1 for t in tasks if t.status not in _TERMINAL)
        return {
            'plan': plan.code, 'status': plan.status,
            'tasks_total': len(tasks), 'tasks_open': open_count,
            'by_level': by_level,
            'kpis': [{'kpi': r['kpi__code'],
                      'top_down': str(r['top_down'] or 0),
                      'bottom_up': str(r['bottom_up'] or 0),
                      'gap': str((r['bottom_up'] or 0) - (r['top_down'] or 0))} for r in kpi_rows],
            'top_movers': deltas[:top_n],
        }

    @staticmethod
    def open_task_count(plan: TargetPlan) -> int:
        return plan.review_tasks.filter(
            status__in=[ReviewTask.PENDING, ReviewTask.ESCALATED]).count()

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _assert_respondable(task: ReviewTask, allowed: set):
        if task.plan.status != TargetPlan.IN_REVIEW:
            raise BusinessError('The review is not open on this plan.')
        if task.status not in allowed:
            if task.status == ReviewTask.FORCE_CLOSED:
                raise BusinessError('This review task was closed by an administrator.')
            if task.status == ReviewTask.ESCALATED:
                raise BusinessError('This task is with your manager for a decision — wait for it.')
            raise BusinessError(f'This task has already been {task.status} and cannot be re-answered.')
