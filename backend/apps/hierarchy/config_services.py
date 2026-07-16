"""Service layer for hierarchy config & lookup models."""
from datetime import date

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Concat, Substr

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError

# The /entity-types/blueprint/ payload is read on many UI screens but only
# changes when an NodeType is created/versioned/deactivated. It is cached
# under this key and invalidated by NodeTypeService on every write.
ENTITY_TYPE_BLUEPRINT_CACHE_KEY = 'hierarchy:entity_type_blueprint'


def invalidate_entity_type_blueprint() -> None:
    cache.delete(ENTITY_TYPE_BLUEPRINT_CACHE_KEY)

from .models import (
    Channel,
    Node,
    NodeRelationship,
    NodeType,
    GeographyNode,
    GeographyType,
    RelationshipType,
)


def _apply(instance, data: dict) -> list[str]:
    """Assign validated_data onto a model instance; return changed field names."""
    changed = []
    for attr, val in data.items():
        if getattr(instance, attr, None) != val:
            changed.append(attr)
        setattr(instance, attr, val)
    return changed


def _assert_unique_code(model, code: str, *, exclude_pk=None) -> None:
    """Raise a clean BusinessError instead of a raw IntegrityError on duplicate codes."""
    qs = model.objects.filter(code=code)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise BusinessError(f"{model.__name__} code '{code}' already exists.")


class ChannelService:
    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> Channel:
        if data.get('code'):
            _assert_unique_code(Channel, data['code'])
        obj = Channel.objects.create(**data)
        AuditService.log('create', 'channel', obj.id, actor, {'code': obj.code, 'name': obj.name})
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: Channel, data: dict, actor=None) -> Channel:
        if 'code' in data and data['code'] != instance.code:
            _assert_unique_code(Channel, data['code'], exclude_pk=instance.pk)
        changed = _apply(instance, data)
        instance.save()
        AuditService.log('update', 'channel', instance.id, actor, {'fields': changed})
        return instance

    @staticmethod
    @transaction.atomic
    def deactivate(instance: Channel, actor=None) -> None:
        # Guard: a channel still assigned to live entities/types would be silently
        # orphaned (SET_NULL). Block and report so the operator reassigns first.
        entity_count = Node.objects.filter(
            channel=instance, is_current=True, is_active=True,
        ).count()
        type_count = NodeType.objects.filter(
            channel=instance, is_current=True, is_active=True,
        ).count()
        if entity_count or type_count:
            parts = []
            if entity_count:
                parts.append(f'{entity_count} active entit{"y" if entity_count == 1 else "ies"}')
            if type_count:
                parts.append(f'{type_count} entity type{"" if type_count == 1 else "s"}')
            raise BusinessError(
                f"Channel '{instance.code}' is still used by {' and '.join(parts)}. "
                'Reassign them before deactivating.'
            )
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'channel', instance.id, actor, {'is_active': False})


class NodeTypeService:
    """NodeType is versioned (VersionedMixin). Every update creates a new version
    so prior configurations are never lost."""

    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> NodeType:
        data.setdefault('effective_from', date.today())
        obj = NodeType.objects.create(**data)
        AuditService.log(
            'create', 'entity_type', obj.id, actor,
            {'code': obj.code, 'name': obj.name, 'version': obj.version},
        )
        invalidate_entity_type_blueprint()
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: NodeType, data: dict, actor=None) -> NodeType:
        changed = _apply(instance, data)
        instance.create_new_version()
        AuditService.log(
            'update', 'entity_type', instance.id, actor,
            {'fields': changed, 'new_version': instance.version},
        )
        invalidate_entity_type_blueprint()
        return instance

    @staticmethod
    @transaction.atomic
    def deactivate(instance: NodeType, actor=None) -> None:
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'entity_type', instance.id, actor, {'is_active': False})
        invalidate_entity_type_blueprint()


class GeographyTypeService:
    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> GeographyType:
        if data.get('code'):
            _assert_unique_code(GeographyType, data['code'])
        obj = GeographyType.objects.create(**data)
        AuditService.log('create', 'geography_type', obj.id, actor, {'code': obj.code, 'name': obj.name})
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: GeographyType, data: dict, actor=None) -> GeographyType:
        if 'code' in data and data['code'] != instance.code:
            _assert_unique_code(GeographyType, data['code'], exclude_pk=instance.pk)
        changed = _apply(instance, data)
        instance.save()
        AuditService.log('update', 'geography_type', instance.id, actor, {'fields': changed})
        return instance

    @staticmethod
    @transaction.atomic
    def deactivate(instance: GeographyType, actor=None) -> None:
        node_count = GeographyNode.objects.filter(geography_type=instance, is_active=True).count()
        if node_count:
            raise BusinessError(
                f"Geography '{instance.code}' still has {node_count} active "
                f'node{"" if node_count == 1 else "s"}. Remove them before deactivating.'
            )
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'geography_type', instance.id, actor, {'is_active': False})


def _validate_geo_placement(geo_type: GeographyType, level: str, parent: 'GeographyNode | None') -> None:
    """Enforce the configured level ordering for a geography node.

    - ``level`` must be one of ``geo_type.levels``.
    - A parent must belong to the SAME geography type and sit at a SHALLOWER level
      (an earlier entry in ``levels``) than the child.
    """
    levels = list(geo_type.levels or [])
    if levels and level not in levels:
        raise BusinessError(
            f"Level '{level}' is not defined for geography '{geo_type.code}'. "
            f'Allowed levels: {", ".join(levels) or "(none configured)"}.'
        )
    if parent is None:
        return
    if parent.geography_type_id != geo_type.id:
        raise BusinessError('Parent node belongs to a different geography type.')
    if levels:
        if parent.level not in levels:
            raise BusinessError(f"Parent level '{parent.level}' is not valid for this geography.")
        if levels.index(level) <= levels.index(parent.level):
            raise BusinessError(
                f"A '{level}' node must sit below its parent '{parent.level}' in the geography."
            )


class GeographyNodeService:
    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> GeographyNode:
        geo_type = data['geography_type']
        _validate_geo_placement(geo_type, data.get('level', ''), data.get('parent'))
        # GeographyNode.save() computes the materialized path/depth.
        obj = GeographyNode.objects.create(**data)
        AuditService.log('create', 'geography_node', obj.id, actor, {'code': obj.code, 'name': obj.name})
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: GeographyNode, data: dict, actor=None) -> GeographyNode:
        geo_type = data.get('geography_type', instance.geography_type)
        level = data.get('level', instance.level)
        parent = data['parent'] if 'parent' in data else instance.parent
        _validate_geo_placement(geo_type, level, parent)
        changed = _apply(instance, data)
        instance.save()
        AuditService.log('update', 'geography_node', instance.id, actor, {'fields': changed})
        return instance

    @staticmethod
    @transaction.atomic
    def move(node_id: int, new_parent_id: int | None, actor=None) -> GeographyNode:
        """Reparent a geography node, recomputing path/depth for it and all descendants.

        Mirrors NodeService.move_entity: prevents cycles, re-validates level ordering,
        prefix-rewrites every descendant path, and audits the move.
        """
        node = GeographyNode.objects.select_for_update().get(pk=node_id, is_active=True)
        new_parent = None
        if new_parent_id is not None:
            new_parent = GeographyNode.objects.get(pk=new_parent_id, is_active=True)
            if new_parent_id == node_id:
                raise BusinessError('A node cannot be its own parent.')
            if new_parent.path.startswith(node.path):
                raise BusinessError(
                    'Cannot move a node under one of its own descendants (circular reference).'
                )

        _validate_geo_placement(node.geography_type, node.level, new_parent)

        old_path = node.path
        old_parent_id = node.parent_id
        old_depth = node.depth

        node.parent = new_parent
        node.save()

        new_path = node.path
        depth_delta = node.depth - old_depth

        # Set-based prefix rewrite (mirrors NodeService.move_entity) — never
        # materializes the subtree, so moving a region with 50k outlets is one UPDATE.
        descendants_moved = (
            GeographyNode.objects
            .filter(path__startswith=old_path)
            .exclude(pk=node.pk)
            .update(
                path=Concat(Value(new_path), Substr('path', len(old_path) + 1)),
                depth=F('depth') + depth_delta,
            )
        )

        AuditService.log(
            'move', 'geography_node', node.id, actor,
            {
                'parent_id': [old_parent_id, new_parent_id],
                'path': [old_path, new_path],
                'descendants_moved': descendants_moved,
            },
        )
        return node

    @staticmethod
    @transaction.atomic
    def bulk_import(data: str | list, fmt: str, user, dry_run: bool = False) -> dict:
        """Import geography nodes from CSV text or a JSON list.

        Columns: geography_type_code, name, code, parent_code, level,
        attributes_json (optional). A parent may be an existing node or an
        earlier/later row in the same batch (rows are topologically sorted).
        All-or-nothing: any row error rolls back the whole batch.
        """
        import csv as _csv
        import io as _io
        import json as _json

        from .services import NodeService, validate_attribute_values

        if fmt == 'csv':
            rows = list(_csv.DictReader(_io.StringIO(data)))
        elif fmt == 'json':
            rows = _json.loads(data) if isinstance(data, str) else data
        else:
            raise BusinessError(f"Unsupported import format: '{fmt}'. Use 'csv' or 'json'.")

        def _cell(row, key):
            return str(row.get(key) or '').strip()

        type_cache: dict[str, GeographyType | None] = {}
        # Pre-index every row so a parent_code may reference a LATER row in the file.
        batch_index: dict[str, tuple[str, str]] = {
            str(r.get('code') or '').strip(): (
                str(r.get('geography_type_code') or '').strip(),
                str(r.get('level') or '').strip(),
            )
            for r in rows if str(r.get('code') or '').strip()
        }
        # One query for every code/parent_code named in the file — the row loop
        # then never touches the DB (150k-row files would otherwise seq-query per row).
        file_codes = {str(r.get('code') or '').strip() for r in rows}
        file_codes |= {str(r.get('parent_code') or '').strip() for r in rows}
        file_codes.discard('')
        existing_nodes: dict[str, GeographyNode] = {
            gn.code: gn for gn in GeographyNode.objects.filter(
                code__in=file_codes, is_active=True,
            )
        } if file_codes else {}

        seen_codes: set[str] = set()
        validation_errors: list[dict] = []
        normalised: list[dict] = []

        for i, row in enumerate(rows, start=1):
            row_errors: list[str] = []

            gt_code = _cell(row, 'geography_type_code')
            if gt_code not in type_cache:
                type_cache[gt_code] = GeographyType.objects.filter(
                    code=gt_code, is_active=True,
                ).first() if gt_code else None
            geo_type = type_cache[gt_code]
            if geo_type is None:
                row_errors.append(
                    f"geography_type_code '{gt_code}' not found." if gt_code
                    else 'geography_type_code is required.'
                )

            name = _cell(row, 'name')
            if not name:
                row_errors.append('name is required.')

            code = _cell(row, 'code')
            if not code:
                row_errors.append('code is required.')
            elif code in seen_codes:
                row_errors.append(f"Duplicate code '{code}' within this file.")
            elif code in existing_nodes:
                row_errors.append(f"A territory with code '{code}' already exists.")

            level = _cell(row, 'level')
            levels = list(geo_type.levels or []) if geo_type else []
            if geo_type and level not in levels:
                row_errors.append(
                    f"Level '{level}' is not defined for geography '{geo_type.code}'. "
                    f'Allowed: {", ".join(levels)}.'
                )

            parent_code = _cell(row, 'parent_code') or None
            if parent_code and geo_type and level in levels:
                parent_level = None
                if parent_code in batch_index and parent_code != code:
                    p_type_code, p_level = batch_index[parent_code]
                    if p_type_code != gt_code:
                        row_errors.append(f"Parent '{parent_code}' belongs to a different geography type.")
                    else:
                        parent_level = p_level
                else:
                    parent = existing_nodes.get(parent_code)
                    if parent is None:
                        row_errors.append(f"parent_code '{parent_code}' not found (in the file or the database).")
                    elif parent.geography_type_id != geo_type.pk:
                        row_errors.append(f"Parent '{parent_code}' belongs to a different geography type.")
                    else:
                        parent_level = parent.level
                if parent_level is not None and parent_level in levels \
                        and levels.index(level) <= levels.index(parent_level):
                    row_errors.append(
                        f"A '{level}' node must sit below its parent's level '{parent_level}'."
                    )

            attrs: dict = {}
            raw_attrs = _cell(row, 'attributes_json')
            if raw_attrs:
                try:
                    attrs = _json.loads(raw_attrs)
                except _json.JSONDecodeError:
                    row_errors.append('attributes_json is not valid JSON.')
            if geo_type and attrs:
                row_errors.extend(validate_attribute_values(geo_type.attribute_schema or [], attrs))

            if row_errors:
                validation_errors.append({'row': i, 'errors': row_errors})
            if code:
                seen_codes.add(code)
            normalised.append({
                'geography_type': geo_type, 'name': name, 'code': code,
                'parent_code': parent_code, 'level': level, 'attributes': attrs,
            })

        if validation_errors:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': validation_errors}

        try:
            sorted_rows = NodeService._topological_sort(normalised)
        except BusinessError as exc:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': [{'row': 0, 'errors': [str(exc)]}]}

        if dry_run:
            transaction.set_rollback(True)
            return {'status': 'valid', 'rows': len(normalised), 'would_create': len(normalised)}

        created: dict[str, GeographyNode] = {}
        for row in sorted_rows:
            parent = None
            if row['parent_code']:
                parent = created.get(row['parent_code']) or existing_nodes.get(row['parent_code'])
            node = GeographyNodeService.create(
                {
                    'geography_type': row['geography_type'], 'name': row['name'],
                    'code': row['code'], 'level': row['level'], 'parent': parent,
                    'attributes': row['attributes'],
                },
                actor=user,
            )
            created[node.code] = node

        return {'status': 'success', 'created': len(created)}

    @staticmethod
    @transaction.atomic
    def deactivate(instance: GeographyNode, actor=None) -> None:
        from apps.assignments.services import AssignmentService

        child_count = instance.children.filter(is_active=True).count()
        assignment_count = AssignmentService.assignments_for(instance).count()
        if child_count or assignment_count:
            parts = []
            if child_count:
                parts.append(f'{child_count} child node{"" if child_count == 1 else "s"}')
            if assignment_count:
                parts.append(f'{assignment_count} open assignment{"" if assignment_count == 1 else "s"}')
            raise BusinessError(
                f"Geography node '{instance.code}' still has {' and '.join(parts)}. "
                'Move or reassign them before deactivating.'
            )
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'geography_node', instance.id, actor, {'is_active': False})


class RelationshipTypeService:
    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> RelationshipType:
        obj = RelationshipType.objects.create(**data)
        AuditService.log('create', 'relationship_type', obj.id, actor, {'code': obj.code, 'name': obj.name})
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: RelationshipType, data: dict, actor=None) -> RelationshipType:
        changed = _apply(instance, data)
        instance.save()
        AuditService.log('update', 'relationship_type', instance.id, actor, {'fields': changed})
        return instance

    @staticmethod
    @transaction.atomic
    def deactivate(instance: RelationshipType, actor=None) -> None:
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'relationship_type', instance.id, actor, {'is_active': False})


class NodeRelationshipService:
    @staticmethod
    @transaction.atomic
    def create(data: dict, actor=None) -> NodeRelationship:
        obj = NodeRelationship.objects.create(**data)
        AuditService.log(
            'create', 'entity_relationship', obj.id, actor,
            {
                'type': obj.relationship_type_id,
                'from': obj.from_entity_id,
                'to': obj.to_entity_id,
            },
        )
        return obj

    @staticmethod
    @transaction.atomic
    def update(instance: NodeRelationship, data: dict, actor=None) -> NodeRelationship:
        changed = _apply(instance, data)
        instance.save()
        AuditService.log('update', 'entity_relationship', instance.id, actor, {'fields': changed})
        return instance

    @staticmethod
    @transaction.atomic
    def end(instance: NodeRelationship, actor=None) -> None:
        """End a lateral relationship: set effective_to=today and deactivate."""
        instance.effective_to = date.today()
        instance.is_active = False
        instance.save(update_fields=['effective_to', 'is_active'])
        AuditService.log(
            'delete', 'entity_relationship', instance.id, actor,
            {'effective_to': str(instance.effective_to)},
        )
