from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError
from apps.core.pagination import StandardPagination
from apps.core.permissions import LevelRBACPermission
from apps.core.scoping import (
    is_planning_admin,
    requester_can_reach_entity,
    scope_transactions_by_territory,
)
from apps.hierarchy.models import Channel, GeographyNode, Node
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.jobs.utils import count_rows
from apps.kpi_engine.models import KPIDefinition
from apps.master_data.models import SKUGroup

from .models import (
    AllocationRecipe,
    PlanRun,
    ReviewTask,
    RevisionPolicy,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
)
from .plan_services import PlanService
from .review_services import ReviewService
from .serializers import (
    AllocationBulkImportSerializer,
    AllocationRecipeSerializer,
    ApproveAllSerializer,
    CommitRunSerializer,
    ForceCloseSerializer,
    GenerateYearSerializer,
    ModifyAllocationSerializer,
    PlanRunSerializer,
    PlanTransitionSerializer,
    PreflightSerializer,
    RealignSerializer,
    RejectAllocationSerializer,
    ReviewAcceptSerializer,
    ReviewAdjustMineSerializer,
    ReviewAdjustSerializer,
    ReviewTaskSerializer,
    RevisionPolicySerializer,
    SetPlanTopSerializer,
    StartRunSerializer,
    TargetAllocationSerializer,
    TargetPeriodNodeSerializer,
    TargetPeriodSerializer,
    TargetPlanCreateSerializer,
    TargetPlanSerializer,
    TargetRevisionSerializer,
)
from .services import TargetService

PERM = 'target_management'


def _opt(model, pk):
    return model.objects.filter(pk=pk).first() if pk else None


@extend_schema_view(
    list=extend_schema(tags=['Targets'], summary='List target periods'),
    retrieve=extend_schema(tags=['Targets'], summary='Retrieve target period'),
    create=extend_schema(tags=['Targets'], summary='Create target period'),
    destroy=extend_schema(tags=['Targets'], summary='Deactivate target period'),
)
class TargetPeriodViewSet(ModelViewSet):
    serializer_class = TargetPeriodSerializer
    required_permission = PERM
    # Targets are geography-anchored (no org-entity FK): object access is level-only;
    # every mutation below is additionally plan-admin-gated.
    permission_classes = [LevelRBACPermission]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = TargetPeriod.objects.filter(is_active=True)
        params = self.request.query_params
        if fy := params.get('fiscal_year'):
            qs = qs.filter(fiscal_year=fy)
        if ptype := params.get('period_type'):
            qs = qs.filter(period_type=ptype)
        if 'roots_only' in params:
            qs = qs.filter(parent__isnull=True)
        return qs.order_by('start_date', 'code')

    def perform_create(self, serializer):
        _plan_admin_or_403(self.request, self.required_permission)
        serializer.instance = TargetService.create_period(serializer.validated_data, actor=self.request.user)

    def perform_destroy(self, instance):
        _plan_admin_or_403(self.request, self.required_permission)
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    # Period status is derived (plan publish / cycle finalize / cycle close via
    # TargetService.advance_period) — there are no manual transition endpoints.

    @extend_schema(tags=['Targets'], summary='Period tree (this period + descendants)',
                   responses={200: TargetPeriodNodeSerializer})
    @action(detail=True, methods=['get'])
    def tree(self, request, pk=None):
        return Response(TargetPeriodNodeSerializer(self.get_object()).data)

    @extend_schema(tags=['Targets'], summary='Generate a whole plan year (annual container + 12 months)',
                   request=GenerateYearSerializer, responses={201: TargetPeriodNodeSerializer})
    @action(detail=False, methods=['post'], url_path='generate-year')
    def generate_year(self, request):
        _plan_admin_or_403(request, self.required_permission)
        ser = GenerateYearSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        annual = TargetService.generate_fiscal_year(
            fiscal_year=d['fiscal_year'], start_month=d['start_month'],
            channel=_opt(Channel, d.get('channel_id')),
            working_days_per_month=d['working_days_per_month'], actor=request.user,
        )
        return Response(TargetPeriodNodeSerializer(annual).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=['Targets'], summary='Approve all pending allocations on this period',
                   request=ApproveAllSerializer)
    @action(detail=True, methods=['post'], url_path='approve-all')
    def approve_all(self, request, pk=None):
        period = self.get_object()
        ser = ApproveAllSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        scope = _opt(Node, ser.validated_data.get('scope_entity_id'))
        # A scoped manager may only approve within their subtree; default the scope to their
        # own entity, and reject an explicit scope outside it.
        home = getattr(request.user, 'entity', None)
        if not is_planning_admin(request.user, self.required_permission):
            if scope is None:
                scope = home
            elif not requester_can_reach_entity(request.user, self.required_permission, scope):
                raise BusinessError('That part of the hierarchy is outside your area.')
        return Response(TargetService.approve_all_pending(period, scope_entity=scope, actor=request.user))


_ALLOC_PARAMS = [
    OpenApiParameter('target_period', required=False, type=int),
    OpenApiParameter('kpi', required=False, type=int),
    OpenApiParameter('geography_node', required=False, type=int),
    OpenApiParameter('status', required=False, type=str),
]


@extend_schema_view(
    list=extend_schema(tags=['Targets'], summary='List target allocations', parameters=_ALLOC_PARAMS),
    retrieve=extend_schema(tags=['Targets'], summary='Retrieve allocation'),
)
class TargetAllocationViewSet(ReadOnlyModelViewSet):
    serializer_class = TargetAllocationSerializer
    required_permission = PERM
    # Object reach = the territory-scoped queryset below (a foreign allocation 404s);
    # writes go through revision governance (change caps + maker-checker) — the custom
    # actions below are the only POST surface (read-only base ⇒ no default create).
    permission_classes = [LevelRBACPermission]
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = TargetAllocation.objects.select_related('geography_node', 'kpi', 'target_period').filter(is_active=True)
        params = self.request.query_params
        for field in ('target_period', 'kpi', 'geography_node', 'channel', 'sku_group', 'status'):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        # Targets are geography-anchored → scope to the territories the requester owns.
        qs = scope_transactions_by_territory(
            qs, self.request.user, self.required_permission, field='geography_node_id')
        return qs.order_by('geography_node__path')

    @extend_schema(tags=['Targets'], summary='Override a target (optionally rebalancing siblings)',
                   request=ModifyAllocationSerializer, responses={200: TargetAllocationSerializer})
    @action(detail=True, methods=['post'])
    def modify(self, request, pk=None):
        allocation = self.get_object()
        ser = ModifyAllocationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        alloc = TargetService.modify_allocation(
            allocation, d['override_value'], reason=d.get('reason', ''),
            actor=request.user, rebalance=d.get('rebalance', True),
        )
        return Response(TargetAllocationSerializer(alloc).data)

    @extend_schema(tags=['Targets'], summary='Approve a single allocation', request=None,
                   responses={200: TargetAllocationSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        # Checker acts are HO acts: a placed editor must never self-approve — escalated
        # revisions route to their manager via the target_revision workflow instead.
        _plan_admin_or_403(request, self.required_permission)
        alloc = TargetService.approve_allocation(self.get_object(), actor=request.user)
        return Response(TargetAllocationSerializer(alloc).data)

    @extend_schema(tags=['Targets'], summary='Reject the latest pending revision (reverts the target)',
                   request=RejectAllocationSerializer, responses={200: TargetAllocationSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = RejectAllocationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        alloc = TargetService.reject_allocation(
            self.get_object(), actor=request.user, reason=ser.validated_data.get('reason', ''))
        return Response(TargetAllocationSerializer(alloc).data)

    @extend_schema(tags=['Targets'], summary='Revision history for one allocation',
                   responses={200: TargetRevisionSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def revisions(self, request, pk=None):
        qs = self.get_object().revisions.select_related('requested_by', 'approved_by').order_by('-created_at')
        return Response(TargetRevisionSerializer(qs, many=True).data)

    @extend_schema(tags=['Targets'], summary='Preflight: what would this change do (cap band)?',
                   request=PreflightSerializer,
                   responses={200: OpenApiResponse(description='{ outcome, delta_pct, policy_code, ... }')})
    @action(detail=True, methods=['post'])
    def preflight(self, request, pk=None):
        ser = PreflightSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(TargetService.preflight_revision(self.get_object(), ser.validated_data['override_value']))

    def _reach(self, entity):
        """Reject reaching an entity outside the requester's subtree (these detail=False
        actions never trigger object permissions, so guard explicitly)."""
        if not requester_can_reach_entity(self.request.user, self.required_permission, entity):
            raise BusinessError('That part of the hierarchy is outside your area.')

    @extend_schema(
        tags=['Targets'], summary='Per-user target view (User × Retailer × SKU)',
        parameters=[OpenApiParameter('period_id', required=True, type=int),
                    OpenApiParameter('kpi_id', required=True, type=int),
                    OpenApiParameter('entity_id', required=True, type=int),
                    OpenApiParameter('channel_id', required=False, type=int),
                    OpenApiParameter('sku_group_id', required=False, type=int),
                    OpenApiParameter('include_draft', required=False, type=bool)],
        responses={200: OpenApiResponse(description="A person's target rolled up from owned territories")},
    )
    @action(detail=False, methods=['get'], url_path='person-view')
    def person_view(self, request):
        p = request.query_params
        # Draft/in-review plan numbers are previewable only by planning admins.
        include_draft = (p.get('include_draft') in ('true', '1')
                         and is_planning_admin(request.user, self.required_permission))
        try:
            entity = Node.objects.get(pk=p['entity_id'])
            self._reach(entity)
            view = TargetService.get_person_view(
                period=TargetPeriod.objects.get(pk=p['period_id']),
                kpi=KPIDefinition.objects.get(pk=p['kpi_id']),
                entity=entity,
                channel=_opt(Channel, p.get('channel_id')),
                sku_group=_opt(SKUGroup, p.get('sku_group_id')),
                live_only=not include_draft,
            )
        except (KeyError, TargetPeriod.DoesNotExist, KPIDefinition.DoesNotExist, Node.DoesNotExist):
            raise BusinessError('period_id, kpi_id and entity_id are required and must exist.')
        return Response(view)

    @extend_schema(tags=['Targets'], summary='Bulk import allocations from CSV (async)',
                   request=AllocationBulkImportSerializer, responses={202: BulkJobSerializer})
    @action(detail=False, methods=['post'])
    def bulk(self, request):
        ser = AllocationBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uploaded = ser.validated_data.get('file')
        raw = uploaded.read().decode('utf-8') if uploaded else ser.validated_data.get('data', '')
        from apps.targets.tasks import import_allocations_task
        job = JobService.create(BulkJob.JobType.TARGET_IMPORT, request.user,
                                total_rows=count_rows(raw, 'csv'), request_id=getattr(request, 'request_id', ''))
        job = run_or_dispatch(import_allocations_task, job, raw, request.user.pk)
        return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


def _plan_admin_or_403(request, permission):
    if not is_planning_admin(request.user, permission):
        raise BusinessError('Plan administration is done by plan administrators.')


@extend_schema_view(
    list=extend_schema(tags=['Target Plans'], summary='List target plans (with progress rollup)'),
    retrieve=extend_schema(tags=['Target Plans'], summary='Retrieve plan'),
    create=extend_schema(tags=['Target Plans'], summary='Create a plan (with its KPI configuration)',
                         request=TargetPlanCreateSerializer),
    destroy=extend_schema(tags=['Target Plans'], summary='Deactivate a draft plan'),
)
class TargetPlanViewSet(ModelViewSet):
    serializer_class = TargetPlanSerializer
    required_permission = PERM
    # The plan aggregate is the review cascade's shared object — reviewers must open it.
    # Territory data inside is scoped per endpoint (grid masking, task ownership), and
    # every mutation is plan-admin-gated.
    permission_classes = [LevelRBACPermission]
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = (
            TargetPlan.objects.filter(is_active=True)
            .select_related('period', 'root_geography', 'channel')
            .prefetch_related('plan_kpis__kpi', 'plan_kpis__recipe')
        )
        params = self.request.query_params
        if s := params.get('status'):
            qs = qs.filter(status=s)
        if p := params.get('period'):
            qs = qs.filter(period_id=p)
        return qs.order_by('-created_at')

    def create(self, request, *args, **kwargs):
        _plan_admin_or_403(request, self.required_permission)
        ser = TargetPlanCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = dict(ser.validated_data)
        kpis = d.pop('kpis')
        plan = PlanService.create_plan(d, kpis=kpis, actor=request.user)
        return Response(TargetPlanSerializer(plan).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        _plan_admin_or_403(self.request, self.required_permission)
        if instance.status != TargetPlan.DRAFT:
            raise BusinessError('Only a draft plan can be deactivated.')
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    @extend_schema(tags=['Target Plans'], summary='Move the plan through its lifecycle',
                   request=PlanTransitionSerializer, responses={200: TargetPlanSerializer})
    @action(detail=True, methods=['post'])
    def transition(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = PlanTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = PlanService.transition_plan(
            self.get_object(), ser.validated_data['status'], actor=request.user,
            force_over_budget=ser.validated_data['force_over_budget'])
        return Response(TargetPlanSerializer(plan).data)

    @extend_schema(tags=['Target Plans'], summary='Set a KPI top number (Stage 2)',
                   request=SetPlanTopSerializer, responses={200: TargetPlanSerializer})
    @action(detail=True, methods=['post'], url_path='set-top')
    def set_top(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = SetPlanTopSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = self.get_object()
        PlanService.set_top_number(
            plan, KPIDefinition.objects.get(pk=ser.validated_data['kpi_id']),
            ser.validated_data['value'], actor=request.user)
        return Response(TargetPlanSerializer(plan).data)

    @extend_schema(tags=['Target Plans'], summary='Start a stage run (async → BulkJob)',
                   request=StartRunSerializer, responses={202: PlanRunSerializer})
    @action(detail=True, methods=['post'])
    def runs(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = StartRunSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        run = PlanService.start_run(self.get_object(), ser.validated_data['kind'], actor=request.user)
        return Response(PlanRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(tags=['Target Plans'], summary='Realignment re-split under a changed subtree (async)',
                   request=RealignSerializer, responses={202: PlanRunSerializer})
    @action(detail=True, methods=['post'])
    def realign(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = RealignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        scope = GeographyNode.objects.get(pk=ser.validated_data['scope_node_id'])
        run = PlanService.start_run(self.get_object(), PlanRun.REALIGN, actor=request.user,
                                    scope_node=scope)
        return Response(PlanRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(tags=['Target Plans'], summary='Cost of plan: payout simulation vs budget',
                   responses={200: OpenApiResponse(description='{ scenarios, per_scheme, budget, … }')})
    @action(detail=True, methods=['get'], url_path='cost-preview')
    def cost_preview(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        return Response(PlanService.cost_preview(self.get_object()))

    @extend_schema(tags=['Target Plans'], summary='Gap board: cascade progress + top-down vs bottom-up',
                   responses={200: OpenApiResponse(description='{ by_level, kpis, top_movers, … }')})
    @action(detail=True, methods=['get'], url_path='gap-board')
    def gap_board(self, request, pk=None):
        return Response(ReviewService.gap_board(self.get_object()))

    @extend_schema(
        tags=['Target Plans'], summary='Planning grid: ONE level of children (lazy-expand)',
        parameters=[OpenApiParameter('kpi', required=True, type=int),
                    OpenApiParameter('parent', required=False, type=int),
                    OpenApiParameter('period', required=False, type=int),
                    OpenApiParameter('page', required=False, type=int),
                    OpenApiParameter('page_size', required=False, type=int)],
        responses={200: OpenApiResponse(description='{ parent, rows, page, total }')},
    )
    @action(detail=True, methods=['get'])
    def grid(self, request, pk=None):
        plan = self.get_object()
        p = request.query_params
        try:
            kpi = KPIDefinition.objects.get(pk=p['kpi'])
            parent = GeographyNode.objects.get(pk=p['parent']) if p.get('parent') else None
            period = TargetPeriod.objects.get(pk=p['period']) if p.get('period') else None
        except (KeyError, KPIDefinition.DoesNotExist, GeographyNode.DoesNotExist,
                TargetPeriod.DoesNotExist):
            raise BusinessError('kpi is required; kpi/parent/period must exist.')
        if parent is None:
            # Land a placed persona at THEIR subtree, not the plan root (which would
            # filter to zero visible rows for anyone below the root's direct children).
            parent = PlanService.default_grid_parent(plan, request.user)
        # Territory RBAC: a scoped user only sees children inside the territories they own.
        children_qs = scope_transactions_by_territory(
            GeographyNode.objects.filter(is_active=True), request.user,
            self.required_permission, field='id')
        # The parent row's numbers span ALL children — mask them when the parent itself
        # is outside the requester's territories (its total would leak sibling data).
        mask_parent = not children_qs.filter(pk=parent.id).exists()
        return Response(PlanService.grid(
            plan, kpi, parent=parent, period=period, children_qs=children_qs,
            page=int(p.get('page', 1)), page_size=int(p.get('page_size', 100)),
            mask_parent=mask_parent))

    @extend_schema(tags=['Target Plans'],
                   summary='Explain a territory\'s numbers from the latest committed run',
                   parameters=[OpenApiParameter('node', required=True, type=int)],
                   responses={200: OpenApiResponse(description='{ run_id, kind, rows }')})
    @action(detail=True, methods=['get'])
    def explain(self, request, pk=None):
        plan = self.get_object()
        node = request.query_params.get('node')
        if not node:
            raise BusinessError('The node query parameter is required.')
        scoped = scope_transactions_by_territory(
            GeographyNode.objects.filter(is_active=True), request.user,
            self.required_permission, field='id')
        if not scoped.filter(pk=node).exists():
            raise BusinessError('That territory is outside your area.')
        run = plan.runs.filter(
            status=PlanRun.COMMITTED, allocations__geography_node_id=node,
        ).order_by('-committed_at').first()
        if run is None:
            return Response({'run_id': None, 'kind': None, 'rows': []})
        return Response({'run_id': run.id, 'kind': run.kind,
                         'rows': PlanService.explain(run, int(node))})

    @extend_schema(tags=['Target Plans'], summary='Force-close the open review tasks (audited)',
                   request=ForceCloseSerializer)
    @action(detail=True, methods=['post'], url_path='force-close')
    def force_close(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        ser = ForceCloseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        closed = ReviewService.force_close(self.get_object(), actor=request.user,
                                           reason=ser.validated_data['reason'])
        return Response({'force_closed': closed})

    @extend_schema(tags=['Target Plans'], summary='Nudge owners with open review tasks', request=None)
    @action(detail=True, methods=['post'])
    def nudge(self, request, pk=None):
        _plan_admin_or_403(request, self.required_permission)
        return Response({'nudged': ReviewService.nudge(self.get_object(), actor=request.user)})


@extend_schema_view(
    list=extend_schema(tags=['Target Plans'], summary='List plan runs',
                       parameters=[OpenApiParameter('plan', required=False, type=int),
                                   OpenApiParameter('kind', required=False, type=str),
                                   OpenApiParameter('status', required=False, type=str)]),
    retrieve=extend_schema(tags=['Target Plans'], summary='Retrieve a run'),
)
class PlanRunViewSet(ReadOnlyModelViewSet):
    serializer_class = PlanRunSerializer
    required_permission = PERM
    permission_classes = [LevelRBACPermission]
    pagination_class = StandardPagination

    def get_queryset(self):
        if not is_planning_admin(self.request.user, self.required_permission):
            return PlanRun.objects.none()  # run internals (config, staging) are plan-admin data
        qs = PlanRun.objects.filter(is_active=True).select_related('plan', 'scope_node')
        params = self.request.query_params
        for field in ('plan', 'kind', 'status'):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        return qs.order_by('-created_at')

    @extend_schema(tags=['Target Plans'], summary='Preview: staged vs committed (+override collisions)',
                   responses={200: OpenApiResponse(description='{ new, changed, override_collisions, … }')})
    @action(detail=True, methods=['get'])
    def preview(self, request, pk=None):
        return Response(PlanService.preview_run(self.get_object()))

    @extend_schema(tags=['Target Plans'],
                   summary='Every staged row for a run (paginated) — the full generated set, '
                           'not just what changed',
                   responses={200: OpenApiResponse(description='paginated { geography_node, level, '
                                                              'kpi, sku_group, value, base_value }')})
    @action(detail=True, methods=['get'], url_path='staged-rows')
    def staged_rows(self, request, pk=None):
        run = self.get_object()
        qs = run.allocations.select_related('geography_node', 'kpi', 'sku_group').order_by(
            'geography_node__depth', 'geography_node__path', 'kpi__code', 'sku_group__code')
        page = self.paginate_queryset(qs)
        rows = [{
            'geography_node': r.geography_node.name,
            'geography_node_code': r.geography_node.code,
            'level': r.geography_node.level,
            'kpi': r.kpi.code,
            'sku_group': r.sku_group.code if r.sku_group_id else None,
            'value': str(r.value),
            'base_value': str(r.base_value) if r.base_value is not None else None,
        } for r in (page if page is not None else qs)]
        return (self.get_paginated_response(rows) if page is not None
                else Response({'results': rows, 'count': len(rows)}))

    @extend_schema(tags=['Target Plans'], summary='Commit staging → live targets (atomic, snapshotted)',
                   request=CommitRunSerializer)
    @action(detail=True, methods=['post'])
    def commit(self, request, pk=None):
        ser = CommitRunSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stats = PlanService.commit_run(self.get_object(), actor=request.user,
                                       override_strategy=ser.validated_data['override_strategy'])
        return Response(stats)

    @extend_schema(tags=['Target Plans'], summary='Discard a staged run', request=None)
    @action(detail=True, methods=['post'])
    def discard(self, request, pk=None):
        run = PlanService.discard_run(self.get_object(), actor=request.user)
        return Response(PlanRunSerializer(run).data)

    @extend_schema(tags=['Target Plans'], summary='Explain: why did this node get these numbers (RFP)',
                   parameters=[OpenApiParameter('node', required=True, type=int)],
                   responses={200: OpenApiResponse(description='per-KPI weight breakdown rows')})
    @action(detail=True, methods=['get'])
    def explain(self, request, pk=None):
        node = request.query_params.get('node')
        if not node:
            raise BusinessError('The node query parameter is required.')
        return Response(PlanService.explain(self.get_object(), int(node)))


@extend_schema_view(
    list=extend_schema(tags=['Target Plans'], summary='List review tasks (mine, unless plan admin)',
                       parameters=[OpenApiParameter('plan', required=False, type=int),
                                   OpenApiParameter('status', required=False, type=str)]),
    retrieve=extend_schema(tags=['Target Plans'], summary='Retrieve a review task'),
)
class ReviewTaskViewSet(ReadOnlyModelViewSet):
    serializer_class = ReviewTaskSerializer
    required_permission = PERM
    # Object reach = the owner-scoped queryset below (a foreign task 404s) plus the
    # explicit _guard_owner on every response action.
    permission_classes = [LevelRBACPermission]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ReviewTask.objects.filter(is_active=True).select_related(
            'plan', 'node', 'owner_node', 'submitted_by')
        if not is_planning_admin(self.request.user, self.required_permission):
            home = getattr(self.request.user, 'entity', None)
            qs = qs.filter(owner_node=home) if home is not None else qs.none()
        params = self.request.query_params
        for field in ('plan', 'status'):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        return qs.order_by('plan', 'node__path')

    def _guard_owner(self, task):
        if is_planning_admin(self.request.user, self.required_permission):
            return
        home = getattr(self.request.user, 'entity', None)
        if home is None or task.owner_node_id != home.pk:
            raise BusinessError('This review task belongs to another territory owner.')

    @extend_schema(tags=['Target Plans'], summary='Accept the top-down numbers as-is',
                   request=ReviewAcceptSerializer, responses={200: ReviewTaskSerializer})
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        task = self.get_object()
        self._guard_owner(task)
        ser = ReviewAcceptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        task = ReviewService.accept(task, actor=request.user, notes=ser.validated_data['notes'])
        return Response(ReviewTaskSerializer(task).data)

    @extend_schema(tags=['Target Plans'], summary='Adjust a number inside this territory (governed)',
                   request=ReviewAdjustSerializer, responses={200: ReviewTaskSerializer})
    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        task = self.get_object()
        self._guard_owner(task)
        ser = ReviewAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        allocation = TargetAllocation.objects.get(pk=d['allocation_id'])
        task = ReviewService.adjust(task, allocation, d['override_value'], reason=d['reason'],
                                    actor=request.user, rebalance=d['rebalance'])
        return Response(ReviewTaskSerializer(task).data)

    @extend_schema(tags=['Target Plans'],
                   summary='Adjust without naming a task — resolves the caller\'s task for the territory',
                   request=ReviewAdjustMineSerializer, responses={200: ReviewTaskSerializer})
    @action(detail=False, methods=['post'], url_path='adjust')
    def adjust_mine(self, request):
        home = getattr(request.user, 'entity', None)
        if home is None:
            raise BusinessError('Only a placed territory owner can respond to a review.')
        ser = ReviewAdjustMineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        plan = TargetPlan.objects.get(pk=d['plan_id'])
        allocation = TargetAllocation.objects.select_related('geography_node').get(pk=d['allocation_id'])
        task = ReviewService.open_task_for(plan, home, allocation)
        task = ReviewService.adjust(task, allocation, d['override_value'], reason=d['reason'],
                                    actor=request.user, rebalance=d['rebalance'])
        return Response(ReviewTaskSerializer(task).data)


class _VersionedConfigViewSet(ModelViewSet):
    """Shared CRUD for the versioned config models (recipes + policies): every update creates
    a new version, prior versions are kept (mirrors the NodeType pattern)."""
    required_permission = PERM
    permission_classes = [LevelRBACPermission]  # shared config: read by all, writes plan-admin-gated
    model = None
    audit_label = ''

    def get_queryset(self):
        return self.model.objects.filter(is_current=True, is_active=True).order_by('code')

    def perform_create(self, serializer):
        _plan_admin_or_403(self.request, self.required_permission)
        obj = serializer.save(effective_from=date.today())
        AuditService.log('create', self.audit_label, obj.id, self.request.user, {'code': obj.code})

    def perform_update(self, serializer):
        _plan_admin_or_403(self.request, self.required_permission)
        instance = serializer.instance
        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)
        instance.create_new_version()
        AuditService.log('update', self.audit_label, instance.id, self.request.user,
                         {'code': instance.code, 'new_version': instance.version})

    def perform_destroy(self, instance):
        _plan_admin_or_403(self.request, self.required_permission)
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    @extend_schema(responses=None)
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        obj = self.get_object()
        qs = self.model.objects.filter(code=obj.code).order_by('version')
        return Response(self.get_serializer(qs, many=True).data)


@extend_schema_view(
    list=extend_schema(tags=['Targets'], summary='List allocation recipes'),
    create=extend_schema(tags=['Targets'], summary='Create allocation recipe'),
    update=extend_schema(tags=['Targets'], summary='Update recipe (new version)'),
    versions=extend_schema(tags=['Targets'], summary='Recipe version history'),
)
class AllocationRecipeViewSet(_VersionedConfigViewSet):
    serializer_class = AllocationRecipeSerializer
    model = AllocationRecipe
    audit_label = 'targets.AllocationRecipe'


@extend_schema_view(
    list=extend_schema(tags=['Targets'], summary='List revision policies (change caps)'),
    create=extend_schema(tags=['Targets'], summary='Create revision policy'),
    update=extend_schema(tags=['Targets'], summary='Update policy (new version)'),
    versions=extend_schema(tags=['Targets'], summary='Policy version history'),
)
class RevisionPolicyViewSet(_VersionedConfigViewSet):
    serializer_class = RevisionPolicySerializer
    model = RevisionPolicy
    audit_label = 'targets.RevisionPolicy'


_REVISION_PARAMS = [
    OpenApiParameter('allocation', required=False, type=int),
    OpenApiParameter('status', required=False, type=str),
    OpenApiParameter('source', required=False, type=str),
    OpenApiParameter('target_period', required=False, type=int),
    OpenApiParameter('geography_node', required=False, type=int),
]


@extend_schema_view(
    list=extend_schema(tags=['Targets'], summary='List target revisions (audit query)',
                       parameters=_REVISION_PARAMS),
    retrieve=extend_schema(tags=['Targets'], summary='Retrieve a revision'),
)
class TargetRevisionViewSet(ReadOnlyModelViewSet):
    serializer_class = TargetRevisionSerializer
    required_permission = PERM
    permission_classes = [LevelRBACPermission]  # read-only; queryset is territory-scoped
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = TargetRevision.objects.select_related(
            'allocation', 'allocation__geography_node', 'requested_by', 'approved_by').filter(is_active=True)
        p = self.request.query_params
        for field in ('allocation', 'status', 'source'):
            if value := p.get(field):
                qs = qs.filter(**{field: value})
        if period := p.get('target_period'):
            qs = qs.filter(allocation__target_period_id=period)
        if node := p.get('geography_node'):
            qs = qs.filter(allocation__geography_node_id=node)
        # Revisions inherit the allocation's territory scope.
        qs = scope_transactions_by_territory(
            qs, self.request.user, self.required_permission, field='allocation__geography_node_id')
        return qs.order_by('-created_at')

    @extend_schema(tags=['Targets'], summary='Export revisions as CSV', parameters=_REVISION_PARAMS,
                   responses={200: OpenApiResponse(description='text/csv')})
    @action(detail=False, methods=['get'])
    def export(self, request):
        import csv
        import io
        rows = self.filter_queryset(self.get_queryset())
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['revision_id', 'allocation_id', 'geography_node', 'period', 'kpi', 'old_value',
                         'new_value', 'delta', 'delta_pct', 'band', 'status', 'source',
                         'reason', 'requested_by', 'approved_by', 'approved_at', 'created_at'])
        for r in rows.iterator():
            a = r.allocation
            writer.writerow([
                r.id, a.id, getattr(a.geography_node, 'code', ''), a.target_period_id, a.kpi_id,
                r.old_value, r.new_value, r.delta, r.delta_pct, r.band, r.status, r.source,
                r.reason, getattr(r.requested_by, 'email', '') or '', getattr(r.approved_by, 'email', '') or '',
                r.approved_at.isoformat() if r.approved_at else '', r.created_at.isoformat(),
            ])
        resp = HttpResponse(buf.getvalue(), content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="target_revisions.csv"'
        return resp
