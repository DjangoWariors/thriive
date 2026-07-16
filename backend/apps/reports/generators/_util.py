"""Shared lookups for generators — batch id→label resolution to avoid N+1."""
from apps.hierarchy.models import Node


def entity_label_map(entity_ids) -> dict[int, str]:
    ids = {i for i in entity_ids if i is not None}
    if not ids:
        return {}
    rows = Node.objects.filter(pk__in=ids).select_related('entity_type').only(
        'id', 'name', 'code', 'entity_type__name')
    return {e.pk: f'{e.name} ({e.code})' for e in rows}


def node_label_map(node_ids) -> dict[int, str]:
    """id→label for geography nodes (sales attach to geography, not people)."""
    from apps.hierarchy.models import GeographyNode
    ids = {i for i in node_ids if i is not None}
    if not ids:
        return {}
    rows = GeographyNode.objects.filter(pk__in=ids).only('id', 'name', 'code')
    return {n.pk: f'{n.name} ({n.code})' for n in rows}


def entity_type_map(entity_ids) -> dict[int, str]:
    ids = {i for i in entity_ids if i is not None}
    if not ids:
        return {}
    rows = Node.objects.filter(pk__in=ids).select_related('entity_type').only(
        'id', 'entity_type__name')
    return {e.pk: e.entity_type.name for e in rows}


def user_label_map(user_ids) -> dict[int, str]:
    from apps.accounts.models import User
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    out = {}
    for u in User.objects.filter(pk__in=ids).only('id', 'first_name', 'last_name', 'email'):
        out[u.pk] = f'{u.first_name} {u.last_name}'.strip() or u.email or f'User #{u.pk}'
    return out
