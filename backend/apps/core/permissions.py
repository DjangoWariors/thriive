from datetime import date

from django.apps import apps
from django.db.models import Q
from rest_framework.permissions import BasePermission

SAFE_METHODS = frozenset(('GET', 'HEAD', 'OPTIONS'))

_LEVEL_RANK: dict[str, int] = {
    'full': 6,
    'view_all': 5,
    'view_edit': 4,
    'team': 3,
    'own_only': 2,
    'view_readonly': 1,
    'none': 0,
}


def _rank(level: str) -> int:
    return _LEVEL_RANK.get(level, 0)


def subtree_lookup(path: str, path_field: str = 'path') -> dict[str, str]:
    """ORM filter kwargs selecting rows at or under ``path`` (inclusive).

    The single source of truth for the materialized-path "is within my subtree"
    rule, shared by RBACPermission._is_in_team (object gating) and
    NodeScopedQuerysetMixin.scope_queryset (list scoping) so the two cannot
    drift. ``path_field`` is the lookup target on the row ('path' for an Node,
    'entity__path' for a row with an entity FK such as User).
    """
    return {f'{path_field}__startswith': path}


def highest_level(user, permission: str) -> str:
    """Highest permission level granted to ``user`` for ``permission`` across
    their currently-effective roles. Returns ``'none'`` if no role grants it.

    Shared by RBACPermission (object gating) and NodeScopedQuerysetMixin
    (list scoping) so both resolve levels identically. The result is memoized on
    the (per-request) user instance: a single request resolves the same
    permission in has_permission, has_object_permission and scope_queryset, and
    we don't want a UserRole query for each.
    """
    cache = getattr(user, '_rbac_level_cache', None)
    if cache is not None and permission in cache:
        return cache[permission]

    UserRole = apps.get_model('accounts', 'UserRole')

    today = date.today()
    active_roles = (
        UserRole.objects.filter(
            user=user,
            is_active=True,
            role__is_active=True,
            effective_from__lte=today,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
        .select_related('role')
    )
    best = 'none'
    for ur in active_roles:
        level = ur.role.permissions.get(permission, 'none')
        if _rank(level) > _rank(best):
            best = level

    # Defense in depth for payout-confidential resources: a grant at a disallowed
    # level (e.g. a hand-seeded 'team' on final_payout) resolves to 'none' rather
    # than exposing subtree payouts. Role writes already reject these; this clamp
    # covers rows that bypassed RoleService. Pure-python import — no model cycle.
    from apps.accounts.permission_catalog import CONFIDENTIAL_RESOURCES, RESOURCE_LEVELS
    if permission in CONFIDENTIAL_RESOURCES and best not in RESOURCE_LEVELS[permission]:
        best = 'none'

    if cache is None:
        try:
            cache = {}
            user._rbac_level_cache = cache
        except (AttributeError, TypeError):
            cache = None
    if cache is not None:
        cache[permission] = best
    return best


def may_see_payout_figures(user) -> bool:
    """May this user be shown a money amount derived from payouts?

    Payout confidentiality is structural (see accounts/permission_catalog.py): a manager
    sees team achievements but never team payouts. Any figure that travels outside the
    payout endpoints — a workflow's impact amount, an exception's pay at stake — has to
    pass through here, or it becomes a side channel around that rule.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return bool(getattr(user, 'is_superuser', False)) or \
        highest_level(user, 'final_payout') in ('full', 'view_all')


class RBACPermission(BasePermission):
    """
    Checks `view.required_permission` against the user's active Role permissions.

    Permission levels (highest → lowest):
        full > view_all > view_edit > team > own_only > view_readonly > none

    Object-level semantics:
        full                     → unconditional access
        view_all / view_readonly → read any object; no writes (GET/HEAD/OPTIONS)
        view_edit                → read any object; write only within own subtree
        team                     → own subtree only (read + write)
        own_only                 → own entity only (read + write)
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        required = getattr(view, 'required_permission', None)
        if required is None:
            return True
        return _rank(self._highest_level(request.user, required)) > 0

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        required = getattr(view, 'required_permission', None)
        if required is None:
            return True

        level = self._highest_level(request.user, required)

        if level == 'full':
            return True
        if level in ('view_all', 'view_readonly'):
            # Read-any, but never write.
            return request.method in SAFE_METHODS
        if level == 'own_only':
            return self._is_own(request.user, obj)
        if level == 'team':
            return self._is_in_team(request.user, obj)
        if level == 'view_edit':
            return request.method in SAFE_METHODS or self._is_in_team(request.user, obj)
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _highest_level(self, user, permission: str) -> str:
        return highest_level(user, permission)

    def _is_own(self, user, obj) -> bool:
        user_entity = getattr(user, 'entity', None)
        if user_entity is None:
            return False
        obj_eid = self._entity_id(obj)
        return obj_eid is not None and user_entity.pk == obj_eid

    def _is_in_team(self, user, obj) -> bool:
        user_entity = getattr(user, 'entity', None)
        if user_entity is None:
            return False
        obj_eid = self._entity_id(obj)
        if obj_eid is None:
            return False
        Node = apps.get_model('hierarchy', 'Node')
        return Node.objects.filter(
            pk=obj_eid,
            is_current=True,
            **subtree_lookup(user_entity.path),
        ).exists()

    def _entity_id(self, obj):
        # obj carries an entity FK (e.g. User, or any model with entity_id).
        eid = getattr(obj, 'entity_id', None)
        if eid is not None:
            return eid
        entity = getattr(obj, 'entity', None)
        if entity is not None:
            return entity.pk
        # Otherwise obj may itself be an Node. Match by type — not by
        # duck-typing on `path` — so GeographyNode (also path+pk) is never
        # mistaken for an entity.
        Node = apps.get_model('hierarchy', 'Node')
        if isinstance(obj, Node):
            return obj.pk
        return None


class LevelRBACPermission(RBACPermission):
    """RBAC for viewsets whose objects carry NO org-entity anchor — geography-anchored
    targets rows (plans, periods, allocations, review tasks) and workflow instances.
    The base object check resolves an ``entity`` FK these models don't have, which would
    deny every placed user (an RSM reviewing their own cascade got 403s).

    Object-stage checks here keep only the LEVEL semantics: read for any holder, write
    for write-capable levels. WHICH objects a user can reach is owned by the view's
    scoped queryset (territory / task-owner / involvement filters — a foreign object
    404s) and the module's explicit guards (plan-admin gates, task-owner checks,
    workflow step eligibility)."""

    _WRITE_LEVELS = frozenset(('full', 'view_edit', 'team', 'own_only'))

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        required = getattr(view, 'required_permission', None)
        if required is None:
            return True
        level = self._highest_level(user, required)
        if request.method in SAFE_METHODS:
            return _rank(level) > 0
        return level in self._WRITE_LEVELS
