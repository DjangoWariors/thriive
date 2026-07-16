import csv
import io
from datetime import date

from django.core.cache import cache
from django.db.models import Count, Q
from django.http import HttpResponse, StreamingHttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.exceptions import BusinessError
from apps.core.scoping import NodeScopedQuerysetMixin
from apps.core.throttling import BulkImportRateThrottle
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.jobs.utils import BULK_ASYNC_THRESHOLD, count_rows

from .models import (
    Channel,
    Node,
    NodeRelationship,
    NodeType,
    GeographyNode,
    GeographyType,
    RelationshipType,
)
from .serializers import (
    ChannelSerializer,
    NodeBulkDeactivateSerializer,
    NodeBulkImportSerializer,
    NodeBulkMoveSerializer,
    NodeBulkReactivateSerializer,
    NodeChangeTypeSerializer,
    NodeCreateSerializer,
    NodeDetailSerializer,
    NodeListSerializer,
    NodeMoveSerializer,
    NodeRelationshipSerializer,
    NodeSubtreeSerializer,
    NodeTransferSerializer,
    NodeTypeBlueprintSerializer,
    NodeTypeSerializer,
    NodeUpdateSerializer,
    GeographyNodeMoveSerializer,
    GeographyNodeSerializer,
    GeographyTypeSerializer,
    RelationshipTypeSerializer,
)
from .config_services import (
    ENTITY_TYPE_BLUEPRINT_CACHE_KEY,
    ChannelService,
    NodeRelationshipService,
    NodeTypeService,
    GeographyNodeService,
    GeographyTypeService,
    RelationshipTypeService,
)
from .services import NodeService, TransferService
from apps.assignments.services import AssignmentService


@extend_schema_view(
    list=extend_schema(tags=['Channels'], summary='List channels'),
    retrieve=extend_schema(tags=['Channels'], summary='Retrieve channel'),
    create=extend_schema(tags=['Channels'], summary='Create channel'),
    update=extend_schema(tags=['Channels'], summary='Update channel'),
    partial_update=extend_schema(tags=['Channels'], summary='Partial update channel'),
    destroy=extend_schema(tags=['Channels'], summary='Soft delete channel'),
)
class ChannelViewSet(ModelViewSet):
    serializer_class = ChannelSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        return Channel.objects.filter(is_active=True).order_by('name')

    def perform_create(self, serializer):
        serializer.instance = ChannelService.create(serializer.validated_data, actor=self.request.user)

    def perform_update(self, serializer):
        serializer.instance = ChannelService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        ChannelService.deactivate(instance, actor=self.request.user)



@extend_schema_view(
    list=extend_schema(tags=['Node Types'], summary='List current entity types'),
    retrieve=extend_schema(tags=['Node Types'], summary='Retrieve entity type'),
    create=extend_schema(tags=['Node Types'], summary='Create entity type'),
    update=extend_schema(tags=['Node Types'], summary='Update entity type'),
    partial_update=extend_schema(tags=['Node Types'], summary='Partial update entity type'),
    destroy=extend_schema(tags=['Node Types'], summary='Soft delete entity type'),
)
class NodeTypeViewSet(ModelViewSet):
    serializer_class = NodeTypeSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        return (
            NodeType.objects
            .filter(is_current=True, is_active=True)
            .select_related('default_role', 'channel')
            .order_by('level_order')
        )

    def perform_create(self, serializer):
        serializer.instance = NodeTypeService.create(
            serializer.validated_data, actor=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.instance = NodeTypeService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        NodeTypeService.deactivate(instance, actor=self.request.user)

    @extend_schema(
        tags=['Node Types'],
        operation_id='entity_type_blueprint',
        summary='Full hierarchy blueprint',
        description=(
            'Returns all current entity types ordered by level_order with full config '
            '(attribute schemas, display config, capability flags). Used by the UI wizard.'
        ),
        responses={200: NodeTypeBlueprintSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='blueprint')
    def blueprint(self, request):
        data = cache.get(ENTITY_TYPE_BLUEPRINT_CACHE_KEY)
        if data is None:
            qs = NodeType.objects.filter(is_current=True, is_active=True).order_by('level_order')
            data = NodeTypeBlueprintSerializer(qs, many=True).data
            cache.set(ENTITY_TYPE_BLUEPRINT_CACHE_KEY, data, timeout=3600)
        return Response(data)

    @extend_schema(
        tags=['Node Types'],
        operation_id='entity_type_versions',
        summary='Version history for an entity type',
        description='Returns all versions of a given entity type, ordered by version number ascending.',
        responses={200: NodeTypeSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        obj = self.get_object()
        qs = NodeType.objects.filter(code=obj.code).order_by('version')
        return Response(NodeTypeSerializer(qs, many=True).data)



_ENTITY_QUERY_PARAMS = [
    OpenApiParameter('type', description='Filter by entity_type code (e.g. ase)', required=False, type=str),
    OpenApiParameter('channel', description='Filter by channel code (e.g. GT)', required=False, type=str),
    OpenApiParameter('geography', description='Filter by geography node code (includes its whole subtree)', required=False, type=str),
    OpenApiParameter('status', description='Filter by status: active, inactive, suspended, onboarding', required=False, type=str),
    OpenApiParameter('parent', description='Filter by parent entity ID', required=False, type=int),
    OpenApiParameter('root', description='If true, return only root (parentless) entities', required=False, type=bool),
]


@extend_schema_view(
    retrieve=extend_schema(
        tags=['Entities'],
        operation_id='entity_retrieve',
        summary='Node full detail',
        responses={200: NodeDetailSerializer},
    ),
    update=extend_schema(tags=['Entities'], summary='Update entity'),
    partial_update=extend_schema(tags=['Entities'], summary='Partial update entity'),
    destroy=extend_schema(
        tags=['Entities'],
        operation_id='entity_deactivate',
        summary='Deactivate entity (soft delete)',
        description='Sets status=inactive. Fails with 422 if entity has active children.',
    ),
)
class NodeViewSet(NodeScopedQuerysetMixin, ModelViewSet):
    required_permission = 'hierarchy_management'
    # Scope list/search/export to the requester's subtree (team/own_only levels).
    # Defaults scope_path_field='path' / scope_entity_id_field='pk' fit Node rows.
    filter_backends = [OrderingFilter]
    ordering_fields = ['name', 'code', 'status', 'depth', 'created_at', 'updated_at']
    ordering = ['name']

    def get_queryset(self):
        qs = (
            Node.objects
            .filter(is_current=True, is_active=True)
            .select_related('entity_type', 'parent__entity_type', 'channel')
        )
        params = self.request.query_params
        if type_code := params.get('type'):
            qs = qs.filter(entity_type__code=type_code)
        if channel_code := params.get('channel'):
            qs = qs.filter(channel__code=channel_code)
        if geo_code := params.get('geography'):
            # Territory filter: entities owning any territory in the node's subtree
            # (resolved through the Assignment bridge, as of today).
            geo_node = GeographyNode.objects.filter(code=geo_code, is_active=True).first()
            if geo_node is not None:
                qs = qs.filter(pk__in=AssignmentService.owner_assignee_ids_in_subtree(geo_node))
            else:
                qs = qs.none()
        if status_val := params.get('status'):
            qs = qs.filter(status=status_val)
        if parent_id := params.get('parent'):
            qs = qs.filter(parent_id=parent_id)
        if params.get('root', '').lower() in ('true', '1', 'yes'):
            # Tree view loads roots only, then lazy-loads children — never the whole table.
            qs = qs.filter(parent__isnull=True)
        return self.scope_queryset(qs.order_by('name'))

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return NodeDetailSerializer
        if self.action == 'create':
            return NodeCreateSerializer
        if self.action in ('update', 'partial_update'):
            return NodeUpdateSerializer
        return NodeListSerializer

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_list',
        summary='List entities',
        description='Paginated entity list. Supports ?type, ?channel, ?status, ?parent filters.',
        parameters=_ENTITY_QUERY_PARAMS,
        responses={200: NodeListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_create',
        summary='Create entity',
        description=(
            'Create a new entity. Validates attributes against the entity type schema. '
            'Auto-creates a User account if entity_type.is_loginable is True.'
        ),
        request=NodeCreateSerializer,
        responses={201: NodeDetailSerializer},
    )
    def create(self, request, *args, **kwargs):
        ser = NodeCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        entity = NodeService.create_entity(ser.validated_data, request.user)
        entity_with_rels = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=entity.pk)
        )
        return Response(NodeDetailSerializer(entity_with_rels).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_update',
        summary='Update entity',
        description=(
            'Update an entity\'s name, attributes, and channel. For loginable types, '
            'email/mobile are propagated to the linked user. Code, parent, and type are '
            'not editable here (use the move endpoint to change parent); territory '
            'coverage changes go through transfer or the assignments API.'
        ),
        request=NodeUpdateSerializer,
        responses={200: NodeDetailSerializer},
    )
    def update(self, request, *args, **kwargs):
        entity = self.get_object()
        partial = kwargs.pop('partial', False)
        ser = NodeUpdateSerializer(data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        NodeService.update_entity(entity.pk, ser.validated_data, request.user)
        refreshed = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=entity.pk)
        )
        return Response(NodeDetailSerializer(refreshed).data)

    def perform_destroy(self, instance):
        NodeService.deactivate_entity(instance.pk, reason='Deactivated via API', user=self.request.user)

    def _paginated(self, qs, serializer_class):
        """Paginate a related queryset using the viewset's paginator.

        Tree endpoints (children/subtree/team) can return tens of thousands of
        rows for a high node; they must page like the list endpoint, not dump
        the whole subtree into one response.
        """
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(serializer_class(page, many=True).data)
        return Response(serializer_class(qs, many=True).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_children',
        summary='Direct children',
        responses={200: NodeListSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='children')
    def children(self, request, pk=None):
        entity = self.get_object()
        qs = entity.get_direct_children().select_related('entity_type', 'parent', 'channel').order_by('name')
        return self._paginated(qs, NodeListSerializer)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_subtree',
        summary='All descendants',
        responses={200: NodeSubtreeSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='subtree')
    def subtree(self, request, pk=None):
        entity = self.get_object()
        qs = entity.get_subtree().select_related('entity_type', 'parent', 'channel', 'user').order_by('path')
        return self._paginated(qs, NodeSubtreeSerializer)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_ancestors',
        summary='Ancestor chain from entity to root',
        responses={200: NodeListSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='ancestors')
    def ancestors(self, request, pk=None):
        entity = self.get_object()
        return Response(NodeListSerializer(entity.get_ancestors(), many=True).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_team',
        summary='All descendants, optionally filtered by entity type',
        parameters=[
            OpenApiParameter(
                'types',
                description='Comma-separated entity type codes, e.g. ase,som',
                required=False,
                type=str,
            ),
        ],
        responses={200: NodeListSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='team')
    def team(self, request, pk=None):
        entity = self.get_object()
        raw = request.query_params.get('types', '')
        type_codes = [c.strip() for c in raw.split(',') if c.strip()] or None
        qs = entity.get_team(entity_type_codes=type_codes).select_related(
            'entity_type', 'parent', 'channel',
        ).order_by('name')
        return self._paginated(qs, NodeListSerializer)


    @extend_schema(
        tags=['Entities'],
        operation_id='entity_move',
        summary='Move entity to a new parent',
        description=(
            'Recomputes the materialized path for the entity and every descendant. '
            'Validates that the new parent type is allowed. Logs reason + effective date.'
        ),
        request=NodeMoveSerializer,
        responses={200: NodeDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='move')
    def move(self, request, pk=None):
        entity = self.get_object()
        ser = NodeMoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        moved = NodeService.move_entity(
            entity_id=entity.pk,
            new_parent_id=ser.validated_data['new_parent_id'],
            reason=ser.validated_data['reason'],
            effective_date=ser.validated_data['effective_date'],
            user=request.user,
        )
        moved_with_rels = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=moved.pk)
        )
        return Response(NodeDetailSerializer(moved_with_rels).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_transfer',
        summary='Transfer a person and settle their territories (team stays)',
        description=(
            'One atomic transfer across both trees. Direct reports are promoted to the '
            'entity\'s parent (or reassign_reports_to). The person lands per mode: '
            'new_seat (node moves under new_parent_id) or occupy_vacant (User relinked '
            'onto a vacant seat of the same type; territories on that seat come with it). '
            'Their owned territories are settled per territory_handover: successor '
            '(all transfer to successor_id), release (left unowned), or keep (they keep '
            'covering them). Distinct from move, which relocates the entire subtree.'
        ),
        request=NodeTransferSerializer,
        responses={200: NodeDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='transfer')
    def transfer(self, request, pk=None):
        entity = self.get_object()
        ser = NodeTransferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        result = TransferService.transfer_person(
            entity_id=entity.pk,
            mode=v['mode'],
            reason=v['reason'],
            effective_date=v['effective_date'],
            user=request.user,
            new_parent_id=v.get('new_parent_id'),
            target_entity_id=v.get('target_entity_id'),
            territory_handover=v.get('territory_handover', 'keep'),
            successor_id=v.get('successor_id'),
            reassign_reports_to=v.get('reassign_reports_to'),
        )
        refreshed = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=result.pk)
        )
        return Response(NodeDetailSerializer(refreshed).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_transfer_impact',
        summary='What a transfer of this entity would touch',
        description=(
            'Read-only preview for the transfer wizard: current placement, owned '
            'territories (open owner assignments) and direct reports. Called on a '
            'vacant seat, it shows the territories that come with that seat.'
        ),
        responses={200: OpenApiResponse(description='Impact summary')},
    )
    @action(detail=True, methods=['get'], url_path='transfer-impact')
    def transfer_impact(self, request, pk=None):
        entity = self.get_object()
        return Response(TransferService.transfer_impact(entity.pk))

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_reactivate',
        summary='Reactivate a deactivated entity',
        description=(
            'Sets status=active and re-enables the linked user account. Fails with 422 if the '
            'parent is inactive (reactivate the parent first). Ended relationships are not restored.'
        ),
        responses={200: NodeDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='reactivate')
    def reactivate(self, request, pk=None):
        entity = self.get_object()
        reason = request.data.get('reason', '') or 'Reactivated via API'
        NodeService.reactivate_entity(entity.pk, reason=reason, user=request.user)
        refreshed = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=entity.pk)
        )
        return Response(NodeDetailSerializer(refreshed).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_change_type',
        summary='Change an entity type (promote / demote)',
        description=(
            'Change an entity\'s type in place — e.g. promote ASM → RSM. Validates the new '
            'placement (both-direction type rules), re-validates attributes against the new '
            'schema, swaps the linked user role, and audits the change. If the entity has direct '
            'reports that are invalid under the new type, pass reassign_reports_to to move them.'
        ),
        request=NodeChangeTypeSerializer,
        responses={200: NodeDetailSerializer},
    )
    @action(detail=True, methods=['post'], url_path='change-type')
    def change_type(self, request, pk=None):
        entity = self.get_object()
        ser = NodeChangeTypeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        NodeService.change_entity_type(
            entity_id=entity.pk,
            new_type_id=v['new_type_id'],
            new_parent_id=v.get('new_parent_id'),
            attributes=v.get('attributes'),
            reason=v['reason'],
            effective_date=v.get('effective_date') or date.today(),
            user=request.user,
            reassign_reports_to=v.get('reassign_reports_to'),
        )
        refreshed = (
            Node.objects
            .select_related('entity_type', 'parent__entity_type', 'channel')
            .get(pk=entity.pk)
        )
        return Response(NodeDetailSerializer(refreshed).data)


    @extend_schema(
        tags=['Entities'],
        operation_id='entity_bulk_import',
        summary='Bulk import entities',
        description=(
            'Import entities from a JSON array or CSV file. All-or-nothing: '
            'if any row fails validation, nothing is created and row-level errors are returned.\n\n'
            '• dry_run=true → validate only, returns {status: valid|validation_failed} and creates nothing.\n'
            '• run_async=true (or more than the async threshold of rows) → returns 202 with a '
            'bulk job to poll at /api/v1/jobs/{id}/.'
        ),
        request=NodeBulkImportSerializer,
        responses={
            200: OpenApiResponse(description='Sync success or dry-run preview'),
            202: BulkJobSerializer,
            422: OpenApiResponse(description='Validation failed — {status, errors: [{row, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk', throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = NodeBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        fmt = ser.validated_data.get('format', 'json')
        uploaded = ser.validated_data.get('file')
        raw = ser.validated_data.get('data', '')
        dry_run = ser.validated_data.get('dry_run', False)
        run_async = ser.validated_data.get('run_async', False)

        if uploaded:
            raw = uploaded.read().decode('utf-8')

        if dry_run:
            result = NodeService.bulk_import(raw, fmt=fmt, user=request.user, dry_run=True)
            code = status.HTTP_200_OK if result['status'] == 'valid' else status.HTTP_422_UNPROCESSABLE_ENTITY
            return Response(result, status=code)

        if run_async or count_rows(raw, fmt) > BULK_ASYNC_THRESHOLD:
            from apps.hierarchy.tasks import import_entities_task

            job = JobService.create(
                BulkJob.JobType.ENTITY_IMPORT, request.user,
                total_rows=count_rows(raw, fmt),
                request_id=getattr(request, 'request_id', ''),
            )
            job = run_or_dispatch(import_entities_task, job, raw, fmt, request.user.pk)
            return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

        result = NodeService.bulk_import(raw, fmt=fmt, user=request.user)
        if result.get('status') == 'validation_failed':
            return Response(result, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_bulk_move',
        summary='Bulk transfer entities to a new parent',
        description=(
            'Move many entities (and their subtrees) under one new parent. All-or-nothing: '
            'every entity is validated first; if any fails, nothing moves and per-entity errors '
            'are returned. Each move recomputes descendant paths and is audited.'
        ),
        request=NodeBulkMoveSerializer,
        responses={
            200: OpenApiResponse(description='Success — {status, moved}'),
            422: OpenApiResponse(description='Validation failed — {status, errors: [{id, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk-move')
    def bulk_move(self, request):
        ser = NodeBulkMoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = NodeService.bulk_move(
            entity_ids=ser.validated_data['entity_ids'],
            new_parent_id=ser.validated_data['new_parent_id'],
            reason=ser.validated_data['reason'],
            effective_date=ser.validated_data['effective_date'],
            user=request.user,
        )
        code = status.HTTP_200_OK if result['status'] == 'success' else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(result, status=code)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_bulk_deactivate',
        summary='Bulk deactivate entities',
        description=(
            'Soft-deactivate many entities. cascade=false rejects an entity with active children '
            'unless those children are also selected; cascade=true deactivates each entity\'s '
            'entire subtree. All-or-nothing.'
        ),
        request=NodeBulkDeactivateSerializer,
        responses={
            200: OpenApiResponse(description='Success — {status, deactivated}'),
            422: OpenApiResponse(description='Validation failed — {status, errors: [{id, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk-deactivate')
    def bulk_deactivate(self, request):
        ser = NodeBulkDeactivateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = NodeService.bulk_deactivate(
            entity_ids=ser.validated_data['entity_ids'],
            reason=ser.validated_data['reason'],
            user=request.user,
            cascade=ser.validated_data['cascade'],
        )
        code = status.HTTP_200_OK if result['status'] == 'success' else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(result, status=code)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_bulk_reactivate',
        summary='Bulk reactivate entities',
        description=(
            'Reactivate many entities (status → active, linked users re-enabled). All-or-nothing; '
            'reactivated parent-first. A child whose parent is inactive is rejected unless the '
            'parent is also selected.'
        ),
        request=NodeBulkReactivateSerializer,
        responses={
            200: OpenApiResponse(description='Success — {status, reactivated}'),
            422: OpenApiResponse(description='Validation failed — {status, errors: [{id, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk-reactivate')
    def bulk_reactivate(self, request):
        ser = NodeBulkReactivateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = NodeService.bulk_reactivate(
            entity_ids=ser.validated_data['entity_ids'],
            reason=ser.validated_data.get('reason', '') or 'Bulk reactivated via API',
            user=request.user,
        )
        code = status.HTTP_200_OK if result['status'] == 'success' else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(result, status=code)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_search',
        summary='Search entities by name or code',
        parameters=[
            OpenApiParameter('q', description='Search term matched against name and code', required=False, type=str),
            OpenApiParameter('type', description='Limit results to this entity_type code', required=False, type=str),
        ],
        responses={200: NodeListSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        q = request.query_params.get('q', '').strip()
        type_code = request.query_params.get('type', '').strip()

        qs = (
            Node.objects
            .filter(is_current=True, is_active=True)
            .select_related('entity_type', 'parent', 'channel')
        )
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        if type_code:
            qs = qs.filter(entity_type__code=type_code)

        qs = self.scope_queryset(qs)
        return Response(NodeListSerializer(qs[:50], many=True).data)

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_counts',
        summary='Node counts grouped by entity type',
        description='Returns {counts: {type_code: n}, total: n} scoped to the requester. '
                    'Lets the blueprint panel show counts without loading every entity.',
        responses={200: OpenApiResponse(description='{counts: {code: int}, total: int}')},
    )
    @action(detail=False, methods=['get'], url_path='counts')
    def counts(self, request):
        qs = self.scope_queryset(
            Node.objects.filter(is_current=True, is_active=True)
        )
        rows = qs.values('entity_type__code').annotate(n=Count('id'))
        counts = {r['entity_type__code']: r['n'] for r in rows if r['entity_type__code']}
        return Response({'counts': counts, 'total': sum(counts.values())})

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_export',
        summary='Export entities as CSV',
        description=(
            'Stream the current (filtered) entity list as a CSV download. Honours the same '
            '?type, ?channel, ?status, ?parent filters as the list endpoint. The output is a '
            'valid bulk-import file (re-importable; the derived `path`/`status` columns are ignored on import).'
        ),
        parameters=_ENTITY_QUERY_PARAMS,
        responses={200: OpenApiResponse(description='CSV file')},
    )
    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        fieldnames, rows = NodeService.export_stream(self.get_queryset())

        # Echo-writer streaming: each writerow returns the encoded line, so the
        # response never buffers the file — 150k entities stream in constant memory.
        class _Echo:
            def write(self, value):
                return value

        writer = csv.DictWriter(_Echo(), fieldnames=fieldnames)

        def _lines():
            yield writer.writeheader()
            for row in rows:
                yield writer.writerow(row)

        response = StreamingHttpResponse(_lines(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="entities.csv"'
        return response

    @extend_schema(
        tags=['Entities'],
        operation_id='entity_import_template',
        summary='Download an import template for an entity type',
        description=(
            'Generate a CSV template whose columns are built dynamically from the entity '
            'type\'s attribute schema (one column per field), with a sample row.'
        ),
        parameters=[
            OpenApiParameter('entity_type', description='Node type code', required=True, type=str),
        ],
        responses={200: OpenApiResponse(description='CSV template file')},
    )
    @action(detail=False, methods=['get'], url_path='import-template')
    def import_template(self, request):
        code = request.query_params.get('entity_type', '').strip()
        if not code:
            raise BusinessError('entity_type query parameter is required.')
        entity_type = NodeType.objects.filter(
            code=code, is_current=True, is_active=True,
        ).first()
        if entity_type is None:
            raise BusinessError(f"NodeType code '{code}' not found.")

        fieldnames, sample = NodeService.import_template(entity_type)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(sample)
        response = HttpResponse(buffer.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{code}_import_template.csv"'
        return response



@extend_schema_view(
    list=extend_schema(tags=['Geography'], summary='List geography types'),
    retrieve=extend_schema(tags=['Geography'], summary='Retrieve geography type'),
    create=extend_schema(tags=['Geography'], summary='Create geography type'),
    update=extend_schema(tags=['Geography'], summary='Update geography type'),
    partial_update=extend_schema(tags=['Geography'], summary='Partial update geography type'),
    destroy=extend_schema(tags=['Geography'], summary='Delete geography type'),
)
class GeographyTypeViewSet(ModelViewSet):
    serializer_class = GeographyTypeSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        return GeographyType.objects.filter(is_active=True).order_by('name')

    def perform_create(self, serializer):
        serializer.instance = GeographyTypeService.create(
            serializer.validated_data, actor=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.instance = GeographyTypeService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        GeographyTypeService.deactivate(instance, actor=self.request.user)


@extend_schema_view(
    list=extend_schema(
        tags=['Geography'],
        summary='List geography nodes',
        parameters=[
            OpenApiParameter('type', description='Filter by geography_type code', required=False, type=str),
            OpenApiParameter('level', description='Filter by level name', required=False, type=str),
            OpenApiParameter('levels', description='CSV of level names (level-constrained pickers)', required=False, type=str),
            OpenApiParameter('parent', description='Filter by parent node ID', required=False, type=int),
        ],
    ),
    retrieve=extend_schema(tags=['Geography'], summary='Retrieve geography node'),
    create=extend_schema(tags=['Geography'], summary='Create geography node'),
    update=extend_schema(tags=['Geography'], summary='Update geography node'),
    partial_update=extend_schema(tags=['Geography'], summary='Partial update geography node'),
    destroy=extend_schema(tags=['Geography'], summary='Delete geography node'),
)
class GeographyNodeViewSet(ModelViewSet):
    serializer_class = GeographyNodeSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        qs = GeographyNode.objects.filter(is_active=True).select_related('geography_type', 'parent')
        params = self.request.query_params
        if geo_type := params.get('type'):
            qs = qs.filter(geography_type__code=geo_type)
        if level := params.get('level'):
            qs = qs.filter(level=level)
        if levels := params.get('levels'):
            wanted = [l for l in (part.strip() for part in levels.split(',')) if l]
            if wanted:
                qs = qs.filter(level__in=wanted)
        if parent_id := params.get('parent'):
            qs = qs.filter(parent_id=parent_id)
        if q := params.get('q', '').strip():
            # Searchable territory pickers query by term instead of loading every node.
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        return qs.order_by('path')

    @extend_schema(
        tags=['Geography'],
        operation_id='geography_node_tree',
        summary='Root geography nodes for a type (lazy tree load)',
        description='Returns the top-level (parentless) nodes for a geography type. '
                    'Children are loaded lazily via the subtree/children endpoints.',
        parameters=[
            OpenApiParameter('type', description='Geography type code', required=True, type=str),
        ],
        responses={200: GeographyNodeSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='tree')
    def tree(self, request):
        code = request.query_params.get('type', '').strip()
        if not code:
            raise BusinessError('type query parameter is required.')
        qs = (
            GeographyNode.objects
            .filter(geography_type__code=code, parent__isnull=True, is_active=True)
            .select_related('geography_type', 'parent')
            .order_by('name')
        )
        # Roots are normally few, but a flat geography (all nodes parentless)
        # must not dump the whole table — paginate like every other list.
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(GeographyNodeSerializer(page, many=True).data)
        return Response(GeographyNodeSerializer(qs, many=True).data)

    @extend_schema(
        tags=['Geography'],
        operation_id='geography_node_subtree',
        summary='All descendants of a geography node',
        responses={200: GeographyNodeSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='subtree')
    def subtree(self, request, pk=None):
        node = self.get_object()
        qs = (
            node.get_subtree()
            .select_related('geography_type', 'parent')
            .order_by('path')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(GeographyNodeSerializer(page, many=True).data)
        return Response(GeographyNodeSerializer(qs, many=True).data)

    @extend_schema(
        tags=['Geography'],
        operation_id='geography_node_ancestors',
        summary='Ancestor chain of a geography node',
        responses={200: GeographyNodeSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='ancestors')
    def ancestors(self, request, pk=None):
        node = self.get_object()
        return Response(GeographyNodeSerializer(node.get_ancestors(), many=True).data)

    @extend_schema(
        tags=['Geography'],
        operation_id='geography_node_move',
        summary='Reparent a geography node (recomputes descendant paths)',
        request=GeographyNodeMoveSerializer,
        responses={200: GeographyNodeSerializer},
    )
    @action(detail=True, methods=['post'], url_path='move')
    def move(self, request, pk=None):
        ser = GeographyNodeMoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        node = GeographyNodeService.move(
            int(pk), ser.validated_data['new_parent_id'], actor=request.user,
        )
        refreshed = (
            GeographyNode.objects.select_related('geography_type', 'parent').get(pk=node.pk)
        )
        return Response(GeographyNodeSerializer(refreshed).data)

    @extend_schema(
        tags=['Geography'],
        operation_id='geography_node_bulk_import',
        summary='Bulk import geography nodes (territories)',
        description=(
            'Import territories from a JSON array or CSV. Columns: geography_type_code, '
            'name, code, parent_code, level, attributes_json. A parent may be an existing '
            'node or another row in the same file. All-or-nothing: any row error rolls '
            'back the whole batch.\n\n'
            '• dry_run=true → validate only.\n'
            '• run_async=true (or more than the async threshold of rows) → returns 202 '
            'with a bulk job to poll at /api/v1/jobs/{id}/.'
        ),
        request=NodeBulkImportSerializer,
        responses={
            200: OpenApiResponse(description='Sync success or dry-run preview'),
            202: BulkJobSerializer,
            422: OpenApiResponse(description='Validation failed — {status, errors: [{row, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk', throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = NodeBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        fmt = ser.validated_data.get('format', 'json')
        uploaded = ser.validated_data.get('file')
        raw = ser.validated_data.get('data', '')
        dry_run = ser.validated_data.get('dry_run', False)
        run_async = ser.validated_data.get('run_async', False)

        if uploaded:
            raw = uploaded.read().decode('utf-8')

        if dry_run:
            result = GeographyNodeService.bulk_import(raw, fmt=fmt, user=request.user, dry_run=True)
            code = status.HTTP_200_OK if result['status'] == 'valid' else status.HTTP_422_UNPROCESSABLE_ENTITY
            return Response(result, status=code)

        if run_async or count_rows(raw, fmt) > BULK_ASYNC_THRESHOLD:
            from apps.hierarchy.tasks import import_geography_task

            job = JobService.create(
                BulkJob.JobType.GEOGRAPHY_IMPORT, request.user,
                total_rows=count_rows(raw, fmt),
                request_id=getattr(request, 'request_id', ''),
            )
            job = run_or_dispatch(import_geography_task, job, raw, fmt, request.user.pk)
            return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

        result = GeographyNodeService.bulk_import(raw, fmt=fmt, user=request.user)
        if result.get('status') == 'validation_failed':
            return Response(result, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        serializer.instance = GeographyNodeService.create(
            serializer.validated_data, actor=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.instance = GeographyNodeService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        GeographyNodeService.deactivate(instance, actor=self.request.user)



@extend_schema_view(
    list=extend_schema(tags=['Relationships'], summary='List relationship types'),
    retrieve=extend_schema(tags=['Relationships'], summary='Retrieve relationship type'),
    create=extend_schema(tags=['Relationships'], summary='Create relationship type'),
    update=extend_schema(tags=['Relationships'], summary='Update relationship type'),
    partial_update=extend_schema(tags=['Relationships'], summary='Partial update relationship type'),
    destroy=extend_schema(tags=['Relationships'], summary='Delete relationship type'),
)
class RelationshipTypeViewSet(ModelViewSet):
    serializer_class = RelationshipTypeSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        return RelationshipType.objects.filter(is_active=True).select_related(
            'from_entity_type', 'to_entity_type',
        ).order_by('name')

    def perform_create(self, serializer):
        serializer.instance = RelationshipTypeService.create(
            serializer.validated_data, actor=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.instance = RelationshipTypeService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        RelationshipTypeService.deactivate(instance, actor=self.request.user)


@extend_schema_view(
    list=extend_schema(
        tags=['Relationships'],
        summary='List entity relationships',
        parameters=[
            OpenApiParameter('entity', description='Node ID — return relationships where from or to matches', required=False, type=int),
            OpenApiParameter('type', description='Filter by relationship type code', required=False, type=str),
            OpenApiParameter('direction', description='from | to | both (default: both)', required=False, type=str),
        ],
    ),
    retrieve=extend_schema(tags=['Relationships'], summary='Retrieve entity relationship'),
    create=extend_schema(tags=['Relationships'], summary='Create entity relationship'),
    update=extend_schema(tags=['Relationships'], summary='Update entity relationship'),
    partial_update=extend_schema(tags=['Relationships'], summary='Partial update entity relationship'),
    destroy=extend_schema(
        tags=['Relationships'],
        summary='End relationship',
        description='Sets effective_to = today and marks inactive.',
    ),
)
class NodeRelationshipViewSet(ModelViewSet):
    serializer_class = NodeRelationshipSerializer
    required_permission = 'hierarchy_management'

    def get_queryset(self):
        qs = (
            NodeRelationship.objects
            .filter(is_active=True)
            .select_related('relationship_type', 'from_entity', 'to_entity')
        )
        params = self.request.query_params
        entity_id = params.get('entity')
        rel_type = params.get('type')
        direction = params.get('direction', 'both')

        if entity_id:
            if direction == 'from':
                qs = qs.filter(from_entity_id=entity_id)
            elif direction == 'to':
                qs = qs.filter(to_entity_id=entity_id)
            else:
                qs = qs.filter(Q(from_entity_id=entity_id) | Q(to_entity_id=entity_id))
        if rel_type:
            qs = qs.filter(relationship_type__code=rel_type)

        return qs.order_by('-effective_from')

    def perform_create(self, serializer):
        serializer.instance = NodeRelationshipService.create(
            serializer.validated_data, actor=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.instance = NodeRelationshipService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        NodeRelationshipService.end(instance, actor=self.request.user)
