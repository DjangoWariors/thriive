from django.utils import timezone
from rest_framework import serializers

from . import adapters
from .models import (
    ApprovalDelegation, WorkflowAction, WorkflowDefinition, WorkflowInstance, WorkflowStep,
)


def _full_name(user) -> str | None:
    if user is None:
        return None
    return f'{user.first_name} {user.last_name}'.strip() or user.email


class WorkflowStepSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowStep
        fields = ['id', 'order', 'name', 'approval_mode', 'status', 'assignee_user',
                  'assignee_name', 'assignee_role_code', 'assignee_user_ids', 'sla_due_at',
                  'activated_at', 'resolved_at']

    def get_assignee_name(self, obj) -> str | None:
        return _full_name(obj.assignee_user)


class WorkflowActionSerializer(serializers.ModelSerializer):
    action_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowAction
        fields = ['id', 'step', 'step_order', 'action', 'action_by', 'action_by_name',
                  'comments', 'created_at']

    def get_action_by_name(self, obj) -> str | None:
        return _full_name(obj.action_by)


def _subject_summary(instance) -> dict:
    adapter = adapters.get(instance.subject_type)
    if adapter is None:
        return {}
    subject = adapter.load(instance.subject_id)
    return adapter.summary(subject) if subject is not None else {}


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    definition_code = serializers.CharField(source='definition.code', read_only=True)
    definition_name = serializers.CharField(source='definition.name', read_only=True)
    initiated_by_name = serializers.SerializerMethodField()
    anchor_entity_name = serializers.CharField(source='anchor_entity.name', read_only=True, default=None)
    steps = WorkflowStepSerializer(many=True, read_only=True)
    actions = WorkflowActionSerializer(many=True, read_only=True)
    subject_summary = serializers.SerializerMethodField()
    current_step_name = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowInstance
        fields = ['id', 'definition', 'definition_code', 'definition_name', 'subject_type',
                  'subject_id', 'status', 'current_step', 'current_step_name', 'anchor_entity',
                  'anchor_entity_name', 'initiated_by', 'initiated_by_name', 'context_data',
                  'sla_due_at', 'is_overdue', 'resolved_at', 'created_at', 'subject_summary',
                  'steps', 'actions']

    def get_initiated_by_name(self, obj) -> str | None:
        return _full_name(obj.initiated_by)

    def get_subject_summary(self, obj) -> dict:
        return _subject_summary(obj)

    def get_current_step_name(self, obj) -> str | None:
        step = next((s for s in obj.steps.all() if s.status in WorkflowStep.OPEN_STATUSES), None)
        return step.name if step else None

    def get_is_overdue(self, obj) -> bool:
        return bool(obj.sla_due_at and obj.sla_due_at < timezone.now())


class PendingApprovalSerializer(serializers.ModelSerializer):
    """Lightweight inbox row."""
    definition_code = serializers.CharField(source='definition.code', read_only=True)
    initiated_by_name = serializers.SerializerMethodField()
    anchor_entity_name = serializers.CharField(source='anchor_entity.name', read_only=True, default=None)
    current_step_name = serializers.SerializerMethodField()
    subject_summary = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowInstance
        fields = ['id', 'definition_code', 'subject_type', 'subject_id', 'status',
                  'current_step', 'current_step_name', 'anchor_entity_name',
                  'initiated_by_name', 'context_data', 'sla_due_at', 'is_overdue',
                  'subject_summary', 'created_at']

    def get_initiated_by_name(self, obj) -> str | None:
        return _full_name(obj.initiated_by)

    def get_current_step_name(self, obj) -> str | None:
        step = next((s for s in obj.steps.all() if s.status in WorkflowStep.OPEN_STATUSES), None)
        return step.name if step else None

    def get_subject_summary(self, obj) -> dict:
        return _subject_summary(obj)

    def get_is_overdue(self, obj) -> bool:
        return bool(obj.sla_due_at and obj.sla_due_at < timezone.now())


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowDefinition
        fields = ['id', 'name', 'code', 'description', 'subject_type', 'trigger_event',
                  'steps', 'version', 'is_current', 'effective_from', 'effective_to',
                  'is_active', 'created_at']
        read_only_fields = ['id', 'version', 'is_current', 'created_at']


class ApprovalDelegationSerializer(serializers.ModelSerializer):
    delegator_name = serializers.SerializerMethodField()
    delegate_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalDelegation
        fields = ['id', 'delegator', 'delegator_name', 'delegate', 'delegate_name',
                  'scope', 'start_date', 'end_date', 'reason', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_delegator_name(self, obj) -> str | None:
        return _full_name(obj.delegator)

    def get_delegate_name(self, obj) -> str | None:
        return _full_name(obj.delegate)


class CommentSerializer(serializers.Serializer):
    comments = serializers.CharField(required=False, allow_blank=True, default='')


class WorkflowRejectSerializer(serializers.Serializer):
    reason = serializers.CharField()


class BulkActionSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    comments = serializers.CharField(required=False, allow_blank=True, default='')
    reason = serializers.CharField(required=False, allow_blank=True, default='')
