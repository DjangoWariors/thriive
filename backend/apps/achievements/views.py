from drf_spectacular.utils import (
    OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import _rank, highest_level
from apps.core.pagination import StandardPagination
from apps.core.scoping import NodeScopedQuerysetMixin, is_planning_admin, requester_can_reach_entity
from apps.hierarchy.models import Node
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.kpi_engine.serializers import ExternalMetricValueSerializer, TransactionSerializer
from apps.targets.models import TargetPeriod

from .models import Achievement, AchievementSnapshot, Alert, AlertRule
from .serializers import (
    AchievementDetailSerializer,
    AchievementListSerializer,
    AlertRuleSerializer,
    AlertSerializer,
    ComputeRequestSerializer,
    DashboardSerializer,
    SnapshotSerializer,
)
from .services import AchievementService, DashboardService

_COMPUTE_PERM = 'achievement_compute'

_LIST_PARAMS = [
    OpenApiParameter('period', description='TargetPeriod id', required=False, type=int),
    OpenApiParameter('kpi', description='KPIDefinition id', required=False, type=int),
    OpenApiParameter('entity', description='Node id', required=False, type=int),
    OpenApiParameter('channel', description='Channel code', required=False, type=str),
    OpenApiParameter('entity_type', description='Node type code', required=False, type=str),
]


@extend_schema_view(
    list=extend_schema(tags=['Achievements'], summary='List achievements (subtree-scoped)',
                       parameters=_LIST_PARAMS),
    retrieve=extend_schema(tags=['Achievements'], summary='Retrieve an achievement'),
)
class AchievementViewSet(NodeScopedQuerysetMixin, ReadOnlyModelViewSet):
    required_permission = 'achievement_view'
    scope_path_field = 'entity__path'
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return AchievementListSerializer if self.action == 'list' else AchievementDetailSerializer

    def get_queryset(self):
        qs = Achievement.objects.select_related('kpi', 'entity', 'channel', 'target_period')
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if kpi := p.get('kpi'):
            qs = qs.filter(kpi_id=kpi)
        if entity := p.get('entity'):
            qs = qs.filter(entity_id=entity)
        if channel := p.get('channel'):
            qs = qs.filter(channel__code=channel)
        if etype := p.get('entity_type'):
            qs = qs.filter(entity__entity_type__code=etype)
        return self.scope_queryset(qs).order_by('-achievement_pct')

    # ── dashboard ──────────────────────────────────────────────────────────
    @extend_schema(
        tags=['Achievements'], operation_id='achievement_dashboard',
        summary='Role-adaptive dashboard for an entity',
        parameters=[
            OpenApiParameter('period', description='TargetPeriod id', required=True, type=int),
            OpenApiParameter('entity', description='Node id (defaults to own entity)', required=False, type=int),
        ],
        responses={200: DashboardSerializer},
    )
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        period = self._period(request)
        entity = None
        if eid := request.query_params.get('entity'):
            try:
                entity = Node.objects.get(pk=int(eid))
            except (ValueError, Node.DoesNotExist):
                raise NotFound('Entity not found.')
        data = DashboardService.build(request.user, period, entity=entity)
        return Response(data)

    @extend_schema(
        tags=['Achievements'], operation_id='achievement_drilldown',
        summary='Gross/returns/net breakdown + paginated transactions',
        responses={200: TransactionSerializer(many=True)},
    )
    @action(detail=True, methods=['get'])
    def drilldown(self, request, pk=None):
        ach, rows, row_kind = AchievementService.drilldown(int(pk), request.user)
        row_serializer = (
            ExternalMetricValueSerializer if row_kind == 'metric_values' else TransactionSerializer
        )
        page = self.paginate_queryset(rows)
        row_data = row_serializer(page if page is not None else rows, many=True).data
        breakdown = {
            'achievement': AchievementDetailSerializer(ach).data,
            'gross_value': str(ach.gross_value),
            'returns_value': str(ach.returns_value),
            'net_value': str(ach.achieved_value),
            'row_kind': row_kind,
        }
        if page is not None:
            paginated = self.get_paginated_response(row_data)
            paginated.data['breakdown'] = breakdown
            return paginated
        return Response({'breakdown': breakdown, 'results': row_data})

    @extend_schema(
        tags=['Achievements'], operation_id='achievement_territory',
        summary='Plan-tracking grid: one geography level (lazy, territory-scoped)',
        parameters=[
            OpenApiParameter('kpi', description='KPIDefinition id', required=True, type=int),
            OpenApiParameter('period', description='TargetPeriod id', required=True, type=int),
            OpenApiParameter('parent', description='GeographyNode id (root if omitted)', type=int),
            OpenApiParameter('channel', description='Channel code (all-channel row if omitted)', type=str),
            OpenApiParameter('channel_id', description='Channel id (alternative to channel code)', type=int),
            OpenApiParameter('sku_group', description='SKUGroup id (all-SKU row if omitted)', type=int),
            OpenApiParameter('page', type=int), OpenApiParameter('page_size', type=int),
        ],
        responses={200: OpenApiResponse(description='{ parent, rows, page, total }')},
    )
    @action(detail=False, methods=['get'])
    def territory(self, request):
        from apps.core.scoping import scope_transactions_by_territory
        from apps.hierarchy.models import GeographyNode
        from apps.kpi_engine.models import KPIDefinition

        p = request.query_params
        try:
            kpi = KPIDefinition.objects.get(pk=p['kpi'])
            period = TargetPeriod.objects.get(pk=p['period'])
        except (KeyError, KPIDefinition.DoesNotExist, TargetPeriod.DoesNotExist):
            raise ValidationError({'detail': 'kpi and period are required and must exist.'})
        # Territory RBAC: a scoped user only sees nodes inside the territories they own.
        children_qs = scope_transactions_by_territory(
            GeographyNode.objects.filter(is_active=True), request.user,
            self.required_permission, field='id',
        )
        data = AchievementService.territory_grid(
            kpi, period,
            parent_id=int(p['parent']) if p.get('parent') else None,
            channel_code=p.get('channel') or None,
            channel_id=int(p['channel_id']) if p.get('channel_id') else None,
            sku_group_id=int(p['sku_group']) if p.get('sku_group') else None,
            children_qs=children_qs,
            page=int(p.get('page', 1)), page_size=int(p.get('page_size', 100)),
        )
        return Response(data)

    @extend_schema(
        tags=['Achievements'], operation_id='achievement_team',
        summary='Subtree achievements (manager view)', parameters=_LIST_PARAMS,
        responses={200: AchievementListSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def team(self, request):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        ser = AchievementListSerializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(
        tags=['Achievements'], operation_id='achievement_snapshots',
        summary='Daily snapshot trend for an entity/KPI/period',
        parameters=[
            OpenApiParameter('entity', required=True, type=int),
            OpenApiParameter('kpi', required=True, type=int),
            OpenApiParameter('period', required=True, type=int),
        ],
        responses={200: SnapshotSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def snapshots(self, request):
        p = request.query_params
        try:
            entity = Node.objects.get(pk=int(p['entity']))
            kpi_id, period_id = int(p['kpi']), int(p['period'])
        except (KeyError, ValueError, Node.DoesNotExist):
            raise ValidationError({'detail': 'entity, kpi and period are required and must exist.'})
        # detail=False action → object permissions never run; enforce subtree reach here.
        if not requester_can_reach_entity(request.user, self.required_permission, entity):
            raise PermissionDenied('You do not have access to this entity.')
        qs = AchievementSnapshot.objects.filter(
            achievement__entity=entity,
            achievement__kpi_id=kpi_id,
            achievement__target_period_id=period_id,
        ).order_by('snapshot_date')
        return Response(SnapshotSerializer(qs, many=True).data)

    @extend_schema(
        tags=['Achievements'], operation_id='achievement_compute',
        summary='Trigger achievement computation for a period (admin)',
        request=ComputeRequestSerializer, responses={202: BulkJobSerializer},
    )
    @action(detail=False, methods=['post'])
    def compute(self, request):
        if not request.user.is_superuser and _rank(highest_level(request.user, _COMPUTE_PERM)) <= 0:
            raise PermissionDenied('You do not have permission to compute achievements.')
        ser = ComputeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        period_id = ser.validated_data['period_id']
        get_object_or_404_period(period_id)
        job = JobService.create(
            BulkJob.JobType.ACHIEVEMENT_COMPUTE, request.user,
            request_id=getattr(request, 'request_id', ''),
        )
        job = run_or_dispatch(_compute_task_ref(), job, period_id, request.user.pk)
        return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    def _period(self, request):
        period_id = request.query_params.get('period')
        if not period_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'period': 'This query parameter is required.'})
        return get_object_or_404_period(period_id)


def get_object_or_404_period(period_id):
    from rest_framework.generics import get_object_or_404
    return get_object_or_404(TargetPeriod, pk=period_id)


def _compute_task_ref():
    from apps.achievements.tasks import compute_daily_achievements
    return compute_daily_achievements


@extend_schema_view(
    list=extend_schema(tags=['Achievements'], summary='List alerts (subtree-scoped)'),
    partial_update=extend_schema(tags=['Achievements'], summary='Acknowledge / resolve an alert'),
)
class AlertViewSet(NodeScopedQuerysetMixin, ReadOnlyModelViewSet):
    required_permission = 'achievement_view'
    scope_path_field = 'entity__path'
    serializer_class = AlertSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Alert.objects.select_related('rule', 'entity', 'kpi')
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if status_ := p.get('status'):
            qs = qs.filter(status=status_)
        return self.scope_queryset(qs)

    @extend_schema(tags=['Achievements'], operation_id='alert_acknowledge',
                   summary='Acknowledge an alert', request=None, responses={200: AlertSerializer})
    @action(detail=True, methods=['patch'])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        alert.status = Alert.ACKNOWLEDGED
        alert.save(update_fields=['status', 'updated_at'])
        return Response(AlertSerializer(alert).data)


@extend_schema_view(
    list=extend_schema(tags=['Achievements'], summary='List alert rules'),
    create=extend_schema(tags=['Achievements'], summary='Create an alert rule'),
    update=extend_schema(tags=['Achievements'], summary='Update an alert rule (new version)'),
    destroy=extend_schema(tags=['Achievements'], summary='Deactivate an alert rule'),
)
class AlertRuleViewSet(ModelViewSet):
    required_permission = 'achievement_view'
    serializer_class = AlertRuleSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return AlertRule.objects.filter(is_current=True, is_active=True).order_by('code')

    def _require_admin(self):
        if not is_planning_admin(self.request.user, self.required_permission):
            raise PermissionDenied('Only plan-wide operators can manage alert rules.')

    def perform_create(self, serializer):
        self._require_admin()
        serializer.save()

    def perform_update(self, serializer):
        self._require_admin()
        instance = serializer.instance
        instance.create_new_version(**serializer.validated_data)

    def perform_destroy(self, instance):
        self._require_admin()
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
