"""
NodeService — all business logic for hierarchy entities.
"""
import csv
import io
import json
import re
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, IntegerField, Max, Value
from django.db.models.functions import Cast, Concat, Substr

from apps.assignments.services import AssignmentService
from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType

# Reserved bulk-import/export column names — everything else maps to attributes.
_RESERVED_IMPORT_COLUMNS = frozenset({
    'entity_type_code', 'name', 'code', 'parent_code', 'channel_code',
    'geography_node_code', 'status', 'path', 'attributes', 'attributes_json',
})


def validate_attribute_values(schema: list, attributes: dict) -> list[str]:
    """Type/format validation of an attributes dict against an attribute_schema.

    Pure — no DB access and no uniqueness checks (callers layer those on against their own
    model). Shared by NodeService (against Node) and GeographyService (against GeographyNode).
    """
    errors: list[str] = []
    for field in schema or []:
        key: str = field['key']
        label: str = field.get('label', key)
        field_type: str = field.get('type', 'string')
        required: bool = bool(field.get('required', False))
        value = attributes.get(key)

        if required and (value is None or value == ''):
            errors.append(f'{label} is required.')
            continue

        if value is None or value == '':
            continue

        if field_type == 'string':
            if not isinstance(value, str):
                errors.append(f'{label} must be a string.')
            else:
                min_len = field.get('min')
                max_len = field.get('max')
                pattern = field.get('pattern')
                if min_len is not None and len(value) < int(min_len):
                    errors.append(f'{label} must be at least {min_len} characters.')
                if max_len is not None and len(value) > int(max_len):
                    errors.append(f'{label} must be at most {max_len} characters.')
                if pattern and not re.match(pattern, value):
                    errors.append(f'{label} format is invalid.')

        elif field_type == 'integer':
            if isinstance(value, bool) or not isinstance(value, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    errors.append(f'{label} must be an integer.')
                    continue
            min_val = field.get('min')
            max_val = field.get('max')
            if min_val is not None and value < int(min_val):
                errors.append(f'{label} must be at least {min_val}.')
            if max_val is not None and value > int(max_val):
                errors.append(f'{label} must be at most {max_val}.')

        elif field_type == 'decimal':
            try:
                d = Decimal(str(value))
                min_val = field.get('min')
                max_val = field.get('max')
                if min_val is not None and d < Decimal(str(min_val)):
                    errors.append(f'{label} must be at least {min_val}.')
                if max_val is not None and d > Decimal(str(max_val)):
                    errors.append(f'{label} must be at most {max_val}.')
            except InvalidOperation:
                errors.append(f'{label} must be a valid decimal number.')

        elif field_type == 'date':
            try:
                import datetime as _dt
                _dt.datetime.strptime(str(value), '%Y-%m-%d')
            except ValueError:
                errors.append(f'{label} must be a valid date in YYYY-MM-DD format.')

        elif field_type == 'boolean':
            if not isinstance(value, bool):
                errors.append(f'{label} must be true or false.')

        elif field_type == 'choice':
            options = field.get('options', [])
            if value not in options:
                readable = ', '.join(str(o) for o in options)
                errors.append(f'{label} must be one of: {readable}.')

        elif field_type == 'email':
            if not isinstance(value, str) or '@' not in value:
                errors.append(f'{label} must be a valid email address.')

        elif field_type == 'phone':
            digits = ''.join(c for c in str(value) if c.isdigit())
            if len(digits) < 7:
                errors.append(f'{label} must be a valid phone number (at least 7 digits).')

    return errors


class GeographyService:

    @staticmethod
    def validate_attributes(geography_type: GeographyType, attributes: dict,
                             exclude_node_id: int | None = None) -> list[str]:
        """Validate a node's attributes against geography_type.attribute_schema (type/format +
        uniqueness against other GeographyNodes of the same type)."""
        schema = geography_type.attribute_schema or []
        errors = validate_attribute_values(schema, attributes)
        if errors:
            return errors

        for field in schema:
            if not field.get('unique'):
                continue
            key = field['key']
            value = attributes.get(key)
            if value is None or value == '':
                continue
            qs = GeographyNode.objects.filter(
                geography_type=geography_type, is_active=True, **{f'attributes__{key}': value},
            )
            if exclude_node_id is not None:
                qs = qs.exclude(pk=exclude_node_id)
            if qs.exists():
                errors.append(f'{field.get("label", key)} value "{value}" is already in use.')

        return errors


class NodeService:

    @staticmethod
    def validate_attributes(entity_type: NodeType, attributes: dict,
                             exclude_entity_id: int | None = None) -> list[str]:
        """
        Validate a dict of attributes against entity_type.attribute_schema.
        """
        schema = entity_type.attribute_schema or []
        errors = validate_attribute_values(schema, attributes)
        if errors:
            return errors

        for field in schema:
            if not field.get('unique'):
                continue
            key = field['key']
            value = attributes.get(key)
            if value is None or value == '':
                continue
            qs = Node.objects.filter(
                entity_type=entity_type, is_current=True, is_active=True,
                **{f'attributes__{key}': value},
            )
            if exclude_entity_id is not None:
                qs = qs.exclude(pk=exclude_entity_id)
            if qs.exists():
                errors.append(f'{field.get("label", key)} value "{value}" is already in use.')

        return errors


    @staticmethod
    def _validate_placement(child_type: NodeType, parent: 'Node | None') -> list[str]:
        """
        Validate that an entity of ``child_type`` may sit under ``parent``
        """
        errors: list[str] = []

        if parent is None:
            if child_type.allowed_parent_types:
                errors.append(
                    f"'{child_type.code}' requires a parent of type: "
                    f"{child_type.allowed_parent_types}."
                )
            return errors

        parent_type = parent.entity_type
        parent_code = parent_type.code if parent_type else ''

        if child_type.is_root_type:
            errors.append(f"'{child_type.code}' is a root type and cannot have a parent.")

        if parent_type and parent_type.is_leaf:
            errors.append(f"'{parent_code}' is a leaf type and cannot have children.")

        if child_type.allowed_parent_types and parent_code not in child_type.allowed_parent_types:
            errors.append(
                f"Parent type '{parent_code}' is not allowed for '{child_type.code}'. "
                f"Allowed: {child_type.allowed_parent_types}."
            )

        if (parent_type and parent_type.allowed_child_types
                and child_type.code not in parent_type.allowed_child_types):
            errors.append(
                f"'{parent_code}' does not allow children of type '{child_type.code}'. "
                f"Allowed: {parent_type.allowed_child_types}."
            )

        return errors

    @staticmethod
    def _generate_entity_code(entity_type) -> str:
        """Generate a stable, geography-independent key: ``{TYPE}-{NNNN}`` (e.g. ASM-0007).

        Geography is deliberately NOT embedded — ``code`` is immutable and lives inside
        the materialized ``path``, while geography changes on every transfer. The readable
        role+geography string is a computed ``display_code`` on the serializer, not this key.
        Server-side generation guarantees uniqueness (a name-derived slug collides).
        """
        prefix = entity_type.code.upper()
        # DB-side max: the regex excludes non-numeric suffixes BEFORE the cast, so at
        # 150k retailers this is one index-ranged aggregate, not a Python scan of all codes.
        start = len(prefix) + 2  # Substr is 1-indexed; skip "PREFIX-"
        max_n = (
            Node.objects
            .filter(code__startswith=f'{prefix}-')
            .filter(code__regex=rf'^{re.escape(prefix)}-\d+$')
            .annotate(n=Cast(Substr('code', start), IntegerField()))
            .aggregate(m=Max('n'))['m']
            or 0
        )
        return f'{prefix}-{max_n + 1:04d}'

    @staticmethod
    @transaction.atomic
    def create_entity(data: dict, user) -> Node:
        """
        Create a new Node (version 1, is_current=True).
        """
        from apps.accounts.models import User, UserRole

        today = date.today()
        entity_type_id = data.get('entity_type_id')
        parent_id = data.get('parent_id')
        attributes = data.get('attributes') or {}


        try:
            entity_type = NodeType.objects.select_related('default_role').get(
                pk=entity_type_id, is_current=True, is_active=True,
            )
        except NodeType.DoesNotExist:
            raise BusinessError(f'NodeType {entity_type_id} not found or not current.')

        parent: Node | None = None
        if parent_id:
            try:
                parent = Node.objects.select_related('entity_type').get(
                    pk=parent_id, is_current=True, is_active=True,
                )
            except Node.DoesNotExist:
                raise BusinessError(f'Parent entity {parent_id} not found or not current.')

        placement_errors = NodeService._validate_placement(entity_type, parent)
        if placement_errors:
            raise BusinessError('; '.join(placement_errors))

        attr_errors = NodeService.validate_attributes(entity_type, attributes)
        if attr_errors:
            raise BusinessError('; '.join(attr_errors))

        code: str = (data.get('code') or '').strip()
        auto_code = not code
        if not code:
            code = NodeService._generate_entity_code(entity_type)
        if Node.objects.filter(code=code, is_current=True, is_active=True).exists():
            raise BusinessError(f"Node with code '{code}' already exists.")
        status = data.get('status') or 'active'
        # Concurrent creates can race to the same auto-generated number; the
        # (code, version) unique constraint backstops it — regenerate and retry
        # under a savepoint so the outer transaction survives.
        for attempt in range(3):
            entity = Node(
                entity_type=entity_type,
                name=data['name'],
                code=code,
                parent=parent,
                attributes=attributes,
                channel_id=data.get('channel_id'),
                status=status,
                effective_from=data.get('effective_from') or today,
                version=1,
                is_current=True,
            )
            try:
                with transaction.atomic():
                    entity.save()
                break
            except IntegrityError:
                if not auto_code or attempt == 2:
                    raise BusinessError(f"Node with code '{code}' already exists.")
                code = NodeService._generate_entity_code(entity_type)

        # Territory coverage is an owner Assignment from day one — never a static FK.
        for scope_id in (data.get('owned_scope_ids') or []):
            AssignmentService.create(
                assignee_id=entity.pk, scope_id=scope_id,
                effective_from=data.get('effective_from') or today,
                reason='Assigned at creation', user=user,
            )

        # A 'vacant' seat is a position with no incumbent yet — skip user creation.
        # It can later be filled by TransferService.transfer_person (occupy_vacant).
        if entity_type.is_loginable and status != 'vacant':
            login_method = entity_type.display_config.get('login_method', 'password_and_otp')

            email = attributes.get('email') or data.get('email') or None
            mobile = str(attributes.get('mobile', '') or data.get('mobile', '') or '').strip() or None
            employee_id = str(attributes.get('employee_id', '') or data.get('employee_id', '') or '').strip() or None

            if not any([email, mobile, employee_id]):
                raise BusinessError(
                    f"Loginable entity type '{entity_type.code}' requires at least one of: "
                    "email, mobile, or employee_id in attributes."
                )

            # Surface duplicate login details as a clear validation error rather than a
            # raw DB IntegrityError (accounts_user.{email,mobile,employee_id} are unique).
            dupes = []
            if email and User.objects.filter(email__iexact=email).exists():
                dupes.append(f"email '{email}'")
            if mobile and User.objects.filter(mobile=mobile).exists():
                dupes.append(f"mobile '{mobile}'")
            if employee_id and User.objects.filter(employee_id=employee_id).exists():
                dupes.append(f"employee ID '{employee_id}'")
            if dupes:
                raise BusinessError(
                    f"A user with this {', and '.join(dupes)} already exists. "
                    "Use different login details, or edit the existing record instead."
                )

            name_parts = entity.name.split()
            first_name = name_parts[0] if name_parts else entity.name
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

            linked_user = User(
                email=email,
                mobile=mobile,
                employee_id=employee_id,
                first_name=first_name,
                last_name=last_name,
            )

            password = (data.get('password') or '').strip()
            if password and login_method in ('password_and_otp', 'password_only'):
                try:
                    validate_password(password, user=linked_user)
                except DjangoValidationError as exc:
                    raise BusinessError('; '.join(exc.messages))
                linked_user.set_password(password)
            else:
                # OTP-only types, or no password given yet ("set it later").
                linked_user.set_unusable_password()
            linked_user.save()
            if entity_type.default_role:
                UserRole.objects.create(
                    user=linked_user,
                    role=entity_type.default_role,
                    effective_from=today,
                )

            linked_user.entity = entity
            linked_user.save(update_fields=['entity'])

        AuditService.log(
            action='create',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={
                'code': entity.code,
                'name': entity.name,
                'entity_type': entity_type.code,
                'parent_id': parent.pk if parent else None,
                'path': entity.path,
            },
        )

        return entity


    @staticmethod
    @transaction.atomic
    def update_entity(entity_id: int, data: dict, user) -> Node:
        """
        Update an existing entity's editable fields and, for loginable types,
        propagate email/mobile changes to the linked User.

        Code, parent, and entity type are NOT updatable here (code/parent affect
        the materialized path — use move_entity). Attributes are validated against
        the entity type schema. Returns the refreshed entity.
        """
        from django.core.exceptions import ObjectDoesNotExist

        from apps.accounts.models import User

        entity = Node.objects.select_related('entity_type').get(
            pk=entity_id, is_current=True, is_active=True,
        )
        entity_type = entity.entity_type
        changed: list[str] = []

        if 'name' in data and data['name'] != entity.name:
            entity.name = data['name']
            changed.append('name')

        if 'attributes' in data and data['attributes'] is not None:
            attrs = data['attributes']
            attr_errors = NodeService.validate_attributes(
                entity_type, attrs, exclude_entity_id=entity.pk,
            )
            if attr_errors:
                raise BusinessError('; '.join(attr_errors))
            if attrs != entity.attributes:
                entity.attributes = attrs
                changed.append('attributes')

        if 'channel_id' in data and data['channel_id'] != entity.channel_id:
            entity.channel_id = data['channel_id']
            changed.append('channel')

        if changed:
            entity.save()

        # Propagate login identifiers to the linked User (loginable types only).
        user_changed: list[str] = []
        if entity_type and entity_type.is_loginable and (
                'email' in data or 'mobile' in data or 'password' in data):
            try:
                linked_user = entity.user
            except ObjectDoesNotExist:
                linked_user = None

            if linked_user is not None:
                if 'email' in data:
                    new_email = (data.get('email') or '').strip() or None
                    if new_email != linked_user.email:
                        if new_email and User.objects.filter(email=new_email).exclude(pk=linked_user.pk).exists():
                            raise BusinessError(f"Email '{new_email}' is already in use by another user.")
                        linked_user.email = new_email
                        user_changed.append('email')
                if 'mobile' in data:
                    new_mobile = (str(data.get('mobile') or '')).strip() or None
                    if new_mobile != linked_user.mobile:
                        if new_mobile and User.objects.filter(mobile=new_mobile).exclude(pk=linked_user.pk).exists():
                            raise BusinessError(f"Mobile '{new_mobile}' is already in use by another user.")
                        linked_user.mobile = new_mobile
                        user_changed.append('mobile')
                new_password = (data.get('password') or '').strip()
                if new_password:
                    login_method = entity_type.display_config.get('login_method', 'password_and_otp')
                    if login_method == 'otp_only':
                        raise BusinessError('This role type signs in with OTP only — it has no password.')
                    try:
                        validate_password(new_password, user=linked_user)
                    except DjangoValidationError as exc:
                        raise BusinessError('; '.join(exc.messages))
                    linked_user.set_password(new_password)
                    user_changed.append('password')
                if user_changed:
                    linked_user.save(update_fields=user_changed)

        AuditService.log(
            action='update',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={'fields': changed, 'user_fields': user_changed},
        )

        return entity

    @staticmethod
    @transaction.atomic
    def move_entity(entity_id: int, new_parent_id: int, reason: str,
                    effective_date: date, user) -> Node:
        """
        Move an entity to a new parent, recomputing path for the entity and all descendants.
        """
        entity = Node.objects.select_related('entity_type').select_for_update(of=('self',)).get(
            pk=entity_id, is_current=True, is_active=True,
        )
        new_parent = Node.objects.select_related('entity_type').get(
            pk=new_parent_id, is_current=True, is_active=True,
        )


        if entity_id == new_parent_id:
            raise BusinessError('An entity cannot be its own parent.')

        if new_parent.path.startswith(entity.path):
            raise BusinessError(
                'Cannot move an entity under one of its own descendants (circular reference).'
            )

        placement_errors = NodeService._validate_placement(entity.entity_type, new_parent)
        if placement_errors:
            raise BusinessError('; '.join(placement_errors))

        old_path = entity.path
        old_parent_id = entity.parent_id
        old_depth = entity.depth

        entity.parent = new_parent
        entity.save()

        new_path = entity.path
        depth_delta = entity.depth - old_depth


        children_moved = 0
        if old_path:
            # Rewrite every descendant's path in one set-based UPDATE — never pull the
            # subtree into Python. Postgres and SQLite both support || / SUBSTR, which
            # Concat/Substr compile to. SUBSTR is 1-indexed, so we start past the old
            # prefix (len(old_path) + 1) to keep the descendant's own tail.
            descendant_qs = Node.objects.filter(
                path__startswith=old_path,
                is_current=True,
            ).exclude(pk=entity.pk)
            children_moved = descendant_qs.update(
                path=Concat(Value(new_path), Substr('path', len(old_path) + 1)),
                depth=F('depth') + depth_delta,
            )

        AuditService.log(
            action='move',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={
                'parent_id': [old_parent_id, new_parent_id],
                'path':       [old_path,     new_path],
                'reason':     reason,
                'effective_date': str(effective_date),
                'children_moved': children_moved,
            },
        )

        return entity

    @staticmethod
    @transaction.atomic
    def change_entity_type(entity_id: int, new_type_id: int, new_parent_id: int | None,
                           attributes: dict | None, reason: str, effective_date: date, user,
                           reassign_reports_to: int | None = None) -> Node:
        """
        Change an entity's type in place (e.g. promote ASM → RSM), keeping the same
        entity/User id so the person, login and relationships stay continuous.

        Validates the new placement (both-direction type rules + root/leaf),
        re-validates attributes against the NEW type's schema, handles existing
        direct reports, swaps the linked User's default role, and audits the change.

        """
        from django.core.exceptions import ObjectDoesNotExist
        from apps.accounts.models import UserRole

        entity = Node.objects.select_related('entity_type', 'parent').select_for_update(of=('self',)).get(
            pk=entity_id, is_current=True, is_active=True,
        )
        old_type = entity.entity_type

        try:
            new_type = NodeType.objects.select_related('default_role').get(
                pk=new_type_id, is_current=True, is_active=True,
            )
        except NodeType.DoesNotExist:
            raise BusinessError(f'NodeType {new_type_id} not found or not current.')

        if old_type and old_type.pk == new_type.pk:
            raise BusinessError('New type is the same as the current type.')

        new_parent: Node | None = None
        if new_parent_id:
            new_parent = Node.objects.select_related('entity_type').get(
                pk=new_parent_id, is_current=True, is_active=True,
            )
            if new_parent.pk == entity.pk:
                raise BusinessError('An entity cannot be its own parent.')
            if new_parent.path.startswith(entity.path):
                raise BusinessError('Cannot move an entity under one of its own descendants.')

        placement_errors = NodeService._validate_placement(new_type, new_parent)
        if placement_errors:
            raise BusinessError('; '.join(placement_errors))

        attrs = attributes if attributes is not None else entity.attributes
        attr_errors = NodeService.validate_attributes(new_type, attrs, exclude_entity_id=entity.pk)
        if attr_errors:
            raise BusinessError('; '.join(attr_errors))

        # Handle existing direct reports.
        children = list(entity.get_direct_children().select_related('entity_type'))
        if children:
            if reassign_reports_to is not None:
                target = Node.objects.select_related('entity_type').get(
                    pk=reassign_reports_to, is_current=True, is_active=True,
                )
                if target.pk == entity.pk:
                    raise BusinessError('Cannot reassign reports to the entity being changed.')
                for ch in children:
                    errs = NodeService._validate_placement(ch.entity_type, target)
                    if errs:
                        raise BusinessError(f"Cannot reassign '{ch.code}' to '{target.code}': {'; '.join(errs)}")
                for ch in children:
                    NodeService.move_entity(
                        ch.pk, target.pk,
                        reason=f'Reassigned during type change of {entity.code}',
                        effective_date=effective_date, user=user,
                    )
            else:
                invalid = []
                for ch in children:
                    ct = ch.entity_type
                    bad = (
                        new_type.is_leaf
                        or (ct and ct.allowed_parent_types and new_type.code not in ct.allowed_parent_types)
                        or (new_type.allowed_child_types and ct and ct.code not in new_type.allowed_child_types)
                    )
                    if bad:
                        invalid.append(ch.code)
                if invalid:
                    raise BusinessError(
                        f"{len(invalid)} report(s) are not valid under '{new_type.code}': {invalid}. "
                        'Reassign them (reassign_reports_to) or change their type first.'
                    )

        old_parent_id = entity.parent_id
        old_path = entity.path
        old_depth = entity.depth

        entity.entity_type = new_type
        entity.parent = new_parent
        if attributes is not None:
            entity.attributes = attrs
        entity.save()

        # Recompute paths for any carried descendants if the path changed.
        new_path = entity.path
        if old_path != new_path:
            depth_delta = entity.depth - old_depth
            old_len = len(old_path)
            descendants = list(
                Node.objects.filter(path__startswith=old_path, is_current=True).exclude(pk=entity.pk)
            )
            for desc in descendants:
                desc.path = new_path + desc.path[old_len:]
                desc.depth = desc.depth + depth_delta
            if descendants:
                Node.objects.bulk_update(descendants, ['path', 'depth'])

        # Swap the linked user's default role (old type's → new type's).
        try:
            linked_user = entity.user
        except ObjectDoesNotExist:
            linked_user = None
        if linked_user is not None:
            if old_type and old_type.default_role_id:
                UserRole.objects.filter(
                    user=linked_user, role_id=old_type.default_role_id, is_active=True,
                ).update(is_active=False)
            if new_type.default_role_id:
                ur, _ = UserRole.objects.get_or_create(
                    user=linked_user, role_id=new_type.default_role_id,
                    defaults={'effective_from': effective_date},
                )
                if not ur.is_active:
                    ur.is_active = True
                    ur.save(update_fields=['is_active'])

        AuditService.log(
            action='promote',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={
                'entity_type': [old_type.code if old_type else None, new_type.code],
                'parent_id': [old_parent_id, new_parent_id],
                'reason': reason,
                'effective_date': str(effective_date),
                'reports_reassigned_to': reassign_reports_to,
            },
        )

        return entity

    @staticmethod
    @transaction.atomic
    def deactivate_entity(entity_id: int, reason: str, user) -> Node:
        """
        Soft-deactivate an entity. Blocks if active children exist.
        Cascades deactivation to the linked User and open NodeRelationships.
        """
        from django.core.exceptions import ObjectDoesNotExist
        from apps.hierarchy.models import NodeRelationship

        entity = Node.objects.select_related('entity_type').get(
            pk=entity_id, is_current=True, is_active=True,
        )

        if entity.get_direct_children().exists():
            raise BusinessError(
                'Cannot deactivate an entity that has active children. '
                'Move or deactivate children first.'
            )

        entity.status = 'inactive'
        entity.save(update_fields=['status', 'updated_at'])

        try:
            linked_user = entity.user
            linked_user.is_active = False
            linked_user.save(update_fields=['is_active'])
        except ObjectDoesNotExist:
            pass

        today = date.today()
        NodeRelationship.objects.filter(
            effective_to__isnull=True,
        ).filter(
            models_q_from_or_to(entity.pk)
        ).update(effective_to=today)

        # An inactive seat must not keep owning territory — close its assignments.
        # Reactivation does NOT restore them; reassign explicitly.
        AssignmentService.end_all_for_assignee(
            entity.pk, effective_to=today, reason=f'Seat deactivated: {reason}', user=user,
        )

        AuditService.log(
            action='deactivate',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={'status': ['active', 'inactive'], 'reason': reason},
        )

        return entity

    @staticmethod
    @transaction.atomic
    def reactivate_entity(entity_id: int, reason: str, user) -> Node:
        """
        Reactivate a previously deactivated entity (status → active) and re-enable
        its linked User. Blocked if the parent is inactive — an active entity may
        not sit under an inactive one. Ended relationships are NOT auto-restored.
        """
        from django.core.exceptions import ObjectDoesNotExist

        entity = Node.objects.select_related('entity_type', 'parent').get(
            pk=entity_id, is_current=True, is_active=True,
        )

        if entity.status == 'active':
            raise BusinessError('Node is already active.')

        if entity.parent_id and entity.parent.status != 'active':
            raise BusinessError(
                'Cannot reactivate under an inactive parent. Reactivate the parent first.'
            )

        entity.status = 'active'
        entity.save(update_fields=['status', 'updated_at'])

        try:
            linked_user = entity.user
            if not linked_user.is_active:
                linked_user.is_active = True
                linked_user.save(update_fields=['is_active'])
        except ObjectDoesNotExist:
            pass

        AuditService.log(
            action='reactivate',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={'status': ['inactive', 'active'], 'reason': reason},
        )

        return entity

    @staticmethod
    @transaction.atomic
    def bulk_move(entity_ids: list[int], new_parent_id: int, reason: str,
                  effective_date: date, user) -> dict:
        """
        Move many entities under one new parent. All-or-nothing: every entity is
        validated first; if any fails, nothing moves and a per-entity error list
        is returned. Each successful move reuses move_entity (path recompute +
        per-entity audit).
        """
        new_parent = Node.objects.select_related('entity_type').filter(
            pk=new_parent_id, is_current=True, is_active=True,
        ).first()
        if new_parent is None:
            raise BusinessError(f'New parent {new_parent_id} not found or not current.')

        entities = list(
            Node.objects.select_related('entity_type').filter(
                pk__in=entity_ids, is_current=True, is_active=True,
            )
        )
        found = {e.pk: e for e in entities}

        errors: list[dict] = []
        for eid in entity_ids:
            ent = found.get(eid)
            if ent is None:
                errors.append({'id': eid, 'errors': ['Node not found or not current.']})
                continue
            ent_errors: list[str] = []
            if ent.pk == new_parent_id:
                ent_errors.append('An entity cannot be its own parent.')
            if new_parent.path.startswith(ent.path):
                ent_errors.append('Cannot move an entity under one of its own descendants.')
            ent_errors.extend(NodeService._validate_placement(ent.entity_type, new_parent))
            if ent_errors:
                errors.append({'id': eid, 'errors': ent_errors})

        if errors:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': errors}

        for eid in entity_ids:
            NodeService.move_entity(eid, new_parent_id, reason, effective_date, user)

        return {'status': 'success', 'moved': len(entity_ids)}

    @staticmethod
    @transaction.atomic
    def bulk_deactivate(entity_ids: list[int], reason: str, user,
                        cascade: bool = False) -> dict:
        """
        Soft-deactivate many entities. All-or-nothing.

        cascade=False → an entity with active children is rejected, UNLESS those
                        children are also in this selection (so a parent + its
                        children can be deactivated together).
        cascade=True  → each selected entity and its entire subtree are
                        deactivated (linked users disabled, open relationships ended).
        """
        from django.core.exceptions import ObjectDoesNotExist
        from apps.hierarchy.models import NodeRelationship

        entities = list(
            Node.objects.select_related('entity_type').filter(
                pk__in=entity_ids, is_current=True, is_active=True,
            )
        )
        found = {e.pk: e for e in entities}
        selected_ids = set(found)

        errors: list[dict] = []
        for eid in entity_ids:
            if eid not in found:
                errors.append({'id': eid, 'errors': ['Node not found or not current.']})

        if not cascade:
            for ent in entities:
                child_ids = set(ent.get_direct_children().values_list('pk', flat=True))
                if child_ids - selected_ids:
                    errors.append({
                        'id': ent.pk,
                        'errors': ['Has active children not in selection; '
                                   'include them or use cascade.'],
                    })

        if errors:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': errors}

        # Build the full set of entities to deactivate (subtree when cascading).
        targets: dict[int, Node] = {}
        for ent in entities:
            targets[ent.pk] = ent
            if cascade:
                for desc in ent.get_subtree().select_related('entity_type'):
                    targets[desc.pk] = desc

        today = date.today()
        for ent in targets.values():
            if ent.status != 'inactive':
                ent.status = 'inactive'
                ent.save(update_fields=['status', 'updated_at'])
            try:
                linked_user = ent.user
                if linked_user.is_active:
                    linked_user.is_active = False
                    linked_user.save(update_fields=['is_active'])
            except ObjectDoesNotExist:
                pass
            NodeRelationship.objects.filter(
                effective_to__isnull=True,
            ).filter(models_q_from_or_to(ent.pk)).update(effective_to=today)
            AssignmentService.end_all_for_assignee(
                ent.pk, effective_to=today, reason=f'Seat deactivated: {reason}', user=user,
            )

            AuditService.log(
                action='deactivate',
                entity_type='hierarchy.Node',
                entity_id=ent.pk,
                user=user,
                changes={'status': ['active', 'inactive'], 'reason': reason, 'cascade': cascade},
            )

        return {'status': 'success', 'deactivated': len(targets)}

    @staticmethod
    @transaction.atomic
    def bulk_reactivate(entity_ids: list[int], reason: str, user) -> dict:
        """
        Reactivate many entities (status → active, linked users re-enabled).
        All-or-nothing. A child whose parent is inactive is rejected unless the
        parent is also in the selection; entities are reactivated parent-first
        (by depth). Already-active selections are skipped silently.
        """
        from django.core.exceptions import ObjectDoesNotExist

        entities = list(
            Node.objects.select_related('entity_type', 'parent').filter(
                pk__in=entity_ids, is_current=True, is_active=True,
            )
        )
        found = {e.pk: e for e in entities}
        selected_ids = set(found)

        errors: list[dict] = []
        for eid in entity_ids:
            if eid not in found:
                errors.append({'id': eid, 'errors': ['Node not found or not current.']})

        for ent in entities:
            if ent.status == 'active':
                continue
            if ent.parent_id and ent.parent.status != 'active' and ent.parent_id not in selected_ids:
                errors.append({
                    'id': ent.pk,
                    'errors': ['Parent is inactive; include it in the selection or reactivate it first.'],
                })

        if errors:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': errors}

        # Reactivate parents before children so the parent-active rule always holds.
        targets = sorted(
            (e for e in entities if e.status != 'active'),
            key=lambda e: e.depth,
        )
        for ent in targets:
            ent.status = 'active'
            ent.save(update_fields=['status', 'updated_at'])
            try:
                linked_user = ent.user
                if not linked_user.is_active:
                    linked_user.is_active = True
                    linked_user.save(update_fields=['is_active'])
            except ObjectDoesNotExist:
                pass
            AuditService.log(
                action='reactivate',
                entity_type='hierarchy.Node',
                entity_id=ent.pk,
                user=user,
                changes={'status': ['inactive', 'active'], 'reason': reason},
            )

        return {'status': 'success', 'reactivated': len(targets)}

    @staticmethod
    def _coerce(field_type: str, value):
        """Coerce a flat CSV cell (string) toward its schema type for storage."""
        if field_type == 'integer':
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        if field_type == 'boolean':
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ('true', '1', 'yes', 'y'):
                return True
            if s in ('false', '0', 'no', 'n'):
                return False
            return value
        if field_type == 'decimal':
            # Keep as string to preserve precision; validators accept Decimal(str(v)).
            return str(value).strip() if isinstance(value, str) else str(value)
        return value.strip() if isinstance(value, str) else value

    @staticmethod
    def _flat_attributes(entity_type: NodeType, row: dict) -> dict:
        """
        Build an attributes dict from flat per-field columns, keyed by the
        entity type's attribute_schema. Empty cells are omitted so required-field
        validation still fires. Used when no explicit `attributes` column exists.
        """
        attrs: dict = {}
        for field in (entity_type.attribute_schema or []):
            key = field.get('key')
            if not key or key not in row:
                continue
            raw = row.get(key)
            if raw is None:
                continue
            if isinstance(raw, str) and raw.strip() == '':
                continue
            attrs[key] = NodeService._coerce(field.get('type', 'string'), raw)
        return attrs

    _EXPORT_CHUNK = 2000

    @staticmethod
    def export_stream(queryset) -> tuple[list[str], 'Iterator[dict]']:
        """
        Build (fieldnames, row_iterator) for a CSV export of the given entity queryset.
        Reserved columns first, then one column per attribute key (ordered union
        across the entity types present). The output is a valid bulk-import file.

        Streams: fieldnames come from the DISTINCT entity types in the queryset
        (one small query), rows are yielded in chunks with one owner-map query
        per chunk — a 150k-entity export never materializes in memory.
        """
        type_codes = list(
            queryset.order_by().values_list('entity_type__code', flat=True).distinct()
        )
        attr_keys: list[str] = []
        seen_keys: set = set()
        for et in NodeType.objects.filter(code__in=type_codes, is_current=True):
            for field in (et.attribute_schema or []):
                key = field.get('key')
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    attr_keys.append(key)

        base_cols = [
            'entity_type_code', 'name', 'code', 'parent_code',
            'channel_code', 'geography_node_code', 'status', 'path',
        ]
        fieldnames = base_cols + attr_keys

        def _rows():
            chunk: list[Node] = []
            for ent in queryset.select_related('entity_type', 'parent', 'channel').iterator(
                    chunk_size=NodeService._EXPORT_CHUNK):
                chunk.append(ent)
                if len(chunk) >= NodeService._EXPORT_CHUNK:
                    yield from NodeService._export_chunk_rows(chunk, attr_keys)
                    chunk = []
            if chunk:
                yield from NodeService._export_chunk_rows(chunk, attr_keys)

        return fieldnames, _rows()

    @staticmethod
    def _export_chunk_rows(entities: list, attr_keys: list[str]):
        # geography_node_code = the scopes this entity currently owns (assignments,
        # '|'-separated) so an export round-trips through bulk_import losslessly.
        owner_map = AssignmentService.open_owner_scopes_map([e.pk for e in entities])
        for ent in entities:
            row = {
                'entity_type_code': ent.entity_type.code if ent.entity_type else '',
                'name': ent.name,
                'code': ent.code,
                'parent_code': ent.parent.code if ent.parent else '',
                'channel_code': ent.channel.code if ent.channel else '',
                'geography_node_code': '|'.join(
                    a.scope.code for a in owner_map.get(ent.pk, [])
                ),
                'status': ent.status,
                'path': ent.path,
            }
            attrs = ent.attributes or {}
            for key in attr_keys:
                val = attrs.get(key, '')
                row[key] = json.dumps(val) if isinstance(val, (dict, list)) else val
            yield row

    @staticmethod
    def import_template(entity_type: NodeType) -> tuple[list[str], dict]:
        """
        Build (fieldnames, sample_row) for an import template tailored to an
        entity type's attribute schema. Configurable — never hardcoded columns.
        """
        base_cols = [
            'entity_type_code', 'name', 'code',
            'parent_code', 'channel_code', 'geography_node_code',
        ]
        schema = entity_type.attribute_schema or []
        fieldnames = base_cols + [f['key'] for f in schema if f.get('key')]

        sample = {col: '' for col in fieldnames}
        sample['entity_type_code'] = entity_type.code
        sample['name'] = 'Sample Name'
        sample['code'] = 'SAMPLE_CODE'
        for field in schema:
            key = field.get('key')
            if not key:
                continue
            options = field.get('options')
            if field.get('type') == 'choice' and options:
                sample[key] = str(options[0])
            else:
                sample[key] = f"<{field.get('type', 'string')}>"
        return fieldnames, sample

    @staticmethod
    def _topological_sort(normalised: list[dict]) -> list[dict]:
        """
        Order rows so every parent (referenced by code within the batch) is
        created before its children. Raises BusinessError on a circular
        reference. Rows whose parent is outside the batch sort first.
        """
        batch_codes = {r['code'] for r in normalised}
        sorted_rows: list[dict] = []
        remaining = list(normalised)
        iterations = 0

        while remaining and iterations <= len(normalised):
            iterations += 1
            next_remaining = []
            for row in remaining:
                parent_code = row['parent_code']
                if (not parent_code
                        or parent_code not in batch_codes
                        or any(s['code'] == parent_code for s in sorted_rows)):
                    sorted_rows.append(row)
                else:
                    next_remaining.append(row)
            if len(next_remaining) == len(remaining):
                codes = [r['code'] for r in next_remaining]
                raise BusinessError(f'Circular parent references detected among: {codes}')
            remaining = next_remaining

        return sorted_rows

    @staticmethod
    @transaction.atomic
    def bulk_import(data: str | list, fmt: str, user, dry_run: bool = False) -> dict:
        """
        Import entities from CSV string or JSON list.
        All-or-nothing: if any row fails validation, nothing is created.
        When dry_run=True, every row is validated but nothing is ever written.
        """

        if fmt == 'csv':
            reader = csv.DictReader(io.StringIO(data))
            rows = list(reader)
        elif fmt == 'json':
            rows = json.loads(data) if isinstance(data, str) else data
        else:
            raise BusinessError(f"Unsupported import format: '{fmt}'. Use 'csv' or 'json'.")


        et_cache: dict = {}
        ch_cache: dict = {}
        validation_errors: list[dict] = []
        normalised: list[dict] = []

        def _code(row, key):
            return str(row.get(key) or '').strip()

        # Batch-prefetch every geography scope named in the file: one node query +
        # one owners query, instead of two queries per distinct code in the row loop.
        all_geo_codes: set[str] = set()
        for row in rows:
            cell = str(row.get('geography_node_code') or '').strip()
            all_geo_codes.update(c.strip() for c in cell.split('|') if c.strip())
        geo_cache: dict = {}
        if all_geo_codes:
            geo_nodes = {gn.code: gn for gn in GeographyNode.objects.filter(
                code__in=all_geo_codes, is_active=True)}
            owned_scopes = AssignmentService.owners_for_scopes(
                [gn.pk for gn in geo_nodes.values()])
            geo_cache = {
                code: {
                    'node': geo_nodes.get(code),
                    'owned': code in geo_nodes and geo_nodes[code].pk in owned_scopes,
                }
                for code in all_geo_codes
            }

        for i, row in enumerate(rows, start=1):
            row_errors: list[str] = []

            et_code = _code(row, 'entity_type_code')
            if not et_code:
                row_errors.append('entity_type_code is required.')
                entity_type = None
            else:
                if et_code not in et_cache:
                    et_cache[et_code] = NodeType.objects.filter(
                        code=et_code, is_current=True, is_active=True
                    ).first()
                entity_type = et_cache[et_code]
                if entity_type is None:
                    row_errors.append(f"NodeType code '{et_code}' not found.")

            ch_code = _code(row, 'channel_code') or None
            channel_id = None
            if ch_code:
                if ch_code not in ch_cache:
                    ch_cache[ch_code] = Channel.objects.filter(code=ch_code, is_active=True).first()
                ch = ch_cache[ch_code]
                if ch is None:
                    row_errors.append(f"Channel code '{ch_code}' not found.")
                else:
                    channel_id = ch.pk

            # geography_node_code = territory ownership: each '|'-separated code opens
            # an owner Assignment on that scope. One owner per scope — clashes with an
            # existing owner or an earlier row in this batch are validation errors.
            geo_cell = _code(row, 'geography_node_code')
            owned_scope_ids: list[int] = []
            for geo_code in filter(None, (c.strip() for c in geo_cell.split('|'))):
                cached = geo_cache[geo_code]  # prefetched above — every file code is present
                if cached['node'] is None:
                    row_errors.append(f"Geography node code '{geo_code}' not found.")
                elif cached['owned']:
                    row_errors.append(f"Territory '{geo_code}' already has an owner.")
                else:
                    cached['owned'] = True  # claimed by this row for the rest of the batch
                    owned_scope_ids.append(cached['node'].pk)


            raw_attrs = row.get('attributes')
            if raw_attrs is None:
                raw_attrs = row.get('attributes_json')
            if raw_attrs is None or raw_attrs == '':
                attrs = NodeService._flat_attributes(entity_type, row) if entity_type else {}
            elif isinstance(raw_attrs, str):
                try:
                    attrs = json.loads(raw_attrs)
                except json.JSONDecodeError:
                    attrs = {}
                    row_errors.append('attributes is not valid JSON.')
            else:
                attrs = raw_attrs

            if entity_type and not row_errors:
                attr_errs = NodeService.validate_attributes(entity_type, attrs)
                row_errors.extend(attr_errs)

            if row_errors:
                validation_errors.append({'row': i, 'errors': row_errors})

            normalised.append({
                'entity_type_code': et_code,
                'entity_type': entity_type,
                'name': str(row.get('name') or '').strip(),
                'code': _code(row, 'code'),
                'parent_code': _code(row, 'parent_code') or None,
                'channel_id': channel_id,
                'owned_scope_ids': owned_scope_ids,
                'attributes': attrs,
            })

        if validation_errors:
            # Rollback happens automatically (atomic) — we just return the errors.
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': validation_errors}


        try:
            sorted_rows = NodeService._topological_sort(normalised)
        except BusinessError as exc:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': [{'row': 0, 'errors': [str(exc)]}]}

        if dry_run:
            transaction.set_rollback(True)
            would_users = sum(
                1 for r in normalised if r['entity_type'] and r['entity_type'].is_loginable
            )
            return {
                'status': 'valid',
                'rows': len(normalised),
                'would_create': len(normalised),
                'would_create_users': would_users,
            }

        # Pre-assign codes for blank-code rows: one max-aggregate per type prefix,
        # then local increments — not one aggregate per row (150k blank retailers).
        next_n: dict[str, int] = {}
        for row in sorted_rows:
            if row['code']:
                continue
            et = row['entity_type']
            prefix = et.code.upper()
            if prefix not in next_n:
                next_n[prefix] = int(NodeService._generate_entity_code(et).rsplit('-', 1)[1])
            row['code'] = f'{prefix}-{next_n[prefix]:04d}'
            next_n[prefix] += 1

        # One query for every parent that lives outside this file.
        batch_codes = {r['code'] for r in sorted_rows}
        outside_parents = {
            r['parent_code'] for r in sorted_rows
            if r['parent_code'] and r['parent_code'] not in batch_codes
        }
        parent_cache: dict[str, int] = dict(
            Node.objects.filter(
                code__in=outside_parents, is_current=True, is_active=True,
            ).values_list('code', 'pk')
        ) if outside_parents else {}

        created_codes: dict[str, Node] = {}
        created_count = 0
        users_created = 0
        today = date.today()

        for row in sorted_rows:
            parent_id = None
            parent_code = row['parent_code']
            if parent_code:
                if parent_code in created_codes:
                    parent_id = created_codes[parent_code].pk
                else:
                    parent_id = parent_cache.get(parent_code)

            entity = NodeService.create_entity(
                {
                    'entity_type_id': row['entity_type'].pk,
                    'name': row['name'],
                    'code': row['code'],
                    'parent_id': parent_id,
                    'channel_id': row['channel_id'],
                    'owned_scope_ids': row['owned_scope_ids'],
                    'attributes': row['attributes'],
                    'effective_from': today,
                },
                user,
            )
            created_codes[entity.code] = entity
            created_count += 1
            if row['entity_type'].is_loginable:
                users_created += 1

        return {'status': 'success', 'created': created_count, 'users_created': users_created}


class TransferService:
    """One orchestrated transfer for a *person*, across both trees, in one atomic step.

    A real transfer touches the organisation tree (reporting line / seat) AND the
    geography bridge (owned territories). This is the single entry point that does
    both together; ``AssignmentService.transfer`` remains the primitive for a pure
    territory handover with no people movement.
    """

    HANDOVERS = ('successor', 'release', 'keep')

    @staticmethod
    def transfer_impact(entity_id: int) -> dict:
        """Read-only summary the transfer wizard previews before committing:
        current placement, owned territories, direct reports. Called on a vacant
        target seat, it shows the territories that come with that seat."""
        entity = Node.objects.select_related('entity_type', 'parent').filter(
            pk=entity_id, is_current=True, is_active=True,
        ).first()
        if entity is None:
            raise BusinessError(f'Node {entity_id} not found or not current.')

        assignments = AssignmentService.open_assignments_for_assignee(entity.pk, role='owner')
        reports = entity.get_direct_children().select_related('entity_type')
        return {
            'entity': {
                'id': entity.pk, 'name': entity.name, 'code': entity.code,
                'type': entity.entity_type.code if entity.entity_type_id else None,
                'status': entity.status,
            },
            'current_parent': (
                {'id': entity.parent.pk, 'name': entity.parent.name, 'code': entity.parent.code}
                if entity.parent_id else None
            ),
            'owned_territories': [
                {'assignment_id': a.pk, 'scope_id': a.scope_id, 'name': a.scope.name,
                 'code': a.scope.code, 'level': a.scope.level, 'since': str(a.effective_from)}
                for a in assignments
            ],
            'direct_reports': [
                {'id': c.pk, 'name': c.name, 'code': c.code,
                 'type': c.entity_type.code if c.entity_type_id else None}
                for c in reports
            ],
        }

    @staticmethod
    @transaction.atomic
    def transfer_person(entity_id: int, *, mode: str, reason: str, effective_date: date, user,
                        new_parent_id: int | None = None,
                        target_entity_id: int | None = None,
                        territory_handover: str = 'keep',
                        successor_id: int | None = None,
                        reassign_reports_to: int | None = None) -> Node:
        """
        Transfer a *person* to a new position WITHOUT dragging their team — and settle
        their territories in the same transaction (the half the old flow forgot).

        Seat movement (``mode``):
          'new_seat'      → the (childless) node moves under ``new_parent_id``; the
                            linked User travels with the node.
          'occupy_vacant' → the User is relinked onto an existing **vacant** seat of the
                            same type (``target_entity_id``); the source seat is
                            deactivated. Any territory already on the target seat comes
                            with it automatically — assignments attach to seats.

        Territory settlement (``territory_handover``) for the person's open owner
        assignments:
          'successor' → each one transfers to ``successor_id`` on the effective date.
          'release'   → each one is closed the day before; territory shows unowned.
          'keep'      → the person keeps covering them: no-op on a new_seat move
                        (assignments ride with the node); on occupy_vacant they
                        transfer from the old seat to the new one.

        Direct reports are first promoted to the entity's parent (or
        ``reassign_reports_to``). One 'transfer' audit entry records the full change
        set; each assignment mutation also keeps its own row-level trail.
        """
        from django.core.exceptions import ObjectDoesNotExist

        if mode not in ('new_seat', 'occupy_vacant'):
            raise BusinessError("mode must be 'new_seat' or 'occupy_vacant'.")
        if territory_handover not in TransferService.HANDOVERS:
            raise BusinessError(
                f"territory_handover must be one of {TransferService.HANDOVERS}."
            )
        if territory_handover == 'successor' and not successor_id:
            raise BusinessError("A 'successor' handover requires successor_id.")
        if successor_id == entity_id:
            raise BusinessError('Successor cannot be the entity being transferred.')

        entity = Node.objects.select_related('entity_type', 'parent').select_for_update(of=('self',)).get(
            pk=entity_id, is_current=True, is_active=True,
        )

        from_parent_id = entity.parent_id
        owned = list(AssignmentService.open_assignments_for_assignee(
            entity.pk, on=effective_date, role='owner',
        ))

        # 1. Decide where the team goes: default to the departing entity's own parent.
        children = list(entity.get_direct_children().select_related('entity_type'))
        reports_target_id = (
            reassign_reports_to if reassign_reports_to is not None else entity.parent_id
        )
        if reassign_reports_to is not None and reassign_reports_to == entity.pk:
            raise BusinessError('Cannot reassign reports to the entity being transferred.')
        if children and reports_target_id is None:
            raise BusinessError(
                'This entity has direct reports but no parent to promote them to. '
                'Pass reassign_reports_to to choose who they report to.'
            )

        promoted_ids = [c.pk for c in children]

        # 2. Promote the team away so the departing node is childless before it moves.
        if children:
            reports_target = Node.objects.select_related('entity_type').get(
                pk=reports_target_id, is_current=True, is_active=True,
            )
            for ch in children:
                errs = NodeService._validate_placement(ch.entity_type, reports_target)
                if errs:
                    raise BusinessError(
                        f"Cannot promote report '{ch.code}' to '{reports_target.code}': "
                        f"{'; '.join(errs)}. Pass reassign_reports_to a compatible manager."
                    )
            for ch in children:
                NodeService.move_entity(
                    ch.pk, reports_target.pk,
                    reason=f'Promoted during transfer of {entity.code}: {reason}',
                    effective_date=effective_date, user=user,
                )

        # 3. Land the incumbent at the destination.
        if mode == 'new_seat':
            if not new_parent_id:
                raise BusinessError('A new_seat transfer requires new_parent_id.')
            result_entity = NodeService.move_entity(
                entity.pk, new_parent_id,
                reason=reason, effective_date=effective_date, user=user,
            )
        else:  # occupy_vacant
            if not target_entity_id:
                raise BusinessError('An occupy_vacant transfer requires target_entity_id.')
            target = Node.objects.select_related('entity_type').select_for_update(of=('self',)).get(
                pk=target_entity_id, is_current=True, is_active=True,
            )
            if target.pk == entity.pk:
                raise BusinessError('Target seat cannot be the entity being transferred.')
            if target.status != 'vacant':
                raise BusinessError(
                    f"Target seat '{target.code}' is not vacant (status='{target.status}')."
                )
            if entity.entity_type_id != target.entity_type_id:
                raise BusinessError(
                    'Target seat is a different entity type. occupy_vacant requires the same '
                    'type — use change-type for a promotion.'
                )
            try:
                existing = target.user
            except ObjectDoesNotExist:
                existing = None
            if existing is not None:
                raise BusinessError(f"Target seat '{target.code}' already has an incumbent.")

            # Relink the person (if any) onto the existing vacant seat.
            try:
                incumbent = entity.user
            except ObjectDoesNotExist:
                incumbent = None
            if incumbent is not None:
                incumbent.entity = target
                incumbent.save(update_fields=['entity'])

            target.status = 'active'
            target.save(update_fields=['status', 'updated_at'])
            result_entity = target

        # 4. Settle the territories — the half the legacy flow left dangling.
        territory_moves: list[dict] = []
        if territory_handover == 'successor':
            for a in owned:
                AssignmentService.transfer(
                    scope_id=a.scope_id, new_assignee_id=successor_id,
                    effective_from=effective_date,
                    reason=f'Handover during transfer of {entity.code}: {reason}', user=user,
                )
                territory_moves.append(
                    {'scope_id': a.scope_id, 'scope_code': a.scope.code,
                     'action': 'successor', 'to': successor_id})
        elif territory_handover == 'release':
            for a in owned:
                AssignmentService.end(
                    a.pk, effective_to=effective_date - timedelta(days=1),
                    reason=f'Released during transfer of {entity.code}: {reason}', user=user,
                )
                territory_moves.append(
                    {'scope_id': a.scope_id, 'scope_code': a.scope.code,
                     'action': 'release', 'to': None})
        elif mode == 'occupy_vacant':  # keep → territories follow the person to the new seat
            for a in owned:
                AssignmentService.transfer(
                    scope_id=a.scope_id, new_assignee_id=result_entity.pk,
                    effective_from=effective_date,
                    reason=f'Kept through transfer of {entity.code}: {reason}', user=user,
                )
                territory_moves.append(
                    {'scope_id': a.scope_id, 'scope_code': a.scope.code,
                     'action': 'keep', 'to': result_entity.pk})
        # keep + new_seat: same node id — assignments ride along untouched.

        if mode == 'occupy_vacant':
            # Source seat is now empty and childless → close any remaining
            # assignments (stand-in/supervisor roles) and deactivate it.
            AssignmentService.end_all_for_assignee(
                entity.pk, effective_to=effective_date - timedelta(days=1),
                reason=f'Seat vacated by transfer: {reason}', user=user,
            )
            entity.status = 'inactive'
            entity.save(update_fields=['status', 'updated_at'])

        AuditService.log(
            action='transfer',
            entity_type='hierarchy.Node',
            entity_id=entity.pk,
            user=user,
            changes={
                'mode': mode,
                'from_parent_id': from_parent_id,
                'to_parent_id': result_entity.parent_id,
                'to_entity_id': result_entity.pk,
                'territory_handover': territory_handover,
                'territory_moves': territory_moves,
                'reports_promoted_to': reports_target_id,
                'reports_promoted': promoted_ids,
                'reason': reason,
                'effective_date': str(effective_date),
            },
        )

        return result_entity


def models_q_from_or_to(entity_pk: int):
    """Return a Q object matching NodeRelationship rows involving entity_pk."""
    from django.db.models import Q
    return Q(from_entity_id=entity_pk) | Q(to_entity_id=entity_pk)
