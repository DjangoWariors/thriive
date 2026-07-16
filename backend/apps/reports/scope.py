"""RBAC scope a report is allowed to read, frozen at request time.

Same precedence as core.scoping: a user placed in the hierarchy sees only their
own entity subtree; a standalone admin/finance account with a read-any level sees
everything; anyone else sees nothing.
"""
from dataclasses import dataclass

from apps.core.permissions import highest_level

_UNSCOPED_LEVELS = frozenset(('full', 'view_all', 'view_edit', 'view_readonly'))


@dataclass
class ReportScope:
    is_global: bool
    home_path: str | None
    home_entity_id: int | None

    def filter_entities(self, qs, path_field: str = 'path'):
        """Scope a queryset whose rows carry a materialized path — either Node
        rows ('path') or rows with an entity FK ('entity__path')."""
        if self.is_global:
            return qs
        if self.home_path:
            return qs.filter(**{f'{path_field}__startswith': self.home_path})
        return qs.none()

    def subtree_entity_ids(self):
        """Node ids in scope as a values() queryset, or None when global."""
        if self.is_global:
            return None
        from apps.hierarchy.models import Node
        if self.home_path:
            return Node.objects.filter(
                is_current=True, path__startswith=self.home_path).values('id')
        return Node.objects.none().values('id')

    def filter_entity_id(self, qs, field: str = 'entity_id'):
        """Scope a queryset whose entity reference is a plain id column, by resolving
        the subtree to a set of ids."""
        ids = self.subtree_entity_ids()
        if ids is None:
            return qs
        return qs.filter(**{f'{field}__in': ids})

    def attributed_node_ids(self):
        """Geography node ids in scope (owned territories, expanded to subtrees) as a
        list, or None when global. Sales attach to geography, so transaction reports
        scope by owned territory rather than by org subtree."""
        if self.is_global:
            return None
        if self.home_entity_id:
            from apps.assignments.services import AssignmentService
            return AssignmentService.scope_node_ids_for_entity(self.home_entity_id)
        return []

    def filter_attributed_node(self, qs, field: str = 'attributed_node_id'):
        """Scope a transaction queryset to the territories the requester owns."""
        ids = self.attributed_node_ids()
        if ids is None:
            return qs
        return qs.filter(**{f'{field}__in': ids})

    def to_snapshot(self) -> dict:
        return {
            'is_global': self.is_global,
            'home_path': self.home_path,
            'home_entity_id': self.home_entity_id,
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> 'ReportScope':
        return cls(
            is_global=data.get('is_global', False),
            home_path=data.get('home_path'),
            home_entity_id=data.get('home_entity_id'),
        )


def build_scope(user, required_permission: str | None) -> ReportScope:
    if getattr(user, 'is_superuser', False) or required_permission is None:
        return ReportScope(True, None, None)
    home = getattr(user, 'entity', None)
    if home is not None:
        return ReportScope(False, home.path, home.pk)
    if highest_level(user, required_permission) in _UNSCOPED_LEVELS:
        return ReportScope(True, None, None)
    return ReportScope(False, None, None)
