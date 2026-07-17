"""TargetService — all business logic + DB writes for the targets app.

The only layer that writes TargetPeriod / TargetAllocation / config models. Planning itself
(baseline → top-down → split → product mix) is plan-run based (see plan_services.py); what
lives here is the durable core: the planning calendar (targets are always set monthly),
derived person targets (the Assignment-bridge rollup), override governance (change caps +
maker-checker), approvals, and bulk import.
"""
import bisect
import calendar
import csv
import io
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.utils import timezone

from apps.assignments.services import AssignmentService
from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Channel, GeographyNode
from apps.kpi_engine.models import KPIDefinition
from apps.master_data.models import SKUGroup

from . import disaggregator
from .models import (
    RevisionPolicy,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
)

_EDITABLE_PERIOD_STATES = {TargetPeriod.DRAFT, TargetPeriod.PUBLISHED}


def _to_decimal(value, field='value'):
    raw = str(value).strip()
    if raw == '':
        return Decimal('0')
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        raise BusinessError(f'Invalid {field}: "{value}"')


class TargetService:

    # ── period lifecycle ────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def create_period(data: dict, actor=None) -> TargetPeriod:
        if TargetPeriod.objects.filter(code=data.get('code')).exists():
            raise BusinessError(f'A period with code "{data.get("code")}" already exists.')
        period = TargetPeriod.objects.create(**data)
        AuditService.log('create', 'targets.TargetPeriod', period.id, actor,
                         {'code': period.code, 'type': period.period_type})
        return period

    @staticmethod
    @transaction.atomic
    def generate_fiscal_year(fiscal_year: str, start_month: int = 4, *, channel=None,
                             working_days_per_month=26, actor=None) -> TargetPeriod:
        """Create a whole plan year in one go: the annual container period owning its 12
        months. Targets are always set monthly — the annual period never carries targets;
        it exists to group the months and to anchor annual SIP payout runs. Idempotent on
        period code, so re-running tops up anything missing without duplicating.
        ``start_month`` is the fiscal-year start (4 = April, the India FMCG default;
        1 = calendar year). Returns the annual root period.
        """
        fiscal_year = (fiscal_year or '').strip()
        if not fiscal_year:
            raise BusinessError('A fiscal year (e.g. "2026-27") is required.')
        if start_month not in range(1, 13):
            raise BusinessError('start_month must be between 1 and 12.')
        try:
            start_year = int(fiscal_year[:4])
        except ValueError:
            raise BusinessError(f'Could not read a start year from "{fiscal_year}". Use a form like "2026-27".')

        # 12 consecutive (year, month) pairs from the fiscal start.
        months = []
        y, m = start_year, start_month
        for _ in range(12):
            months.append((y, m))
            m = 1 if m == 12 else m + 1
            y = y + 1 if m == 1 else y

        annual_code = f'FY{start_year}'
        annual = TargetService._upsert_period(
            code=annual_code, name=f'FY {fiscal_year} (Annual)', ptype=TargetPeriod.ANNUAL,
            start=date(*months[0], 1), end=TargetService._month_end(*months[-1]),
            parent=None, fiscal_year=fiscal_year, channel=channel,
        )
        created = 1 if annual._was_created else 0
        for my, mm in months:
            month = TargetService._upsert_period(
                code=f'{annual_code}-M{mm:02d}', name=f'{calendar.month_abbr[mm]} {my}',
                ptype=TargetPeriod.MONTHLY, start=date(my, mm, 1), end=TargetService._month_end(my, mm),
                parent=annual, fiscal_year=fiscal_year, channel=channel,
                working_days=working_days_per_month,
            )
            created += month._was_created
        AuditService.log('create', 'targets.TargetPeriod', annual.id, actor,
                         {'fiscal_year': fiscal_year, 'start_month': start_month, 'periods_created': created})
        return annual

    @staticmethod
    def _month_end(year, month):
        return date(year, month, calendar.monthrange(year, month)[1])

    @staticmethod
    def _upsert_period(code, name, ptype, start, end, parent, fiscal_year, channel=None, working_days=None):
        period, was_created = TargetPeriod.objects.get_or_create(
            code=code,
            defaults={'name': name, 'fiscal_year': fiscal_year, 'period_type': ptype,
                      'start_date': start, 'end_date': end, 'parent': parent,
                      'channel': channel, 'working_days': working_days},
        )
        period._was_created = was_created
        return period

    @staticmethod
    @transaction.atomic
    def advance_period(period: TargetPeriod, new_status: str, actor=None,
                       source: str = '') -> TargetPeriod:
        """Period status is derived, never hand-set: a plan publishing marks its month
        published, the payout cycle finalizing locks it (freezing every allocation), and
        the cycle closing closes it. Forward-only and idempotent — the driving events can
        repeat or skip states (a cycle may finalize a month no plan ever published)."""
        order = [TargetPeriod.DRAFT, TargetPeriod.PUBLISHED, TargetPeriod.LOCKED, TargetPeriod.CLOSED]
        if order.index(new_status) <= order.index(period.status):
            return period
        old = period.status
        period.status = new_status
        period.save(update_fields=['status', 'updated_at'])
        if new_status == TargetPeriod.LOCKED:
            TargetService._void_pending_revisions(period, actor)
            period.allocations.update(status=TargetAllocation.LOCKED)
        AuditService.log('update', 'targets.TargetPeriod', period.id, actor,
                         {'status': {'from': old, 'to': new_status}, 'driven_by': source})
        return period

    @staticmethod
    def _void_pending_revisions(period, actor=None):
        """Locking freezes the base exactly as computed and paid — in-flight escalations are
        void. Values stay untouched (the optimistic override is already in the frozen numbers);
        only the open approvals close, so a late decision can't move a paid month."""
        from apps.workflows.models import WorkflowInstance
        from apps.workflows.services import WorkflowService
        pending = TargetRevision.objects.filter(
            allocation__target_period=period, status=TargetRevision.PENDING)
        ids = list(pending.values_list('id', flat=True))
        if not ids:
            return
        pending.update(status=TargetRevision.REJECTED, approved_at=timezone.now(),
                       reason=Concat('reason', Value(' | cancelled: period locked by payout cycle')))
        for inst in WorkflowInstance.objects.filter(
                subject_type='targets.TargetRevision', subject_id__in=ids,
                status__in=WorkflowInstance.OPEN_STATUSES):
            WorkflowService.cancel(inst, actor=actor, reason='Period locked by the payout cycle.')
        AuditService.log('update', 'targets.TargetPeriod', period.id, actor,
                         {'revisions_voided_on_lock': len(ids)})

    # ── person-derived target view (the bridge to org entities) ─────────────
    @staticmethod
    def derive_entity_targets(period, kpi, entity_ids, *, on=None, channel=None, sku_group=None,
                              live_only=True) -> dict:
        """A person's target = sum of ``effective_target`` over the geography nodes they directly
        own as-of the period. Targets are stored only on geography; the per-entity number is
        derived here (never a stored column), which keeps target and actual on the same axis.

        Sums the *directly-owned* node's own allocation — disaggregation already makes a parent's
        target equal the sum of its descendants, so summing owned nodes (not their subtrees) avoids
        double counting. When an owned node has no direct allocation (e.g. leaf-only bulk import),
        falls back to the top-most allocations in its subtree.

        ``live_only`` keeps draft/in-review plan numbers out of the rollup (achievements,
        dashboards, portals); the plan workspace passes False to preview its own draft.
        """
        on = on or period.end_date
        entity_ids = list(entity_ids)
        if not entity_ids:
            return {}
        owned = {eid: AssignmentService.owned_scope_ids_for_entity(eid, on=on) for eid in entity_ids}
        all_scope_ids = {nid for ids in owned.values() for nid in ids}
        if not all_scope_ids:
            return {eid: Decimal('0') for eid in entity_ids}

        base = TargetAllocation.objects.live() if live_only else TargetAllocation.objects.filter(is_active=True)
        allocs = {
            a.geography_node_id: a.effective_target
            for a in base.filter(
                target_period=period, kpi=kpi, channel=channel, sku_group=sku_group,
                geography_node_id__in=all_scope_ids,
            )
        }
        missing = [nid for nid in all_scope_ids if nid not in allocs]
        fallback = TargetService._subtree_allocation_rollup(
            period, kpi, missing, channel, sku_group, live_only=live_only)

        result = {}
        for eid in entity_ids:
            total = Decimal('0')
            for nid in owned[eid]:
                if nid in allocs:
                    total += allocs[nid]
                elif nid in fallback:
                    total += fallback[nid]
            result[eid] = total
        return result

    @staticmethod
    def _subtree_allocation_rollup(period, kpi, node_ids, channel, sku_group, live_only=True) -> dict:
        """For each node with no own allocation, sum the *top-most* descendant allocations (skip a
        row whose ancestor also carries one) so nested allocations aren't double-counted.

        One query for the whole batch: the nightly person pass resolves thousands of owned
        nodes at once, so this must never be a query per node. Rows are path-sorted; each
        node's subtree is a contiguous slice found by bisect."""
        if not node_ids:
            return {}
        nodes = list(GeographyNode.objects.filter(pk__in=node_ids, is_active=True).values('id', 'path'))
        base = TargetAllocation.objects.live() if live_only else TargetAllocation.objects.filter(is_active=True)
        rows = sorted(base.filter(
            target_period=period, kpi=kpi, channel=channel, sku_group=sku_group,
        ).values_list('geography_node__path', 'override_value', 'target_value'))
        paths = [r[0] for r in rows]
        result = {}
        for n in nodes:
            lo = bisect.bisect_left(paths, n['path'])
            hi = bisect.bisect_left(paths, n['path'] + '￿')
            kept, total = None, Decimal('0')
            for path, override, target in rows[lo:hi]:
                # Path order puts an ancestor right before its descendants, so one
                # remembered prefix is enough to skip a kept ancestor's whole subtree.
                if kept and path.startswith(kept):
                    continue
                kept = path
                total += override if override is not None else target
            result[n['id']] = total
        return result

    @staticmethod
    def get_person_view(period, kpi, entity, *, on=None, channel=None, sku_group=None,
                        live_only=True) -> dict:
        """A person's target broken down by the retailers/territories they own — the
        "Target processing (User × Retailer × SKU)" view. ``target`` is the derived rollup;
        ``rows`` are the underlying geography allocations that make it up."""
        on = on or period.end_date
        scope_ids = AssignmentService.owned_scope_ids_for_entity(entity.id, on=on)
        base = TargetAllocation.objects.live() if live_only else TargetAllocation.objects.filter(is_active=True)
        qs = base.filter(
            target_period=period, kpi=kpi, geography_node_id__in=scope_ids,
        ).select_related('geography_node', 'channel', 'sku_group')
        if channel is not None:
            qs = qs.filter(channel=channel)
        if sku_group is not None:
            qs = qs.filter(sku_group=sku_group)
        rows = [{
            'allocation_id': a.id,
            'geography_node_id': a.geography_node_id,
            'geography_node': a.geography_node.name if a.geography_node else None,
            'geography_code': a.geography_node.code if a.geography_node else None,
            'channel': a.channel.code if a.channel else None,
            'sku_group': a.sku_group.code if a.sku_group else None,
            'target': str(a.effective_target),
            'status': a.status,
        } for a in qs]
        derived = TargetService.derive_entity_targets(
            period, kpi, [entity.id], on=on, channel=channel, sku_group=sku_group, live_only=live_only)
        return {
            'entity_id': entity.id, 'entity': entity.name, 'entity_code': entity.code,
            'owned_node_count': len(scope_ids),
            'target': str(derived.get(entity.id, Decimal('0'))),
            'rows': rows,
        }

    # ── manual override + sibling rebalance ─────────────────────────────────
    @staticmethod
    @transaction.atomic
    def modify_allocation(allocation, override_value, reason='', actor=None, rebalance=True) -> TargetAllocation:
        # Serialize concurrent edits: two sibling overrides racing would each rebalance
        # against the other's stale value and break the parent-sum invariant.
        allocation = TargetAllocation.objects.select_for_update().get(pk=allocation.pk)
        TargetService._assert_editable(allocation.target_period)
        if allocation.status == TargetAllocation.LOCKED:
            raise BusinessError('This target is locked and cannot be changed.')
        old = allocation.effective_target
        new = Decimal(str(override_value))
        if new < 0:
            raise BusinessError('A target cannot be negative.')

        # A placed persona may only change targets inside the territories they cover —
        # enforced here (not just in the territory-scoped viewsets) so every caller,
        # present and future, carries the same boundary.
        actor_entity = getattr(actor, 'entity', None)
        if actor_entity is not None and not AssignmentService.entity_covers_node(
                actor_entity.pk, allocation.geography_node):
            raise BusinessError('That territory is outside your area.')

        mode = TargetService._governance_mode(allocation)
        if mode == TargetService.FREE and actor_entity is not None:
            raise BusinessError(
                'Draft plans are set by the planning team — you can adjust once the plan '
                'is in review.')
        # A plan's numbers are only field-editable during its review window. Once
        # published they are read-only for placed users — post-publish corrections are
        # raised by HO (still governed by change caps / maker-checker below).
        if (actor_entity is not None and allocation.plan_id is not None
                and allocation.plan.status != TargetPlan.IN_REVIEW):
            raise BusinessError(
                'This plan is published — its numbers are read-only for field users. '
                'Ask the planning team to raise the change.')
        policy = TargetService._resolve_revision_policy(allocation) if mode != TargetService.FREE else None
        if policy and policy.requires_reason and not (reason or '').strip():
            raise BusinessError('A reason is required to revise this target.')

        raw_pct = TargetService._pct(allocation.original_target_value or old, new)
        if policy is not None:
            band = TargetService._check_policy(allocation, new, policy, raw_pct)  # may raise
        elif mode == TargetService.PUBLISHED_MODE:
            band = TargetRevision.ESCALATE  # default maker-checker: published edits need approval
        else:
            band = TargetRevision.AUTO  # draft sandbox, or an uncapped review cascade

        approved = band == TargetRevision.AUTO
        allocation.override_value = new
        allocation.is_modified = True
        allocation.modification_reason = reason
        allocation.source = TargetAllocation.MANUAL
        allocation.status = TargetAllocation.APPROVED if approved else TargetAllocation.PENDING
        allocation.save(update_fields=['override_value', 'is_modified', 'modification_reason',
                                       'source', 'status', 'updated_at'])

        revision = TargetRevision.objects.create(
            allocation=allocation, old_value=old, new_value=new, delta=new - old,
            delta_pct=raw_pct if raw_pct is not None else Decimal('0'),
            reason=reason, source=TargetRevision.MANUAL, band=band, requested_by=actor,
            status=TargetRevision.APPROVED if approved else TargetRevision.PENDING,
            approved_by=actor if approved else None,
            approved_at=timezone.now() if approved else None,
        )
        if rebalance:
            # After the revision so side-effect rows can link back to it — a rejection
            # must revert the rebalanced siblings too, not just the edited node.
            TargetService._rebalance_siblings(allocation, old, new, actor, triggered_by=revision)
        AuditService.log('update', 'targets.TargetAllocation', allocation.id, actor,
                         {'override': {'from': str(old), 'to': str(new)}, 'reason': reason,
                          'band': band, 'delta_pct': str(raw_pct) if raw_pct is not None else None})
        if not approved:
            TargetService._route_escalation(revision, actor)
        return allocation

    # An edit under a very wide parent (an outlet level can have thousands of siblings)
    # must not lock and rewrite them all in one transaction — above this, edit without
    # rebalance and re-split the level with a plan run instead.
    _MAX_REBALANCE_SIBLINGS = 200

    @staticmethod
    def _rebalance_siblings(allocation, old, new, actor, triggered_by=None):
        """Keep the parent's total unchanged by absorbing the delta across geography siblings."""
        node = allocation.geography_node
        if node is None or node.parent_id is None:
            return
        # PENDING siblings are excluded like LOCKED ones: their value is an optimistic
        # override awaiting a checker — overwriting it would be clobbered (and the parent
        # sum broken) the moment that escalation is rejected and reverts to its old value.
        pool = TargetAllocation.objects.filter(
            target_period=allocation.target_period, kpi=allocation.kpi,
            channel=allocation.channel, sku_group=allocation.sku_group,
            geography_node__parent_id=node.parent_id,
        ).exclude(pk=allocation.pk).exclude(
            status__in=(TargetAllocation.LOCKED, TargetAllocation.PENDING))
        pool_size = pool.count()
        if pool_size > TargetService._MAX_REBALANCE_SIBLINGS:
            raise BusinessError(
                f'This territory has {pool_size} siblings — automatic rebalance is capped at '
                f'{TargetService._MAX_REBALANCE_SIBLINGS}. Save without rebalance, or re-split '
                'the level with a plan run.')
        siblings = list(pool.select_related('geography_node').select_for_update(of=('self',)))
        if not siblings:
            return
        # A placed persona's rebalance must not rewrite territories outside their area
        # (a peer's — possibly already accepted — number). Refuse loudly rather than
        # skip silently; the edit itself can be saved without rebalance.
        actor_entity = getattr(actor, 'entity', None)
        if actor_entity is not None:
            scope_paths = AssignmentService.scope_paths_for_entity(actor_entity.pk)
            if any(not any(s.geography_node.path.startswith(p) for p in scope_paths)
                   for s in siblings):
                raise BusinessError(
                    'Rebalancing would touch territories outside your area — save without '
                    'rebalance instead.')
        sibling_total = sum((s.effective_target for s in siblings), Decimal('0'))
        new_total = sibling_total - (new - old)
        if new_total < 0:
            raise BusinessError('That target is too high — siblings cannot absorb the difference.')
        # Quantize to the column scale (numeric 18,4): unquantized shares would be rounded
        # independently by the DB on save, silently drifting the parent total by dust.
        split = disaggregator.split_by_weights(
            new_total, [(s.id, s.effective_target) for s in siblings], unit='0.0001',
        )
        by_id = {s.id: s for s in siblings}
        for sid, value in split.items():
            sib = by_id[sid]
            sib_old = sib.effective_target
            if value == sib_old:
                continue
            sib.override_value = value
            sib.is_modified = True
            sib.modification_reason = 'Auto-rebalanced after a sibling edit'
            sib.save(update_fields=['override_value', 'is_modified', 'modification_reason', 'updated_at'])
            TargetRevision.objects.create(
                allocation=sib, old_value=sib_old, new_value=value, delta=value - sib_old,
                delta_pct=TargetService._pct(sib.original_target_value or sib_old, value) or Decimal('0'),
                reason='Auto-rebalanced after a sibling edit', source=TargetRevision.REBALANCE,
                band=TargetRevision.AUTO, requested_by=actor, status=TargetRevision.APPROVED,
                approved_by=actor, approved_at=timezone.now(), triggered_by=triggered_by,
            )

    # ── revision governance (the FMCG "change cap") ─────────────────────────
    FREE, REVIEW, PUBLISHED_MODE = 'free', 'review', 'published'

    @staticmethod
    def _governance_mode(allocation) -> str:
        """How edits to this allocation are governed. The plan — not the period — carries the
        planning lifecycle.

        free      → draft planning sandbox: everything auto-approves.
        review    → cascade negotiation: a RevisionPolicy cap applies if configured,
                    otherwise owners adjust freely.
        published → live numbers: policy cap applies, and with no policy every edit
                    needs approval (default maker-checker).

        Plan-less rows (bulk imports) are live downstream from the moment they exist
        (``TargetAllocation.live()``), so they are always in published mode — a draft
        month must never disable maker-checker.
        """
        if allocation.plan_id is not None:
            if allocation.plan.status == TargetPlan.IN_REVIEW:
                return TargetService.REVIEW
            if allocation.plan.status in (TargetPlan.PUBLISHED, TargetPlan.LOCKED, TargetPlan.CLOSED):
                return TargetService.PUBLISHED_MODE
            return TargetService.FREE
        return TargetService.PUBLISHED_MODE

    @staticmethod
    def _pct(base, new) -> Decimal | None:
        """Absolute % change of ``new`` vs ``base``. None when base is 0 (undefined)."""
        base = Decimal(str(base or 0))
        if base == 0:
            return None
        return (abs(Decimal(str(new)) - base) / abs(base) * Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def _resolve_revision_policy(allocation):
        """Most-specific current policy for this allocation, or None (→ default behaviour).

        Targets are geography-anchored, so the ``entity_type`` policy dimension no longer applies;
        only period- and channel-scoped policies match (entity-type-scoped policies never do)."""
        candidates = RevisionPolicy.objects.filter(is_current=True, is_active=True, entity_type__isnull=True).filter(
            Q(target_period__isnull=True) | Q(target_period_id=allocation.target_period_id),
            Q(channel__isnull=True) | Q(channel_id=allocation.channel_id),
        )
        best, best_score = None, -1
        for p in candidates:
            score = (4 if p.target_period_id else 0) + (2 if p.channel_id else 0)
            # Tie-break must be deterministic across DB return order: code, then version.
            if score > best_score or (score == best_score and best is not None
                                      and (p.code, p.version) > (best.code, best.version)):
                best, best_score = p, score
        return best

    @staticmethod
    def _check_policy(allocation, new, policy, raw_pct) -> str:
        """Apply a matched policy. Returns the band ('auto'/'escalate'); raises if blocked."""
        if policy.freeze_after and timezone.localdate() > policy.freeze_after:
            raise BusinessError(f'Targets for this period are frozen — no changes after {policy.freeze_after}.')
        if policy.max_revisions_per_period is not None:
            used = TargetRevision.objects.filter(allocation=allocation, source=TargetRevision.MANUAL).count()
            if used >= policy.max_revisions_per_period:
                raise BusinessError(
                    f'This target has reached its revision limit of {policy.max_revisions_per_period}.')
        if raw_pct is None:  # 0 → X: magnitude undefined, always needs approval (never auto, never blocked)
            return TargetRevision.ESCALATE
        if policy.hard_ceiling_pct is not None and raw_pct > policy.hard_ceiling_pct:
            raise BusinessError(
                f'A change of {raw_pct}% exceeds the {policy.hard_ceiling_pct}% ceiling for this target.')
        if raw_pct <= policy.auto_approve_within_pct:
            return TargetRevision.AUTO
        return TargetRevision.ESCALATE

    @staticmethod
    def preflight_revision(allocation, new) -> dict:
        """Tell the UI what a proposed change would do, without applying it."""
        new = Decimal(str(new))
        mode = TargetService._governance_mode(allocation)
        policy = TargetService._resolve_revision_policy(allocation) if mode != TargetService.FREE else None
        raw_pct = TargetService._pct(allocation.original_target_value or allocation.effective_target, new)
        out = {'delta_pct': str(raw_pct) if raw_pct is not None else None,
               'policy_code': policy.code if policy else None,
               'requires_reason': bool(policy.requires_reason) if policy else False}
        if policy is not None:
            try:
                out['outcome'] = TargetService._check_policy(allocation, new, policy, raw_pct)
            except BusinessError as exc:
                out['outcome'] = 'blocked'
                out['message'] = str(exc)
        else:
            out['outcome'] = (TargetRevision.ESCALATE if mode == TargetService.PUBLISHED_MODE
                              else TargetRevision.AUTO)
        return out

    @staticmethod
    def _route_escalation(revision, actor):
        """Route an escalated target revision to the editor's immediate manager for approval.

        Opt-in by configuration: with no ``target_revision`` workflow definition (or no actor to
        route from), the revision is simply left PENDING for manual approval — the platform's
        default maker-checker. When a definition exists, the approval follows the editor's org
        reporting line (``Entity.parent``) even though the target itself is geography-anchored.
        """
        if actor is None:
            return
        from apps.targets.adapters import TARGET_REVISION_WF
        from apps.workflows import routing
        from apps.workflows.models import WorkflowDefinition
        from apps.workflows.services import WorkflowService
        if not WorkflowDefinition.objects.filter(
                code=TARGET_REVISION_WF, is_current=True, is_active=True).exists():
            return
        # No reachable manager (unplaced editor, or top of the tree) must NOT initiate:
        # an empty approval chain auto-approves — a beyond-cap edit confirmed with no
        # checker. Falling back keeps the revision PENDING for the manual approve queue.
        anchor = getattr(actor, 'entity', None)
        if not [u for u in routing.managers_up(anchor, 7) if u.pk != actor.pk]:
            AuditService.log('update', 'targets.TargetRevision', revision.id, actor,
                             {'escalation': 'no approver reachable — left pending for manual review'})
            return
        WorkflowService.initiate(revision, TARGET_REVISION_WF, initiated_by=actor)

    # ── approvals ───────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def approve_allocation(allocation, actor=None) -> TargetAllocation:
        allocation.status = TargetAllocation.APPROVED
        allocation.save(update_fields=['status', 'updated_at'])
        TargetRevision.objects.filter(allocation=allocation, status=TargetRevision.PENDING).update(
            status=TargetRevision.APPROVED, approved_by=actor, approved_at=timezone.now())
        AuditService.log('update', 'targets.TargetAllocation', allocation.id, actor, {'status': 'approved'})
        return allocation

    @staticmethod
    @transaction.atomic
    def reject_allocation(allocation, actor=None, reason='') -> TargetAllocation:
        """Reject the latest pending revision and roll the target back to its pre-change value."""
        rev = TargetRevision.objects.filter(
            allocation=allocation, status=TargetRevision.PENDING).order_by('-created_at').first()
        if rev is None:
            raise BusinessError('There is no pending revision to reject.')
        allocation.override_value = None if rev.old_value == allocation.target_value else rev.old_value
        allocation.is_modified = allocation.override_value is not None
        allocation.status = TargetAllocation.APPROVED
        allocation.save(update_fields=['override_value', 'is_modified', 'status', 'updated_at'])
        rev.status = TargetRevision.REJECTED
        rev.reason = (rev.reason + f' | rejected: {reason}').strip(' |') if reason else rev.reason
        rev.approved_by = actor
        rev.approved_at = timezone.now()
        rev.save(update_fields=['status', 'reason', 'approved_by', 'approved_at', 'updated_at'])
        TargetService._revert_side_effects(rev, actor)
        AuditService.log('update', 'targets.TargetAllocation', allocation.id, actor,
                         {'status': 'rejected', 'reverted_to': str(rev.old_value)})
        return allocation

    @staticmethod
    def _revert_side_effects(revision, actor=None):
        """A rejected edit takes its auto-rebalanced siblings with it — otherwise the parent
        total stays broken and peers keep numbers they never agreed to."""
        for side in revision.side_effects.filter(
                status=TargetRevision.APPROVED).select_related('allocation'):
            alloc = side.allocation
            if alloc.status == TargetAllocation.LOCKED:
                continue  # frozen by the payout cycle — the paid base must not move
            alloc.override_value = None if side.old_value == alloc.target_value else side.old_value
            alloc.is_modified = alloc.override_value is not None
            alloc.save(update_fields=['override_value', 'is_modified', 'updated_at'])
            side.status = TargetRevision.REJECTED
            side.approved_by = actor
            side.approved_at = timezone.now()
            side.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def approve_all_pending(period, scope_entity=None, actor=None) -> dict:
        qs = TargetAllocation.objects.filter(target_period=period, status=TargetAllocation.PENDING)
        if scope_entity is not None:
            # Targets are geography-anchored; a manager approves within the territories they own.
            node_ids = AssignmentService.scope_node_ids_for_entity(scope_entity.id)
            qs = qs.filter(geography_node_id__in=node_ids)
        ids = list(qs.values_list('id', flat=True))
        count = qs.update(status=TargetAllocation.APPROVED)
        TargetRevision.objects.filter(allocation_id__in=ids, status=TargetRevision.PENDING).update(
            status=TargetRevision.APPROVED, approved_by=actor, approved_at=timezone.now())
        AuditService.log('update', 'targets.TargetPeriod', period.id, actor, {'approved_pending': count})
        return {'approved': count}

    # ── bulk import ─────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def bulk_import_allocations(csv_text: str, actor=None) -> dict:
        """Idempotent upsert of allocations from CSV. All-or-nothing validation."""
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise BusinessError('CSV is empty or has no header row.')
        header = {h.strip() for h in reader.fieldnames}
        for required in ('period_code', 'kpi_code', 'geography_node_code', 'target_value'):
            if required not in header:
                raise BusinessError(f'CSV must include a "{required}" column.')

        parsed, errors = [], []
        for i, raw in enumerate(reader, start=2):
            row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
            try:
                parsed.append(TargetService._resolve_import_row(row))
            except BusinessError as exc:
                errors.append({'row': i, 'errors': [str(exc)]})

        if errors:
            return {'status': 'validation_failed', 'created': 0, 'updated': 0, 'errors': errors}

        created = updated = 0
        for r in parsed:
            fields = {'target_value': r['value'], 'original_target_value': r['value'],
                      'source': TargetAllocation.BULK}
            # A fresh row is the initial load; overwriting an existing (live) number is an
            # edit and lands pending for a checker — the same rule as manual edits.
            _, was_created = TargetAllocation.objects.update_or_create(
                target_period=r['period'], kpi=r['kpi'], geography_node=r['geography_node'],
                channel=r['channel'], sku_group=r['sku_group'],
                defaults={**fields, 'status': TargetAllocation.PENDING},
                create_defaults={**fields, 'status': TargetAllocation.APPROVED},
            )
            created += int(was_created)
            updated += int(not was_created)

        AuditService.log('bulk_import', 'targets.TargetAllocation', 0, actor,
                         {'created': created, 'updated': updated})
        return {'status': 'success', 'created': created, 'updated': updated, 'errors': []}

    @staticmethod
    def _resolve_import_row(row: dict) -> dict:
        period = TargetPeriod.objects.filter(code=row.get('period_code')).first()
        if period is None:
            raise BusinessError(f'Unknown period "{row.get("period_code")}".')
        if period.period_type != TargetPeriod.MONTHLY:
            raise BusinessError(
                f'Targets are set monthly — "{period.code}" is a {period.period_type} period.')
        kpi = KPIDefinition.objects.filter(code=row.get('kpi_code'), is_current=True).first()
        if kpi is None:
            raise BusinessError(f'Unknown KPI "{row.get("kpi_code")}".')
        node = GeographyNode.objects.filter(code=row.get('geography_node_code'), is_active=True).first()
        if node is None:
            raise BusinessError(f'Unknown geography node "{row.get("geography_node_code")}".')
        channel = Channel.objects.filter(code=row['channel_code']).first() if row.get('channel_code') else None
        sku_group = SKUGroup.objects.filter(code=row['sku_group_code']).first() if row.get('sku_group_code') else None
        return {'period': period, 'kpi': kpi, 'geography_node': node, 'channel': channel,
                'sku_group': sku_group, 'value': _to_decimal(row.get('target_value'), 'target_value')}

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _assert_editable(period):
        if period.status not in _EDITABLE_PERIOD_STATES:
            raise BusinessError(f'This period is {period.status} and cannot be changed.')
