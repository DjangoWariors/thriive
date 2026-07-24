"""AssignmentService — the resolvers that link the geography and organisation trees.

Everything that needs to know *who is responsible for a territory* (RBAC territory
scoping, achievement attribution, payout ownership) goes through here rather than
reading a static FK. Assignments are effective-dated, so the same question always
carries an "as of" date.
"""
from datetime import date, timedelta

from django.db import transaction
from django.db.models import OuterRef, Q, Subquery

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Node, GeographyNode

from .models import Assignment


def _as_of(on: date | None) -> date:
    return on or date.today()


def _effective_filter(on: date) -> Q:
    """Rows whose [effective_from, effective_to] window contains ``on``."""
    return Q(effective_from__lte=on) & (Q(effective_to__isnull=True) | Q(effective_to__gte=on))


def _ancestor_paths(path: str) -> list[str]:
    """``/IN/ZA/A1/`` → ``['/IN/ZA/A1/', '/IN/ZA/', '/IN/']`` — the territory itself first,
    then each ancestor, so a nearest-owner lookup is just the first hit."""
    codes = [c for c in path.split('/') if c]
    return ['/' + '/'.join(codes[:i]) + '/' for i in range(len(codes), 0, -1)]


class AssignmentService:

    # ------------------------------------------------------------------
    # Resolvers (read)
    # ------------------------------------------------------------------

    @staticmethod
    def owner_of(scope, on: date | None = None) -> Node | None:
        """The organisation entity that owns ``scope`` on ``on`` (default today).

        ``scope`` may be a GeographyNode or its id. Returns the assignee Node of
        the effective ``owner`` assignment, or ``None`` if the territory is unowned.
        """
        on = _as_of(on)
        scope_id = scope.pk if isinstance(scope, GeographyNode) else int(scope)
        assignment = (
            Assignment.objects
            .filter(_effective_filter(on),
                    scope_id=scope_id, role_in_scope=Assignment.Role.OWNER, is_active=True)
            .select_related('assignee')
            .order_by('-effective_from')
            .first()
        )
        return assignment.assignee if assignment else None

    @staticmethod
    def scopes_owned_by(user, on: date | None = None, *, role: str | None = None):
        """Geography nodes the user's entity is assigned to on ``on``.

        Returns a GeographyNode queryset (directly-assigned scopes only — the RBAC
        layer expands each to its subtree via the materialized path). An unplaced
        user (no linked entity) owns nothing.
        """
        on = _as_of(on)
        entity = getattr(user, 'entity', None)
        if entity is None:
            return GeographyNode.objects.none()
        qs = Assignment.objects.filter(_effective_filter(on), assignee=entity, is_active=True)
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        scope_ids = qs.values('scope_id')
        return GeographyNode.objects.filter(pk__in=scope_ids, is_active=True)

    @staticmethod
    def scope_node_ids_for_entity(entity_id: int, on: date | None = None,
                                  *, role: str | None = None) -> list[int]:
        """Geography node ids an organisation entity is responsible for on ``on``,
        each expanded to its whole subtree.

        This is the attribution key set for the KPI/achievement engines and the
        territory dimension of RBAC: owning a region implies owning every territory
        and outlet beneath it. Returns ``[]`` for an entity that owns no territory.
        """
        on = _as_of(on)
        qs = Assignment.objects.filter(_effective_filter(on), assignee_id=entity_id, is_active=True)
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        scope_paths = list(
            GeographyNode.objects
            .filter(pk__in=qs.values('scope_id'), is_active=True)
            .values_list('path', flat=True)
        )
        if not scope_paths:
            return []
        path_q = Q()
        for path in scope_paths:
            path_q |= Q(path__startswith=path)
        return list(
            GeographyNode.objects.filter(path_q, is_active=True).values_list('id', flat=True)
        )

    # Above this many distinct scope paths, one streamed pass over all live nodes
    # beats per-scope prefix queries (150k retailers each owning an outlet would
    # otherwise mean 150k queries).
    _BATCH_SCOPE_THRESHOLD = 50

    @staticmethod
    def scope_node_ids_map(entity_ids, on: date | None = None,
                           *, role: str | None = None) -> dict[int, list[int]]:
        """Batched ``scope_node_ids_for_entity`` for an entity set — the query count
        is constant (2-ish) regardless of ``len(entity_ids)``.

        For every entity: the geography node ids it is responsible for on ``on``,
        each directly-assigned scope expanded to its whole subtree. Entities with
        no territory map to ``[]``.
        """
        entity_ids = list(entity_ids)
        if not entity_ids:
            return {}
        on = _as_of(on)
        qs = Assignment.objects.filter(
            _effective_filter(on), assignee_id__in=entity_ids,
            is_active=True, scope__is_active=True,
        )
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        pairs = list(qs.values_list('assignee_id', 'scope__path'))

        owned: dict[int, set[int]] = {eid: set() for eid in entity_ids}
        if not pairs:
            return {eid: [] for eid in entity_ids}

        path_owners: dict[str, list[int]] = {}
        for eid, path in pairs:
            path_owners.setdefault(path, []).append(eid)

        if len(path_owners) <= AssignmentService._BATCH_SCOPE_THRESHOLD:
            # Few distinct scopes: one indexed prefix query each.
            for path, owners in path_owners.items():
                ids = GeographyNode.objects.filter(
                    path__startswith=path, is_active=True,
                ).values_list('id', flat=True)
                for node_id in ids:
                    for eid in owners:
                        owned[eid].add(node_id)
        else:
            # Many scopes: stream every live (id, path) once and decompose each
            # node's path into its ancestor prefixes — paths end with '/', so a
            # prefix hit is true ancestry ('/A/B/' can never claim '/A/BC/...').
            node_rows = GeographyNode.objects.filter(is_active=True) \
                .values_list('id', 'path').iterator(chunk_size=10_000)
            for node_id, node_path in node_rows:
                idx = node_path.find('/', 1)
                while idx != -1:
                    owners = path_owners.get(node_path[:idx + 1])
                    if owners:
                        for eid in owners:
                            owned[eid].add(node_id)
                    idx = node_path.find('/', idx + 1)

        return {eid: sorted(ids) for eid, ids in owned.items()}

    @staticmethod
    def scope_node_qs_for_entity(entity_id: int, on: date | None = None,
                                 *, role: str | None = None):
        """Un-materialized twin of ``scope_node_ids_for_entity``: a GeographyNode
        values-queryset of the owned subtree ids, for use as a SQL subquery
        (``attributed_node_id__in=<qs>``) — constant SQL size even when a national
        owner's subtree is 150k nodes. Returns ``None`` when nothing is owned.
        """
        on = _as_of(on)
        qs = Assignment.objects.filter(_effective_filter(on), assignee_id=entity_id, is_active=True)
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        scope_paths = list(
            GeographyNode.objects
            .filter(pk__in=qs.values('scope_id'), is_active=True)
            .values_list('path', flat=True)
        )
        if not scope_paths:
            return None
        path_q = Q()
        for path in scope_paths:
            path_q |= Q(path__startswith=path)
        return GeographyNode.objects.filter(path_q, is_active=True).values('id')

    @staticmethod
    def owned_scope_ids_for_entity(entity_id: int, on: date | None = None,
                                   *, role: str | None = Assignment.Role.OWNER) -> list[int]:
        """Geography node ids an entity is *directly* assigned on ``on`` — NOT expanded to subtrees.

        Use this for target rollup: a person's target is the sum of the allocations on the nodes
        they directly own, and disaggregation already makes a parent's target equal the sum of its
        descendants — so expanding to subtrees (as ``scope_node_ids_for_entity`` does for the
        attribution key set) would double-count. Returns ``[]`` for an entity that owns nothing.
        """
        on = _as_of(on)
        qs = Assignment.objects.filter(_effective_filter(on), assignee_id=entity_id, is_active=True)
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        return list(
            GeographyNode.objects.filter(pk__in=qs.values('scope_id'), is_active=True)
            .values_list('id', flat=True)
        )

    @staticmethod
    def owned_top_scopes_for_entity(entity_id: int, on: date | None = None,
                                    *, within_path: str | None = None):
        """The entity's directly-owned nodes with no owned proper ancestor — the roots of
        the disjoint subtrees the person is responsible for. Optionally restricted to nodes
        under ``within_path`` (e.g. a plan's root). Ordered shallowest-first (depth, path),
        so callers wanting one representative subtree take the first. OWNER role only —
        this shapes what a person "lands on", not what they may read."""
        on = _as_of(on)
        qs = Assignment.objects.filter(
            _effective_filter(on), assignee_id=entity_id, is_active=True,
            role_in_scope=Assignment.Role.OWNER,
        )
        nodes = list(
            GeographyNode.objects.filter(pk__in=qs.values('scope_id'), is_active=True)
            .order_by('depth', 'path')
        )
        if within_path:
            nodes = [n for n in nodes if n.path.startswith(within_path)]
        paths = [n.path for n in nodes]
        return [n for n in nodes
                if not any(n.path.startswith(p) and n.path != p for p in paths)]

    @staticmethod
    def scope_paths_for_entity(entity_id: int, on: date | None = None) -> list[str]:
        """Materialized paths of every territory the entity is assigned to on ``on`` —
        any role, matching the read-scoping semantics of ``scope_node_ids_for_entity``.
        A node is inside the entity's area iff its path starts with one of these."""
        on = _as_of(on)
        qs = Assignment.objects.filter(_effective_filter(on), assignee_id=entity_id, is_active=True)
        return list(
            GeographyNode.objects.filter(pk__in=qs.values('scope_id'), is_active=True)
            .values_list('path', flat=True)
        )

    @staticmethod
    def entity_covers_node(entity_id: int, node, on: date | None = None) -> bool:
        """True if ``node`` lies inside any territory the entity is assigned to (subtree
        containment by path prefix). Any assignment role — a write guard must never
        contradict what the territory-scoped querysets let the caller see."""
        return any(node.path.startswith(p)
                   for p in AssignmentService.scope_paths_for_entity(entity_id, on))

    @staticmethod
    def owner_entity_ids_for_scopes(scope_ids, on: date | None = None) -> set[int]:
        """Org entity ids that own any of ``scope_ids`` on ``on`` — one query, for bulk
        "who is responsible for these territories" lookups (e.g. eligible achievement types)."""
        scope_ids = list(scope_ids)
        if not scope_ids:
            return set()
        on = _as_of(on)
        return set(
            Assignment.objects.filter(
                _effective_filter(on), scope_id__in=scope_ids,
                role_in_scope=Assignment.Role.OWNER, is_active=True,
            ).values_list('assignee_id', flat=True)
        )

    @staticmethod
    def owners_for_scopes(scope_ids, on: date | None = None) -> dict[int, Node]:
        """{scope_id: owner Node} for every scope with an effective owner on ``on`` —
        one query, for grids that show who is accountable per territory."""
        scope_ids = list(scope_ids)
        if not scope_ids:
            return {}
        on = _as_of(on)
        rows = (
            Assignment.objects
            .filter(_effective_filter(on), scope_id__in=scope_ids,
                    role_in_scope=Assignment.Role.OWNER, is_active=True)
            .select_related('assignee__entity_type')
            .order_by('scope_id', '-effective_from')
        )
        result: dict[int, Node] = {}
        for a in rows:
            result.setdefault(a.scope_id, a.assignee)  # newest effective_from wins
        return result

    @staticmethod
    def annotate_direct_owner(qs, node_field: str, on: date | None = None):
        """Annotate ``owner_code``/``owner_name`` — the territory's *direct* owner — onto a
        queryset whose ``node_field`` holds a GeographyNode id.

        A correlated subquery, so the database resolves ownership row by row through
        ``assign_scope_role_from_idx`` inside the caller's own cursor. Streaming callers
        should prefer this over batched id lookups: a large ``scope_id__in`` list makes the
        planner abandon the index. Inherited ownership is not covered — pair it with
        ``owner_labels_for_nodes`` for the rows that come back with no direct owner.
        """
        on = _as_of(on)
        owner = (
            Assignment.objects
            .filter(_effective_filter(on), scope_id=OuterRef(node_field),
                    role_in_scope=Assignment.Role.OWNER, is_active=True)
            .order_by('-effective_from')
        )
        return qs.annotate(
            owner_code=Subquery(owner.values('assignee__code')[:1]),
            owner_name=Subquery(owner.values('assignee__name')[:1]),
        )

    @staticmethod
    def owner_labels_for_nodes(nodes, on: date | None = None,
                               inherited_cache: dict | None = None) -> dict[int, tuple[str, str]]:
        """``{node id: (owner code, owner name)}`` — who is accountable for each territory in
        ``nodes`` (an iterable of ``(id, path)``), falling back to the nearest owned ancestor
        when a territory has no owner of its own. Territories with no owner anywhere up the
        chain are absent from the result.

        Built for streaming callers (exports, paginated grids), so it takes an explicit batch
        rather than a subtree root: a whole-subtree index would be O(territories) in memory —
        hundreds of MB at 200k outlets. Direct owners resolve by indexed ``scope_id``; only
        the territories without one pay an ancestor lookup, and passing the same
        ``inherited_cache`` dict across batches makes that cost converge to zero (ancestors
        repeat across every batch).
        """
        nodes = list(nodes)
        if not nodes:
            return {}
        on = _as_of(on)
        cache = inherited_cache if inherited_cache is not None else {}

        direct = {}
        for scope_id, code, name in (
            Assignment.objects
            .filter(_effective_filter(on), role_in_scope=Assignment.Role.OWNER,
                    is_active=True, scope_id__in=[n[0] for n in nodes])
            .order_by('scope_id', '-effective_from')
            .values_list('scope_id', 'assignee__code', 'assignee__name')
        ):
            direct.setdefault(scope_id, (code, name))  # newest effective_from wins

        # Only the unowned territories need the walk up. Their ancestor paths are a small,
        # heavily repeated set (trees are shallow), so one lookup serves the whole stream.
        orphans = [(nid, path) for nid, path in nodes if nid not in direct]
        unknown = {step for _, path in orphans
                   for step in _ancestor_paths(path)[1:] if step not in cache}
        if unknown:
            found = {}
            for path, code, name in (
                Assignment.objects
                .filter(_effective_filter(on), role_in_scope=Assignment.Role.OWNER,
                        is_active=True, scope__path__in=unknown)
                .order_by('scope_id', '-effective_from')
                .values_list('scope__path', 'assignee__code', 'assignee__name')
            ):
                found.setdefault(path, (code, name))
            cache.update({step: found.get(step) for step in unknown})

        resolved = dict(direct)
        for nid, path in orphans:
            hit = next((cache[step] for step in _ancestor_paths(path)[1:] if cache.get(step)), None)
            if hit is not None:
                resolved[nid] = hit
        return resolved

    @staticmethod
    def open_owner_scopes_map(assignee_ids, on: date | None = None) -> dict[int, list]:
        """{assignee_id: [Assignment(+scope)]} for every effective owner assignment —
        one query, so list serializers can render display codes / owned scopes without N+1.
        Scopes are ordered shallowest-first then by code (the primary-scope rule)."""
        assignee_ids = list(assignee_ids)
        if not assignee_ids:
            return {}
        on = _as_of(on)
        rows = (
            Assignment.objects
            .filter(_effective_filter(on),
                    assignee_id__in=assignee_ids,
                    role_in_scope=Assignment.Role.OWNER, is_active=True)
            .select_related('scope')
            .order_by('scope__depth', 'scope__code')
        )
        result: dict[int, list] = {}
        for a in rows:
            result.setdefault(a.assignee_id, []).append(a)
        return result

    @staticmethod
    def owner_assignee_ids_in_subtree(scope, on: date | None = None) -> set[int]:
        """Org entity ids owning any territory within ``scope``'s subtree (inclusive) —
        the territory dimension of the entity list's ?geography filter."""
        on = _as_of(on)
        scope_ids = GeographyNode.objects.filter(
            path__startswith=scope.path, is_active=True,
        ).values('id')
        return set(
            Assignment.objects
            .filter(_effective_filter(on), scope_id__in=scope_ids,
                    role_in_scope=Assignment.Role.OWNER, is_active=True)
            .values_list('assignee_id', flat=True)
        )

    @staticmethod
    def open_assignments_for_assignee(assignee_id: int, on: date | None = None,
                                      *, role: str | None = None):
        """Effective assignments held by an org entity on ``on`` (any role unless given)."""
        on = _as_of(on)
        qs = (
            Assignment.objects
            .filter(_effective_filter(on), assignee_id=assignee_id, is_active=True)
            .select_related('scope')
            .order_by('scope__depth', 'scope__code')
        )
        if role is not None:
            qs = qs.filter(role_in_scope=role)
        return qs

    @staticmethod
    def assignments_for(scope, on: date | None = None):
        """All effective assignments on a scope (any role) — for the territory detail view."""
        on = _as_of(on)
        scope_id = scope.pk if isinstance(scope, GeographyNode) else int(scope)
        return (
            Assignment.objects
            .filter(_effective_filter(on), scope_id=scope_id, is_active=True)
            .select_related('assignee', 'scope')
            .order_by('role_in_scope')
        )

    # ------------------------------------------------------------------
    # Mutations (write) — the only layer that writes Assignment rows
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create(*, assignee_id: int, scope_id: int, role_in_scope: str = Assignment.Role.OWNER,
               effective_from: date, reason: str = '', user=None) -> Assignment:
        """Open a new assignment. For ``owner``, rejects an overlapping open owner on
        the same scope — use ``transfer`` to hand a territory over."""
        assignee = Node.objects.filter(
            pk=assignee_id, is_current=True, is_active=True,
        ).select_related('entity_type').first()
        if assignee is None:
            raise BusinessError(f'Assignee entity {assignee_id} not found or not current.')

        # Lock the scope row so concurrent create/transfer on the same territory serialise —
        # the one-owner-per-scope invariant is enforced in app code, not by a DB constraint.
        scope = GeographyNode.objects.select_for_update().filter(pk=scope_id, is_active=True).first()
        if scope is None:
            raise BusinessError(f'Geography scope {scope_id} not found or inactive.')

        if role_in_scope == Assignment.Role.OWNER:
            clash = (
                Assignment.objects
                .filter(_effective_filter(effective_from),
                        scope=scope, role_in_scope=Assignment.Role.OWNER, is_active=True)
                .exists()
            )
            if clash:
                raise BusinessError(
                    f"Territory '{scope.code}' already has an owner on {effective_from}. "
                    'Use transfer to hand it over.'
                )

        assignment = Assignment.objects.create(
            assignee=assignee, scope=scope, role_in_scope=role_in_scope,
            effective_from=effective_from, reason=reason,
        )
        AuditService.log(
            action='create', entity_type='assignments.Assignment',
            entity_id=assignment.pk, user=user,
            changes={'assignee_id': assignee_id, 'scope_id': scope_id,
                     'role_in_scope': role_in_scope, 'effective_from': str(effective_from)},
        )
        return assignment

    @staticmethod
    @transaction.atomic
    def end(assignment_id: int, *, effective_to: date, reason: str = '', user=None) -> Assignment:
        """Close an open assignment on a date (its last owned day)."""
        assignment = Assignment.objects.select_for_update().filter(
            pk=assignment_id, is_active=True,
        ).first()
        if assignment is None:
            raise BusinessError(f'Assignment {assignment_id} not found.')
        if assignment.effective_to is not None and assignment.effective_to < effective_to:
            raise BusinessError('Assignment is already closed before this date.')
        if effective_to < assignment.effective_from:
            raise BusinessError('effective_to cannot precede effective_from.')

        assignment.effective_to = effective_to
        assignment.save(update_fields=['effective_to', 'updated_at'])
        AuditService.log(
            action='update', entity_type='assignments.Assignment',
            entity_id=assignment.pk, user=user,
            changes={'effective_to': str(effective_to), 'reason': reason},
        )
        return assignment

    @staticmethod
    @transaction.atomic
    def end_all_for_assignee(assignee_id: int, *, effective_to: date,
                             reason: str = '', user=None) -> int:
        """Close every open assignment an entity holds (any role) — e.g. when the
        seat is deactivated. Returns the number closed."""
        open_qs = Assignment.objects.select_for_update().filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=effective_to),
            assignee_id=assignee_id, is_active=True,
        )
        count = 0
        for assignment in open_qs:
            if assignment.effective_from > effective_to:
                continue
            assignment.effective_to = effective_to
            assignment.save(update_fields=['effective_to', 'updated_at'])
            AuditService.log(
                action='update', entity_type='assignments.Assignment',
                entity_id=assignment.pk, user=user,
                changes={'effective_to': str(effective_to), 'reason': reason},
            )
            count += 1
        return count

    @staticmethod
    @transaction.atomic
    def transfer(*, scope_id: int, new_assignee_id: int, effective_from: date,
                 reason: str = '', role_in_scope: str = Assignment.Role.OWNER,
                 user=None) -> Assignment:
        """Hand a territory from its current holder to a new one, effective-dated.

        The outgoing assignment is closed on the day before ``effective_from`` and a
        new one opens on ``effective_from``. The geography, its outlets and targets
        are untouched — only ownership moves. Idempotent on the assignee: transferring
        to the current holder is a no-op error.
        """
        # Lock the scope row so create/transfer on the same territory serialise (see create()).
        scope = GeographyNode.objects.select_for_update().filter(pk=scope_id, is_active=True).first()
        if scope is None:
            raise BusinessError(f'Geography scope {scope_id} not found or inactive.')

        new_assignee = Node.objects.filter(
            pk=new_assignee_id, is_current=True, is_active=True,
        ).first()
        if new_assignee is None:
            raise BusinessError(f'New assignee entity {new_assignee_id} not found or not current.')

        current = (
            Assignment.objects
            .filter(_effective_filter(effective_from),
                    scope=scope, role_in_scope=role_in_scope, is_active=True)
            .select_for_update()
            .order_by('-effective_from')
            .first()
        )
        if current is not None:
            if current.assignee_id == new_assignee_id:
                raise BusinessError(f"'{scope.code}' is already held by that entity.")
            if effective_from <= current.effective_from:
                raise BusinessError(
                    'Transfer date must be after the current assignment started '
                    f'({current.effective_from}).'
                )
            current.effective_to = effective_from - timedelta(days=1)
            current.save(update_fields=['effective_to', 'updated_at'])

        new_assignment = Assignment.objects.create(
            assignee=new_assignee, scope=scope, role_in_scope=role_in_scope,
            effective_from=effective_from, reason=reason,
        )
        AuditService.log(
            action='transfer', entity_type='assignments.Assignment',
            entity_id=new_assignment.pk, user=user,
            changes={
                'scope_id': scope_id,
                'from_assignee_id': current.assignee_id if current else None,
                'to_assignee_id': new_assignee_id,
                'role_in_scope': role_in_scope,
                'effective_from': str(effective_from),
                'reason': reason,
            },
        )
        return new_assignment
