from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet
from rest_framework import mixins

from apps.core.pagination import StandardPagination
from apps.core.permissions import LevelRBACPermission, highest_level

# Read-any levels: an unplaced holder (HO admin / finance) sees the whole ledger.
_READ_ANY = frozenset(('full', 'view_all', 'view_edit', 'view_readonly'))

from .models import ApprovalDelegation, WorkflowDefinition, WorkflowInstance
from .serializers import (
    ApprovalDelegationSerializer,
    BulkActionSerializer,
    CommentSerializer,
    PendingApprovalSerializer,
    WorkflowActionSerializer,
    WorkflowDefinitionSerializer,
    WorkflowInstanceSerializer,
    WorkflowRejectSerializer,
)
from .services import WorkflowService

_TAG = ['Workflows']


@extend_schema_view(
    retrieve=extend_schema(tags=_TAG, summary='Workflow instance with steps + action history'),
)
class WorkflowInstanceViewSet(mixins.RetrieveModelMixin, GenericViewSet):
    required_permission = 'workflow_management'
    # Instances anchor to a domain object, not an org entity — object access is
    # level-only; WHO may act is enforced by WorkflowService eligibility, and WHO may
    # see an instance by the involvement scoping below.
    permission_classes = [LevelRBACPermission]
    serializer_class = WorkflowInstanceSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = (
            WorkflowInstance.objects
            .select_related('definition', 'anchor_entity', 'initiated_by')
            .prefetch_related('steps', 'actions', 'actions__action_by')
        )
        user = self.request.user
        if user.is_superuser:
            return qs
        if getattr(user, 'entity', None) is None and \
                highest_level(user, self.required_permission) in _READ_ANY:
            return qs
        # A placed user sees the requests they are part of: initiated, acted on,
        # assigned to a step of, or currently pending with them (incl. via delegation).
        pending_ids = list(WorkflowService.get_pending(user).values_list('pk', flat=True))
        return qs.filter(
            Q(initiated_by=user) | Q(actions__action_by=user)
            | Q(steps__assignee_user=user) | Q(pk__in=pending_ids)
        ).distinct()

    @extend_schema(tags=_TAG, summary='My pending approvals (assigned or delegated)',
                   responses={200: PendingApprovalSerializer(many=True)})
    @action(detail=False, methods=['get'])
    def pending(self, request):
        qs = WorkflowService.get_pending(request.user)
        page = self.paginate_queryset(qs)
        ser = PendingApprovalSerializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(tags=_TAG, summary='Count of my pending approvals (sidebar badge)')
    @action(detail=False, methods=['get'], url_path='pending/count')
    def pending_count(self, request):
        return Response({'count': WorkflowService.pending_count(request.user)})

    @extend_schema(tags=_TAG, summary='Action history (audit timeline)',
                   responses={200: WorkflowActionSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        instance = self.get_object()
        ser = WorkflowActionSerializer(
            instance.actions.select_related('action_by').all(), many=True,
        )
        return Response(ser.data)

    @extend_schema(tags=_TAG, summary='Approve the active step', request=CommentSerializer,
                   responses={200: WorkflowInstanceSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        instance = self.get_object()
        ser = CommentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = WorkflowService.approve(instance, request.user, ser.validated_data['comments'])
        return Response(WorkflowInstanceSerializer(self._reload(instance.pk)).data)

    @extend_schema(tags=_TAG, summary='Reject the request', request=WorkflowRejectSerializer,
                   responses={200: WorkflowInstanceSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        instance = self.get_object()
        ser = WorkflowRejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = WorkflowService.reject(instance, request.user, ser.validated_data['reason'])
        return Response(WorkflowInstanceSerializer(self._reload(instance.pk)).data)

    @extend_schema(tags=_TAG, summary='Approve many requests at once', request=BulkActionSerializer)
    @action(detail=False, methods=['post'], url_path='bulk-approve')
    def bulk_approve(self, request):
        ser = BulkActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = WorkflowService.bulk_act(
            ser.validated_data['ids'], request.user, 'approve', ser.validated_data['comments'],
        )
        return Response(result)

    @extend_schema(tags=_TAG, summary='Reject many requests at once', request=BulkActionSerializer)
    @action(detail=False, methods=['post'], url_path='bulk-reject')
    def bulk_reject(self, request):
        ser = BulkActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason'] or ser.validated_data['comments']
        if not reason.strip():
            return Response({'detail': 'A reason is required to reject.'}, status=400)
        result = WorkflowService.bulk_act(ser.validated_data['ids'], request.user, 'reject', reason)
        return Response(result)

    def _reload(self, pk):
        return self.get_queryset().get(pk=pk)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List workflow definitions (current versions)'),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a workflow definition'),
    create=extend_schema(tags=_TAG, summary='Create a workflow definition'),
    update=extend_schema(tags=_TAG, summary='Update a definition (creates a new version)'),
    destroy=extend_schema(tags=_TAG, summary='Deactivate a definition'),
)
class WorkflowDefinitionViewSet(ModelViewSet):
    required_permission = 'workflow_management'
    serializer_class = WorkflowDefinitionSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'put', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = WorkflowDefinition.objects.all()
        if self.action == 'list':
            qs = qs.filter(is_current=True, is_active=True)
        if subject := self.request.query_params.get('subject_type'):
            qs = qs.filter(subject_type=subject)
        return qs.order_by('code', '-version')

    def perform_update(self, serializer):
        # Config models are versioned: an edit retires the current row and inserts v+1.
        instance = serializer.instance
        data = serializer.validated_data
        instance.create_new_version(**data)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    @extend_schema(tags=_TAG, summary='Version history for a definition code')
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        current = self.get_object()
        rows = WorkflowDefinition.objects.filter(code=current.code).order_by('-version')
        return Response(WorkflowDefinitionSerializer(rows, many=True).data)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List approval delegations'),
    create=extend_schema(tags=_TAG, summary='Create an out-of-office delegation'),
    destroy=extend_schema(tags=_TAG, summary='End a delegation'),
)
class ApprovalDelegationViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                                mixins.DestroyModelMixin, GenericViewSet):
    required_permission = 'workflow_management'
    # Delegations carry user FKs, not entities; the queryset already limits non-admins
    # to delegations they gave or received.
    permission_classes = [LevelRBACPermission]
    serializer_class = ApprovalDelegationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ApprovalDelegation.objects.filter(is_active=True).select_related(
            'delegator', 'delegate',
        )
        # Non-superusers see delegations they gave or received.
        user = self.request.user
        if not user.is_superuser:
            from django.db.models import Q
            qs = qs.filter(Q(delegator=user) | Q(delegate=user))
        return qs.order_by('-created_at')

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
