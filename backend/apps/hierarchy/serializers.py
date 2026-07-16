from datetime import date as _date

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Channel,
    Node,
    NodeRelationship,
    NodeType,
    GeographyNode,
    GeographyType,
    RelationshipType,
)



class ChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Channel
        fields = ['id', 'name', 'code', 'description', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ChannelNestedSerializer(serializers.ModelSerializer):

    class Meta:
        model = Channel
        fields = ['id', 'code', 'name']


class NodeTypeSerializer(serializers.ModelSerializer):
    channel = ChannelNestedSerializer(read_only=True)
    channel_id = serializers.PrimaryKeyRelatedField(
        source='channel', queryset=Channel.objects.all(),
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = NodeType
        fields = [
            'id', 'name', 'code', 'description', 'level_order',
            'allowed_parent_types', 'allowed_child_types', 'attribute_schema',
            'is_loginable', 'incentive_eligible', 'is_leaf',
            'is_root_type',
            'default_role', 'channel', 'channel_id', 'display_config',
            'version', 'effective_from', 'effective_to', 'is_current',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'version', 'created_at', 'updated_at']


class NodeTypeBlueprintSerializer(serializers.ModelSerializer):

    class Meta:
        model = NodeType
        fields = [
            'id', 'name', 'code', 'level_order',
            'is_loginable', 'incentive_eligible', 'is_leaf',
            'allowed_parent_types', 'allowed_child_types',
            'attribute_schema', 'display_config',
        ]



class NodeListSerializer(serializers.ModelSerializer):
    entity_type_code = serializers.SerializerMethodField()
    entity_type_name = serializers.SerializerMethodField()
    parent_name = serializers.SerializerMethodField()
    channel = ChannelNestedSerializer(read_only=True)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type_code(self, obj):
        return obj.entity_type.code if obj.entity_type_id else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type_name(self, obj):
        return obj.entity_type.name if obj.entity_type_id else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent_id else None

    class Meta:
        model = Node
        fields = [
            'id', 'name', 'code',
            'entity_type_code', 'entity_type_name',
            'parent', 'parent_name',
            'status', 'channel',
            'depth', 'path',
            'is_current', 'version', 'is_active',
        ]



class NodeSubtreeSerializer(NodeListSerializer):
    """Serializer for the subtree endpoint.

    Returns a flat list of nodes and includes the linked user, if one exists.
    The extra user data is included only for this endpoint so other list, child,
    and search endpoints remain lightweight.
    """

    linked_user = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_linked_user(self, obj):
        try:
            u = obj.user
            return {'id': u.pk, 'email': u.email, 'mobile': u.mobile, 'is_active': u.is_active}
        except ObjectDoesNotExist:
            return None

    class Meta(NodeListSerializer.Meta):
        fields = NodeListSerializer.Meta.fields + ['linked_user']



def _open_owner_assignments(obj):
    """Effective owner assignments for a node, shallowest scope first — cached on the
    instance so display_code + owned_scopes share one lookup (views may pre-populate)."""
    cached = getattr(obj, '_owned_assignments', None)
    if cached is None:
        from apps.assignments.services import AssignmentService
        cached = list(AssignmentService.open_assignments_for_assignee(obj.pk, role='owner'))
        obj._owned_assignments = cached
    return cached


class NodeDetailSerializer(serializers.ModelSerializer):
    entity_type = NodeTypeSerializer(read_only=True)
    parent_info = serializers.SerializerMethodField()
    linked_user = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    channel = ChannelNestedSerializer(read_only=True)
    owned_scopes = serializers.SerializerMethodField()
    display_code = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_display_code(self, obj):
        """Returns a role and geography label, such as `ASM-DL`.

        The geography part is the node's primary owned territory (shallowest, then
        alphabetical) resolved through assignments, so it tracks transfers. Unlike
        `code`, which is a permanent identifier, this label is dynamic.
        """
        type_code = obj.entity_type.code.upper() if obj.entity_type_id else ''
        owned = _open_owner_assignments(obj)
        if owned:
            return f'{type_code}-{owned[0].scope.code}'
        return type_code

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_owned_scopes(self, obj):
        """Territories this entity currently owns, via the Assignment bridge."""
        return [
            {'id': a.scope_id, 'name': a.scope.name, 'code': a.scope.code,
             'level': a.scope.level, 'since': str(a.effective_from)}
            for a in _open_owner_assignments(obj)
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_parent_info(self, obj):
        if not obj.parent_id:
            return None
        p = obj.parent
        return {
            'id': p.pk,
            'name': p.name,
            'code': p.code,
            'type': p.entity_type.code if p.entity_type_id else None,
        }

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_linked_user(self, obj):
        try:
            u = obj.user
            return {
                'id': u.pk,
                'email': u.email,
                'mobile': u.mobile,
                'is_active': u.is_active,
            }
        except ObjectDoesNotExist:
            return None

    @extend_schema_field(serializers.IntegerField())
    def get_children_count(self, obj):
        return obj.get_direct_children().count()

    class Meta:
        model = Node
        fields = [
            'id', 'name', 'code', 'display_code',
            'entity_type', 'parent', 'parent_info',
            'attributes', 'channel', 'owned_scopes',
            'path', 'depth', 'status',
            'linked_user', 'children_count',
            'version', 'effective_from', 'effective_to', 'is_current',
            'is_active', 'created_at', 'updated_at',
        ]



class NodeCreateSerializer(serializers.Serializer):
    entity_type_id = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    attributes = serializers.DictField(required=False, default=dict)
    channel_id = serializers.IntegerField(required=False, allow_null=True)
    owned_scope_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
        help_text='Geography nodes this entity will own from day one (opens owner assignments).',
    )
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    mobile = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    employee_id = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True,
        write_only=True, trim_whitespace=False,
        help_text='Initial password for the auto-created login (password-capable types only).',
    )
    effective_from = serializers.DateField(required=False, default=_date.today)
    status = serializers.CharField(max_length=20, required=False, default='active')


class NodeUpdateSerializer(serializers.Serializer):
    """Editable fields for an existing entity.
    """

    name = serializers.CharField(max_length=200, required=False)
    attributes = serializers.DictField(required=False)
    channel_id = serializers.IntegerField(required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    mobile = serializers.CharField(
        max_length=20, required=False, allow_null=True, allow_blank=True,
    )
    password = serializers.CharField(
        max_length=128, required=False, allow_null=True, allow_blank=True,
        write_only=True, trim_whitespace=False,
        help_text='Set a new password for the linked login; blank keeps the current one.',
    )


class NodeMoveSerializer(serializers.Serializer):
    new_parent_id = serializers.IntegerField()
    reason = serializers.CharField()
    effective_date = serializers.DateField()


class NodeTransferSerializer(serializers.Serializer):
    """Transfer a person to a new position AND settle their territories, atomically.

    The departing entity's reports are promoted to its parent (or
    ``reassign_reports_to``); the person lands at the destination per ``mode``;
    their open owner assignments are settled per ``territory_handover``.
    """

    mode = serializers.ChoiceField(choices=['new_seat', 'occupy_vacant'])
    reason = serializers.CharField()
    effective_date = serializers.DateField()
    # mode='new_seat' — relocate the (childless) node under a new manager.
    new_parent_id = serializers.IntegerField(required=False)
    # mode='occupy_vacant' — fill an existing vacant seat of the same type.
    target_entity_id = serializers.IntegerField(required=False)
    # Territory settlement for the person's owned scopes.
    territory_handover = serializers.ChoiceField(
        choices=['successor', 'release', 'keep'], default='keep',
    )
    successor_id = serializers.IntegerField(required=False, allow_null=True)
    # Team handling — defaults to the departing entity's own parent.
    reassign_reports_to = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs['mode'] == 'new_seat':
            if not attrs.get('new_parent_id'):
                raise serializers.ValidationError(
                    {'new_parent_id': 'Required for a new_seat transfer.'}
                )
        elif not attrs.get('target_entity_id'):
            raise serializers.ValidationError(
                {'target_entity_id': 'Required for an occupy_vacant transfer.'}
            )
        if attrs.get('territory_handover') == 'successor' and not attrs.get('successor_id'):
            raise serializers.ValidationError(
                {'successor_id': "Required when territory_handover is 'successor'."}
            )
        return attrs


class NodeBulkImportSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=['csv', 'json'], default='json')
    data = serializers.CharField(
        required=False, allow_blank=True,
        help_text='JSON array string or CSV text. Omit when uploading a file.',
    )
    file = serializers.FileField(
        required=False,
        help_text='CSV or JSON file. Takes precedence over the data field.',
    )
    dry_run = serializers.BooleanField(
        default=False,
        help_text='Validate every row and return a preview/errors without creating anything.',
    )
    run_async = serializers.BooleanField(
        default=False,
        help_text='Process as a background job and return a job_id to poll. '
        'Imports larger than the async threshold are forced async regardless.',
    )


class NodeBulkMoveSerializer(serializers.Serializer):
    entity_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
        help_text='IDs of the entities to move under the new parent.',
    )
    new_parent_id = serializers.IntegerField()
    reason = serializers.CharField()
    effective_date = serializers.DateField()


class NodeBulkDeactivateSerializer(serializers.Serializer):
    entity_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    reason = serializers.CharField()
    cascade = serializers.BooleanField(
        default=False,
        help_text='Also deactivate each entity\'s entire subtree.',
    )


class NodeBulkReactivateSerializer(serializers.Serializer):
    entity_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    reason = serializers.CharField(required=False, allow_blank=True)


class NodeChangeTypeSerializer(serializers.Serializer):
    """ change an entity's type in place."""

    new_type_id = serializers.IntegerField()
    new_parent_id = serializers.IntegerField(required=False, allow_null=True)
    attributes = serializers.DictField(required=False)
    reason = serializers.CharField()
    effective_date = serializers.DateField(required=False)
    reassign_reports_to = serializers.IntegerField(required=False, allow_null=True)



class GeographyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeographyType
        fields = ['id', 'name', 'code', 'levels', 'attribute_schema', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GeographyTypeNestedSerializer(serializers.ModelSerializer):
    """Compact read-only geography-type shape embedded in node responses."""
    class Meta:
        model = GeographyType
        fields = ['id', 'code', 'name', 'levels']


class GeographyNodeSerializer(serializers.ModelSerializer):
    geography_type = GeographyTypeNestedSerializer(read_only=True)
    geography_type_id = serializers.PrimaryKeyRelatedField(
        source='geography_type', queryset=GeographyType.objects.all(), write_only=True,
    )
    parent_name = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent_id else None

    @extend_schema_field(serializers.IntegerField())
    def get_children_count(self, obj):
        return obj.children.filter(is_active=True).count()

    def validate(self, attrs):
        geo_type = attrs.get('geography_type') or getattr(self.instance, 'geography_type', None)
        attributes = attrs.get('attributes')
        if geo_type is not None and attributes is not None:
            from apps.hierarchy.services import GeographyService
            errors = GeographyService.validate_attributes(
                geo_type, attributes, exclude_node_id=self.instance.id if self.instance else None)
            if errors:
                raise serializers.ValidationError({'attributes': errors})
        return attrs

    class Meta:
        model = GeographyNode
        fields = [
            'id', 'geography_type', 'geography_type_id', 'name', 'code', 'level',
            'parent', 'parent_name', 'children_count', 'path', 'depth', 'attributes', 'is_active',
        ]
        read_only_fields = ['id', 'path', 'depth']


class GeographyNodeMoveSerializer(serializers.Serializer):
    new_parent_id = serializers.IntegerField(allow_null=True)



class RelationshipTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelationshipType
        fields = [
            'id', 'name', 'code',
            'from_entity_type', 'to_entity_type',
            'allows_multiple', 'is_active',
        ]
        read_only_fields = ['id']


class NodeRelationshipSerializer(serializers.ModelSerializer):
    from_entity_name = serializers.SerializerMethodField()
    to_entity_name = serializers.SerializerMethodField()
    type_name = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_from_entity_name(self, obj):
        return obj.from_entity.name

    @extend_schema_field(serializers.CharField())
    def get_to_entity_name(self, obj):
        return obj.to_entity.name

    @extend_schema_field(serializers.CharField())
    def get_type_name(self, obj):
        return obj.relationship_type.name

    class Meta:
        model = NodeRelationship
        fields = [
            'id', 'relationship_type', 'type_name',
            'from_entity', 'from_entity_name',
            'to_entity', 'to_entity_name',
            'effective_from', 'effective_to', 'is_active',
        ]
        read_only_fields = ['id']
