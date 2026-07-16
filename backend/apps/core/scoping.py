"""Node-scope filtering for list querysets.

The platform rule: **anyone placed in the entity hierarchy sees only their own
entity and everything beneath it** (their `entity.path` subtree) — for every
hierarchy data endpoint, regardless of permission level. Their position in the
tree *is* their visibility. Whether they may reach an endpoint at all is still
governed by `RBACPermission.has_permission` (the admin-assigned level); this
mixin only narrows *which rows* they see once allowed.

`RBACPermission.has_object_permission` only scopes single-object access, and DRF
never runs it per-row on a list — hence this queryset-level scope.
"""
from apps.core.permissions import highest_level, subtree_lookup

# Levels granting unconditional read for users NOT placed in the hierarchy
# (standalone admin / finance accounts with no linked entity).
_UNSCOPED_LEVELS = frozenset(('full', 'view_all', 'view_edit', 'view_readonly'))


class NodeScopedQuerysetMixin:
    """Filter a viewset's queryset to the requester's entity subtree.

    Set on subclasses:
        scope_path_field — lookup for the materialized-path prefix match
                           ('path' for Node rows, 'entity__path' for rows with
                           an entity FK such as User).
    """

    scope_path_field = 'path'

    def scope_queryset(self, qs):
        user = self.request.user
        required = getattr(self, 'required_permission', None)
        if user.is_superuser or required is None:
            return qs

        home = getattr(user, 'entity', None)
        if home is not None:
            # Placed in the hierarchy → see own entity + descendants only,
            # independent of permission level (team / view_all / full all alike).
            return qs.filter(**subtree_lookup(home.path, self.scope_path_field))

        # Not placed in the hierarchy (standalone admin / finance). Fall back to
        # the level: read-any levels see everything; team/own_only have no subtree
        # to resolve, so they see nothing.
        if highest_level(user, required) in _UNSCOPED_LEVELS:
            return qs
        return qs.none()


def scope_by_entity_ids(qs, user, required, field='entity_id'):
    """Subtree-scope a queryset whose entity reference is a plain id column (NOT an FK
    with a path), e.g. ``Transaction.entity_id``. Resolves the requester's subtree to a
    set of Node ids and filters ``field__in``. Same precedence as the mixin."""
    if getattr(user, 'is_superuser', False) or required is None:
        return qs
    home = getattr(user, 'entity', None)
    if home is not None:
        from apps.hierarchy.models import Node
        ids = Node.objects.filter(is_current=True, **subtree_lookup(home.path)).values('id')
        return qs.filter(**{f'{field}__in': ids})
    if highest_level(user, required) in _UNSCOPED_LEVELS:
        return qs
    return qs.none()


def scope_transactions_by_territory(qs, user, required, field='attributed_node_id'):
    """Scope a queryset attributed to geography nodes (e.g. ``Transaction.attributed_node_id``)
    to the territories the requester owns. Sales attach to geography, so a placed user sees
    the transactions of the territories they own (via assignments), expanded to subtrees.
    An unplaced read-any user sees everything; an unplaced team/own_only user sees nothing."""
    if getattr(user, 'is_superuser', False) or required is None:
        return qs
    home = getattr(user, 'entity', None)
    if home is not None:
        from apps.assignments.services import AssignmentService
        node_ids = AssignmentService.scope_node_ids_for_entity(home.pk)
        return qs.filter(**{f'{field}__in': node_ids})
    if highest_level(user, required) in _UNSCOPED_LEVELS:
        return qs
    return qs.none()


def requester_can_reach_entity(user, required, entity) -> bool:
    """True if ``entity`` is the requester's own entity or a descendant (or the requester
    is unscoped: superuser / read-any without a home entity). Guards the ``detail=False``
    actions that take an entity id in params/body and so never trigger object permissions."""
    if getattr(user, 'is_superuser', False) or required is None:
        return True
    home = getattr(user, 'entity', None)
    if home is not None:
        from apps.hierarchy.models import Node
        return Node.objects.filter(pk=entity.pk, is_current=True, **subtree_lookup(home.path)).exists()
    return highest_level(user, required) in _UNSCOPED_LEVELS


def is_planning_admin(user, required) -> bool:
    """True for plan-wide operators (superuser, or a read-any level without a home entity).
    Period-wide actions with no single entity (e.g. phasing) require this."""
    if getattr(user, 'is_superuser', False) or required is None:
        return True
    if getattr(user, 'entity', None) is not None:
        return False
    return highest_level(user, required) in _UNSCOPED_LEVELS
