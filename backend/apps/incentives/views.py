from django.db.models import Sum
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet, ReadOnlyModelViewSet
from rest_framework import mixins

from apps.audit.services import AccessService
from apps.core.pagination import StandardPagination
from apps.core.permissions import _rank, highest_level
from apps.core.scoping import NodeScopedQuerysetMixin, is_planning_admin
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.targets.models import TargetPeriod

from .models import (
    ExceptionCategory, IncentiveScheme, Payout, PayoutCycle, PayoutException, PayoutRun, VariablePay,
)
from .serializers import (
    AdjustRequestSerializer,
    CycleCreateSerializer,
    CycleFinalizeSerializer,
    DisburseSerializer,
    ExceptionCategorySerializer,
    HoldSerializer,
    MarkPaidSerializer,
    PayoutCycleSerializer,
    PayoutDetailSerializer,
    PayoutExceptionSerializer,
    PayoutListSerializer,
    PayoutRunSerializer,
    PayoutSummarySerializer,
    RejectSerializer,
    SchemeDetailSerializer,
    SchemeListSerializer,
    SchemeValidateResponseSerializer,
    SchemeWriteSerializer,
    VariablePayBulkSerializer,
    VariablePaySerializer,
    VariablePayUpsertSerializer,
)
from .services import (
    ExceptionService, PayoutCycleService, PayoutService, SchemeService, VariablePayService,
)

_APPROVE_PERM = 'payout_approve'


def _require_planning_admin(request, required: str, message: str) -> None:
    if not is_planning_admin(request.user, required):
        raise PermissionDenied(message)


def _require_resource(request, resource: str, message: str) -> None:
    if not request.user.is_superuser and _rank(highest_level(request.user, resource)) <= 0:
        raise PermissionDenied(message)


# ── schemes ────────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List incentive schemes (current versions)',
                       parameters=[
                           OpenApiParameter('entity_type', description='NodeType code', type=str),
                           OpenApiParameter('include_inactive', type=bool),
                       ]),
    retrieve=extend_schema(tags=['Incentives'], summary='Retrieve a scheme with KPIs and tiers'),
    create=extend_schema(tags=['Incentives'], summary='Create an incentive scheme',
                         request=SchemeWriteSerializer, responses={201: SchemeDetailSerializer}),
    update=extend_schema(tags=['Incentives'], summary='Update a scheme (creates a new version)',
                         request=SchemeWriteSerializer, responses={200: SchemeDetailSerializer}),
    destroy=extend_schema(tags=['Incentives'], summary='Deactivate a scheme'),
)
class SchemeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                    mixins.DestroyModelMixin, GenericViewSet):
    required_permission = 'scheme_management'
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action in ('create', 'update'):
            return SchemeWriteSerializer
        return SchemeListSerializer if self.action == 'list' else SchemeDetailSerializer

    def get_queryset(self):
        qs = IncentiveScheme.objects.select_related(
            'target_entity_type', 'channel',
        ).prefetch_related('gates__kpi')
        if self.action in ('retrieve', 'versions'):
            return qs
        qs = qs.filter(is_current=True)
        p = self.request.query_params
        if p.get('include_inactive') not in ('1', 'true'):
            qs = qs.filter(is_active=True)
        if etype := p.get('entity_type'):
            qs = qs.filter(target_entity_type__code=etype)
        return qs.order_by('code')

    def create(self, request):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can create schemes.')
        ser = SchemeWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        scheme = SchemeService.create(dict(ser.validated_data), actor=request.user)
        return Response(SchemeDetailSerializer(scheme).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can update schemes.')
        scheme = get_object_or_404(IncentiveScheme, pk=pk, is_current=True)
        ser = SchemeWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        scheme = SchemeService.update(scheme, dict(ser.validated_data), actor=request.user)
        return Response(SchemeDetailSerializer(scheme).data)

    def perform_destroy(self, instance):
        _require_planning_admin(self.request, self.required_permission,
                                'Only plan-wide operators can deactivate schemes.')
        SchemeService.deactivate(instance, actor=self.request.user)

    @extend_schema(tags=['Incentives'], operation_id='scheme_versions',
                   summary='Version history for a scheme code',
                   responses={200: SchemeListSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        scheme = get_object_or_404(IncentiveScheme, pk=pk)
        qs = IncentiveScheme.objects.filter(code=scheme.code).select_related(
            'target_entity_type', 'channel',
        ).order_by('-version')
        return Response(SchemeListSerializer(qs, many=True).data)

    @extend_schema(tags=['Incentives'], operation_id='scheme_validate',
                   summary='Dry-run validation of a scheme payload (wizard)',
                   request=SchemeWriteSerializer,
                   responses={200: SchemeValidateResponseSerializer})
    @action(detail=False, methods=['post'])
    def validate(self, request):
        ser = SchemeWriteSerializer(data=request.data)
        if not ser.is_valid():
            flat = [f'{field}: {errs[0]}' for field, errs in ser.errors.items()]
            return Response({'valid': False, 'errors': flat})
        errors = SchemeService.validate_config(dict(ser.validated_data))
        return Response({'valid': not errors, 'errors': errors})

    @extend_schema(tags=['Incentives'], operation_id='sip_structures',
                   summary='SIP structure — schemes grouped by entity type × channel',
                   description='Each group lists its components (monthly / annual schemes) '
                               'with vp_basis_pct; is_complete = the shares sum to 100.',
                   responses={200: OpenApiResponse(description='[{entity_type, channel, components, total_vp_basis_pct, is_complete}]')})
    @action(detail=False, methods=['get'], url_path='sip-structures')
    def sip_structures(self, request):
        return Response(SchemeService.sip_structure())


# ── variable pay ───────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List variable pay (subtree-scoped)',
                       parameters=[
                           OpenApiParameter('period', description='TargetPeriod id', type=int),
                           OpenApiParameter('entity', description='Node id', type=int),
                       ]),
)
class VariablePayViewSet(NodeScopedQuerysetMixin, mixins.ListModelMixin, GenericViewSet):
    required_permission = 'scheme_management'
    scope_path_field = 'entity__path'
    serializer_class = VariablePaySerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = VariablePay.objects.filter(is_active=True).select_related(
            'entity', 'target_period',
        )
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if entity := p.get('entity'):
            qs = qs.filter(entity_id=entity)
        return self.scope_queryset(qs).order_by('entity__code')

    @extend_schema(tags=['Incentives'], operation_id='variable_pay_upsert',
                   summary='Create or update one entity-period variable pay',
                   request=VariablePayUpsertSerializer,
                   responses={200: VariablePaySerializer})
    def create(self, request):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can set variable pay.')
        ser = VariablePayUpsertSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        vp = VariablePayService.upsert(
            v['entity'], v['target_period'], v['amount'],
            eligible_working_days=v.get('eligible_working_days'), actor=request.user,
        )
        return Response(VariablePaySerializer(vp).data)

    @extend_schema(tags=['Incentives'], operation_id='variable_pay_bulk',
                   summary='Bulk import variable pay rows (all-or-nothing)',
                   request=VariablePayBulkSerializer)
    @action(detail=False, methods=['post'])
    def bulk(self, request):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can import variable pay.')
        ser = VariablePayBulkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = VariablePayService.bulk_import(
            ser.validated_data['rows'], ser.validated_data['target_period'],
            actor=request.user,
        )
        return Response(result)


# ── payout runs ────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List payout runs',
                       parameters=[
                           OpenApiParameter('period', type=int),
                           OpenApiParameter('scheme', type=int),
                           OpenApiParameter('status', type=str),
                       ]),
    retrieve=extend_schema(tags=['Incentives'], summary='Retrieve a payout run'),
)
class PayoutRunViewSet(ReadOnlyModelViewSet):
    """Runs have no entity anchor — any final_payout level may read them; the payout
    rows inside stay subtree-scoped. Lifecycle actions are explicitly gated below
    (the runs are fetched directly so RBAC object checks don't apply)."""

    required_permission = 'final_payout'
    serializer_class = PayoutRunSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = PayoutRun.objects.select_related(
            'scheme', 'target_period', 'submitted_by', 'approved_by',
        )
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if scheme := p.get('scheme'):
            qs = qs.filter(scheme_id=scheme)
        if status_ := p.get('status'):
            qs = qs.filter(status=status_)
        return qs

    def _run(self, pk) -> PayoutRun:
        return get_object_or_404(PayoutRun.objects.select_related('scheme', 'target_period'), pk=pk)

    # NOTE: there is deliberately no standalone compute endpoint. Final runs are
    # computed by the payout cycle (finalize → compute, off frozen achievements);
    # estimates come from the nightly beat. A standalone final compute would bypass
    # readiness checks and the achievement freeze.

    @extend_schema(tags=['Incentives'], operation_id='payout_run_adjust',
                   summary='Raise an adjustment run (delta vs a paid, closed-cycle run)',
                   request=AdjustRequestSerializer, responses={202: PayoutRunSerializer})
    @action(detail=False, methods=['post'])
    def adjust(self, request):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can raise adjustments.')
        ser = AdjustRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reference_run = get_object_or_404(
            PayoutRun.objects.select_related('scheme', 'target_period', 'cycle'),
            pk=ser.validated_data['reference_run_id'],
        )
        cycle = get_object_or_404(PayoutCycle, pk=ser.validated_data['cycle_id'])
        result = PayoutCycleService.create_adjustment(reference_run, cycle, actor=request.user)
        run = get_object_or_404(PayoutRun, pk=result['run_id'])
        data = PayoutRunSerializer(run).data
        data['net_delta'] = result['net_delta']
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(tags=['Incentives'], operation_id='payout_run_submit',
                   summary='Submit a computed run for review (maker)',
                   request=None, responses={200: PayoutRunSerializer})
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can submit runs for review.')
        run = PayoutService.submit_for_review(self._run(pk), request.user)
        return Response(PayoutRunSerializer(run).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_run_approve',
                   summary='Approve a run under review (checker; not the submitter)',
                   request=None, responses={200: PayoutRunSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to approve payout runs.')
        run = PayoutService.approve(self._run(pk), request.user)
        return Response(PayoutRunSerializer(run).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_run_reject',
                   summary='Reject a run under review (back to computed)',
                   request=RejectSerializer, responses={200: PayoutRunSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to reject payout runs.')
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        run = PayoutService.reject(self._run(pk), request.user, ser.validated_data['reason'])
        return Response(PayoutRunSerializer(run).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_run_mark_paid',
                   summary='Mark an approved run as paid',
                   request=MarkPaidSerializer, responses={200: PayoutRunSerializer})
    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to mark runs as paid.')
        ser = MarkPaidSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        run = PayoutService.mark_paid(self._run(pk), request.user,
                                      ser.validated_data['payment_ref'])
        return Response(PayoutRunSerializer(run).data)


# ── payouts ────────────────────────────────────────────────────────────────────

_PAYOUT_PARAMS = [
    OpenApiParameter('period', description='TargetPeriod id', type=int),
    OpenApiParameter('scheme', description='Scheme id', type=int),
    OpenApiParameter('run', description='PayoutRun id', type=int),
    OpenApiParameter('run_status', description='Run status', type=str),
    OpenApiParameter('entity_type', description='NodeType code', type=str),
]


@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List payouts (subtree-scoped)',
                       parameters=_PAYOUT_PARAMS),
    retrieve=extend_schema(tags=['Incentives'],
                           summary='Payout breakdown with line items and exception'),
)
class PayoutViewSet(NodeScopedQuerysetMixin, ReadOnlyModelViewSet):
    required_permission = 'final_payout'
    scope_path_field = 'entity__path'
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return PayoutListSerializer if self.action == 'list' else PayoutDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        # Disclosure trail: log when a manager/finance views someone else's payout.
        own_entity_id = getattr(getattr(request.user, 'entity', None), 'pk', None)
        if obj.entity_id != own_entity_id:
            AccessService.record(request.user, 'payout',
                                 subject_entity_id=obj.entity_id, object_id=obj.pk)
        return Response(self.get_serializer(obj).data)

    def get_queryset(self):
        qs = Payout.objects.select_related(
            'run', 'scheme', 'target_period', 'entity', 'entity__entity_type', 'exception',
        )
        if self.action == 'retrieve':
            qs = qs.prefetch_related('line_items__scheme_kpi__kpi')
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if scheme := p.get('scheme'):
            qs = qs.filter(scheme_id=scheme)
        if run := p.get('run'):
            qs = qs.filter(run_id=run)
        if run_status := p.get('run_status'):
            qs = qs.filter(run__status=run_status)
        else:
            qs = qs.exclude(run__status__in=[PayoutRun.SUPERSEDED, PayoutRun.FAILED])
        if etype := p.get('entity_type'):
            qs = qs.filter(entity__entity_type__code=etype)
        return self.scope_queryset(qs)

    @extend_schema(tags=['Incentives'], operation_id='payout_summary',
                   summary='Aggregates over the (scoped) payout list',
                   parameters=_PAYOUT_PARAMS, responses={200: PayoutSummarySerializer})
    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self.get_queryset()
        agg = qs.aggregate(total=Sum('total_payout'))
        return Response({
            'total_payout': str(agg['total'] or '0.00'),
            'entities': qs.values('entity_id').distinct().count(),
            'capped_count': qs.filter(capped=True).count(),
            'gatekeeper_failed_count': qs.filter(gatekeeper_status=Payout.GK_FAILED).count(),
            'exception_count': qs.filter(exception__isnull=False).count(),
        })

    def _payout(self, pk) -> Payout:
        return get_object_or_404(Payout.objects.select_related('run', 'run__cycle', 'entity'), pk=pk)

    @extend_schema(tags=['Incentives'], operation_id='payout_hold',
                   summary='Hold one payee during cycle review (excluded from register)',
                   request=HoldSerializer, responses={200: PayoutDetailSerializer})
    @action(detail=True, methods=['post'])
    def hold(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can hold payouts.')
        ser = HoldSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payout = PayoutCycleService.hold_payout(
            self._payout(pk), actor=request.user, reason=ser.validated_data['reason'],
        )
        return Response(PayoutDetailSerializer(payout).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_release',
                   summary='Release a held payout before the register is cut',
                   request=None, responses={200: PayoutDetailSerializer})
    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can release payouts.')
        payout = PayoutCycleService.release_payout(self._payout(pk), actor=request.user)
        return Response(PayoutDetailSerializer(payout).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_statement',
                   summary='Per-payee statement (self-explaining payout record)',
                   responses={200: OpenApiResponse(description='Statement payload')})
    @action(detail=True, methods=['get'])
    def statement(self, request, pk=None):
        payout = self._payout(pk)
        own_entity_id = getattr(getattr(request.user, 'entity', None), 'pk', None)
        if payout.entity_id != own_entity_id:
            AccessService.record(request.user, 'payout',
                                 subject_entity_id=payout.entity_id, object_id=payout.pk)
        return Response(PayoutService.statement(int(pk), request.user))


# ── exceptions ─────────────
@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List configurable exception categories'),
    retrieve=extend_schema(tags=['Incentives'], summary='Retrieve an exception category'),
)
class ExceptionCategoryViewSet(ReadOnlyModelViewSet):
    """The FMCG reason catalog — drives the raise form's category dropdown + default treatments."""
    required_permission = 'exception_management'
    serializer_class = ExceptionCategorySerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        from django.db.models import Q
        qs = ExceptionCategory.objects.filter(is_current=True, is_active=True)
        # Channel-scoped categories: ?channel= keeps channel-null (all-channel) rows.
        if channel := self.request.query_params.get('channel'):
            qs = qs.filter(Q(channel__isnull=True) | Q(channel__code=channel))
        return qs.select_related('channel').order_by('name')


@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List payout exceptions (subtree-scoped)',
                       parameters=[
                           OpenApiParameter('period', type=int),
                           OpenApiParameter('status', type=str),
                           OpenApiParameter('entity', type=int),
                       ]),
    retrieve=extend_schema(tags=['Incentives'], summary='Retrieve a payout exception'),
    create=extend_schema(tags=['Incentives'], summary='Raise a payout exception (pending)'),
    partial_update=extend_schema(tags=['Incentives'], summary='Edit a pending exception'),
    destroy=extend_schema(tags=['Incentives'], summary='Withdraw a pending exception'),
)
class PayoutExceptionViewSet(NodeScopedQuerysetMixin, ModelViewSet):
    required_permission = 'exception_management'
    scope_path_field = 'entity__path'
    serializer_class = PayoutExceptionSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = PayoutException.objects.filter(is_active=True).select_related(
            'entity', 'target_period', 'scheme', 'requested_by',
        )
        p = self.request.query_params
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        if status_ := p.get('status'):
            qs = qs.filter(status=status_)
        if entity := p.get('entity'):
            qs = qs.filter(entity_id=entity)
        return self.scope_queryset(qs)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        exc = ExceptionService.create(dict(ser.validated_data), actor=request.user)
        return Response(PayoutExceptionSerializer(exc).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        ExceptionService.update_pending(
            serializer.instance, dict(serializer.validated_data), actor=self.request.user,
        )

    def perform_destroy(self, instance):
        if instance.status != PayoutException.PENDING:
            from apps.core.exceptions import BusinessError
            raise BusinessError('Only pending exceptions can be withdrawn.')
        ExceptionService.withdraw(instance, actor=self.request.user)

    @extend_schema(tags=['Incentives'], operation_id='payout_exception_approve',
                   summary='Approve a pending exception (not the requester)',
                   request=None, responses={200: PayoutExceptionSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        _require_resource(request, 'exception_approve',
                          'You do not have permission to approve exceptions.')
        exc = get_object_or_404(PayoutException, pk=pk, is_active=True)
        exc = ExceptionService.approve(exc, request.user)
        return Response(PayoutExceptionSerializer(exc).data)

    @extend_schema(tags=['Incentives'], operation_id='payout_exception_reject',
                   summary='Reject a pending exception',
                   request=RejectSerializer, responses={200: PayoutExceptionSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        _require_resource(request, 'exception_approve',
                          'You do not have permission to reject exceptions.')
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        exc = get_object_or_404(PayoutException, pk=pk, is_active=True)
        exc = ExceptionService.reject(exc, request.user, ser.validated_data['reason'])
        return Response(PayoutExceptionSerializer(exc).data)


# ── payout cycles (month-close) ──────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Incentives'], summary='List payout cycles',
                       parameters=[OpenApiParameter('status', type=str),
                                   OpenApiParameter('period', type=int)]),
    retrieve=extend_schema(tags=['Incentives'], summary='Retrieve a payout cycle'),
)
class PayoutCycleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet):
    """The month-close workspace. Reads are open to any final_payout level (the cycle carries
    no entity anchor); the payout rows inside stay subtree-scoped. Mutating steps are gated:
    finalize/compute/submit/reject/disburse/close need plan-wide operator rights, approve
    needs payout_approve (and can't be the submitter)."""

    required_permission = 'final_payout'
    serializer_class = PayoutCycleSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = PayoutCycle.objects.select_related(
            'target_period', 'finalized_by', 'submitted_by', 'approved_by', 'disbursed_by',
        )
        p = self.request.query_params
        if status_ := p.get('status'):
            qs = qs.filter(status=status_)
        if period := p.get('period'):
            qs = qs.filter(target_period_id=period)
        return qs.order_by('-target_period__start_date')

    def _cycle(self, pk) -> PayoutCycle:
        return get_object_or_404(PayoutCycle.objects.select_related('target_period'), pk=pk)

    @extend_schema(tags=['Incentives'], operation_id='cycle_open',
                   summary='Open (or return) the cycle for a period',
                   request=CycleCreateSerializer, responses={201: PayoutCycleSerializer})
    def create(self, request):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can open a payout cycle.')
        ser = CycleCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        period = get_object_or_404(TargetPeriod, pk=ser.validated_data['period_id'])
        cycle = PayoutCycleService.open_cycle(period, actor=request.user)
        return Response(PayoutCycleSerializer(cycle).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=['Incentives'], operation_id='cycle_readiness',
                   summary='Recompute and return the readiness checklist',
                   responses={200: OpenApiResponse(description='Readiness snapshot')})
    @action(detail=True, methods=['get'])
    def readiness(self, request, pk=None):
        return Response(PayoutCycleService.readiness(self._cycle(pk)))

    @extend_schema(tags=['Incentives'], operation_id='cycle_finalize',
                   summary='Finalize: freeze the period achievements (async)',
                   request=CycleFinalizeSerializer, responses={202: BulkJobSerializer})
    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can finalize a cycle.')
        ser = CycleFinalizeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cycle = self._cycle(pk)
        override = ser.validated_data['override']
        # Give a clean synchronous 400 when readiness blocks and there's no override, rather
        # than surfacing it only through the async job.
        snapshot = PayoutCycleService.readiness(cycle)
        if not snapshot['is_ready'] and not override:
            from apps.core.exceptions import BusinessError
            red = [c['key'] for c in snapshot['checks'] if c['status'] == 'red']
            raise BusinessError('Readiness checks are not green: ' + ', '.join(red)
                                + '. Resolve them or finalize with an override.')
        job = JobService.create(BulkJob.JobType.CYCLE_FINALIZE, request.user,
                                request_id=getattr(request, 'request_id', ''))
        from apps.incentives.tasks import finalize_cycle_task
        job = run_or_dispatch(finalize_cycle_task, job, cycle.pk, request.user.pk,
                              override, ser.validated_data['override_reason'])
        data = BulkJobSerializer(job).data
        data['cycle_id'] = cycle.pk
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(tags=['Incentives'], operation_id='cycle_compute',
                   summary='Compute final runs for all active schemes (async)',
                   request=None, responses={202: BulkJobSerializer})
    @action(detail=True, methods=['post'])
    def compute(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can compute a cycle.')
        cycle = self._cycle(pk)
        if cycle.finalized_at is None:
            from apps.core.exceptions import BusinessError
            raise BusinessError('Finalize the cycle (freeze achievements) before computing.')
        job = JobService.create(BulkJob.JobType.CYCLE_COMPUTE, request.user,
                                request_id=getattr(request, 'request_id', ''))
        from apps.incentives.tasks import compute_cycle_task
        job = run_or_dispatch(compute_cycle_task, job, cycle.pk, request.user.pk)
        data = BulkJobSerializer(job).data
        data['cycle_id'] = cycle.pk
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(tags=['Incentives'], operation_id='cycle_review',
                   summary='Review board payload (stats, variance, distribution, movers)',
                   responses={200: OpenApiResponse(description='Review payload')})
    @action(detail=True, methods=['get'])
    def review(self, request, pk=None):
        return Response(PayoutCycleService.review(self._cycle(pk)))

    @extend_schema(tags=['Incentives'], operation_id='cycle_submit',
                   summary='Submit the reviewed cycle for approval (maker)',
                   request=None, responses={200: PayoutCycleSerializer})
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can submit a cycle.')
        cycle = PayoutCycleService.submit_cycle(self._cycle(pk), actor=request.user)
        return Response(PayoutCycleSerializer(cycle).data)

    @extend_schema(tags=['Incentives'], operation_id='cycle_approve',
                   summary='Approve the cycle (checker; not the submitter)',
                   request=None, responses={200: PayoutCycleSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to approve payout cycles.')
        cycle = PayoutCycleService.approve_cycle(self._cycle(pk), actor=request.user)
        return Response(PayoutCycleSerializer(cycle).data)

    @extend_schema(tags=['Incentives'], operation_id='cycle_reject',
                   summary='Send a submitted cycle back into review',
                   request=RejectSerializer, responses={200: PayoutCycleSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to reject payout cycles.')
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cycle = PayoutCycleService.reject_cycle(self._cycle(pk), actor=request.user,
                                                reason=ser.validated_data['reason'])
        return Response(PayoutCycleSerializer(cycle).data)

    @extend_schema(tags=['Incentives'], operation_id='cycle_disburse',
                   summary='Disburse the approved cycle (mark paid, record ref)',
                   request=DisburseSerializer, responses={200: PayoutCycleSerializer})
    @action(detail=True, methods=['post'])
    def disburse(self, request, pk=None):
        _require_resource(request, _APPROVE_PERM,
                          'You do not have permission to disburse payout cycles.')
        ser = DisburseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cycle = PayoutCycleService.disburse_cycle(
            self._cycle(pk), actor=request.user,
            payment_ref=ser.validated_data['payment_ref'],
            register_ref=ser.validated_data['register_ref'],
        )
        return Response(PayoutCycleSerializer(cycle).data)

    @extend_schema(tags=['Incentives'], operation_id='cycle_close',
                   summary='Close (archive) a disbursed cycle',
                   request=None, responses={200: PayoutCycleSerializer})
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        _require_planning_admin(request, self.required_permission,
                                'Only plan-wide operators can close a cycle.')
        cycle = PayoutCycleService.close_cycle(self._cycle(pk), actor=request.user)
        return Response(PayoutCycleSerializer(cycle).data)

    @extend_schema(tags=['Incentives'], operation_id='cycle_register',
                   summary='Disbursement register (held payouts excluded)',
                   parameters=[OpenApiParameter('fmt', description='json (default) or csv', type=str),
                               OpenApiParameter('bank_keys', description='comma-separated entity attribute keys', type=str)],
                   responses={200: OpenApiResponse(description='Register rows + totals, or CSV')})
    @action(detail=True, methods=['get'])
    def register(self, request, pk=None):
        cycle = self._cycle(pk)
        bank_keys = [k for k in (request.query_params.get('bank_keys', '') or '').split(',') if k]
        AccessService.record(request.user, 'report_payout', subject_entity_id=None,
                             object_id=cycle.pk)
        if request.query_params.get('fmt') == 'csv':
            csv_text = PayoutCycleService.register_csv(cycle, bank_attribute_keys=bank_keys)
            resp = HttpResponse(csv_text, content_type='text/csv')
            resp['Content-Disposition'] = (
                f'attachment; filename="register-{cycle.target_period.code}.csv"'
            )
            return resp
        return Response(PayoutCycleService.register(cycle, bank_attribute_keys=bank_keys))
