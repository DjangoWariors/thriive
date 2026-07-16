"""Assignee resolution — reads the entity tree and roles (ORM reads only, no writes).

Resolution is re-run when a step *activates* (not just at initiation) so org transfers
made after a request was raised route to the current manager. Delegation substitution is
handled at the eligibility/inbox layer in ``services.py``, not here, so resolution stays a
pure function of org structure.
"""
from datetime import date

from django.apps import apps
from django.db.models import Q


def managers_up(entity, levels: int = 1) -> list:
    """Up to ``levels`` nearest *loginable* managers above ``entity`` (closest first)."""
    if entity is None:
        return []
    User = apps.get_model('accounts', 'User')
    out = []
    for ancestor in entity.get_ancestors():  # [parent, grandparent, …, root]
        user = User.objects.filter(entity=ancestor, is_active=True).first()
        if user is not None:
            out.append(user)
        if len(out) >= levels:
            break
    return out


def manager_at_level(entity, levels: int = 1) -> list:
    """The single loginable manager ``levels`` loginable-steps above ``entity``.

    Returns ``[user]`` (or the highest available if the tree is shorter), else ``[]``.
    """
    found = managers_up(entity, levels)
    if not found:
        return []
    return [found[levels - 1]] if len(found) >= levels else found[-1:]


def role_holders_above(role_code: str, anchor_entity) -> list:
    """Active holders of ``role_code`` whose entity subtree contains ``anchor_entity``.

    If nobody with the role is placed above the anchor (e.g. a national head modelled as a
    standalone account with no entity), fall back to *all* active holders of the role — the
    request must still reach a decision-maker.
    """
    if not role_code:
        return []
    UserRole = apps.get_model('accounts', 'UserRole')
    today = date.today()
    rows = (
        UserRole.objects.filter(
            role__code=role_code, is_active=True, role__is_active=True,
            effective_from__lte=today,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
        .select_related('user', 'user__entity')
    )
    anchor_path = getattr(anchor_entity, 'path', '') or ''
    above, holders = [], []
    for ur in rows:
        user = ur.user
        if user is None or not user.is_active:
            continue
        holders.append(user)
        ent = getattr(user, 'entity', None)
        if anchor_path and ent is not None and ent.path and anchor_path.startswith(ent.path):
            above.append(user)
    return _dedupe(above or holders)


def fixed_entity_users(entity_code: str) -> list:
    if not entity_code:
        return []
    Node = apps.get_model('hierarchy', 'Node')
    User = apps.get_model('accounts', 'User')
    ent = Node.objects.filter(code=entity_code, is_current=True, is_active=True).first()
    if ent is None:
        return []
    user = User.objects.filter(entity=ent, is_active=True).first()
    return [user] if user else []


def resolve_assignees(step_config: dict, anchor_entity) -> list:
    """Resolve the users eligible to action a step from its config + the routing anchor."""
    rule = step_config.get('assignee_rule', 'hierarchy_manager')
    levels = int(step_config.get('hierarchy_levels_up', 1) or 1)
    if rule in ('hierarchy_manager', 'initiator_manager'):
        users = manager_at_level(anchor_entity, levels)
    elif rule == 'role':
        users = role_holders_above(step_config.get('role_code', ''), anchor_entity)
    elif rule == 'fixed_entity':
        users = fixed_entity_users(step_config.get('entity_code', ''))
    else:
        users = manager_at_level(anchor_entity, levels)
    return _dedupe(users)


def _dedupe(users: list) -> list:
    seen, out = set(), []
    for u in users:
        if u is not None and u.pk not in seen:
            seen.add(u.pk)
            out.append(u)
    return out
