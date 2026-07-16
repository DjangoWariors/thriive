from rest_framework import serializers

from apps.hierarchy.models import Node, GeographyNode

from .models import Assignment


class _NodeRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Node
        fields = ['id', 'name', 'code', 'path']


class _GeographyRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeographyNode
        fields = ['id', 'name', 'code', 'level', 'path']


class AssignmentSerializer(serializers.ModelSerializer):
    assignee = _NodeRefSerializer(read_only=True)
    scope = _GeographyRefSerializer(read_only=True)

    class Meta:
        model = Assignment
        fields = [
            'id', 'assignee', 'scope', 'role_in_scope',
            'effective_from', 'effective_to', 'reason',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AssignmentCreateSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField()
    scope_id = serializers.IntegerField()
    role_in_scope = serializers.ChoiceField(
        choices=Assignment.Role.choices, default=Assignment.Role.OWNER,
    )
    effective_from = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class AssignmentTransferSerializer(serializers.Serializer):
    scope_id = serializers.IntegerField()
    new_assignee_id = serializers.IntegerField()
    role_in_scope = serializers.ChoiceField(
        choices=Assignment.Role.choices, default=Assignment.Role.OWNER,
    )
    effective_from = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class AssignmentEndSerializer(serializers.Serializer):
    effective_to = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')
