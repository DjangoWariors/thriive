from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.audit.services import AccessService
from apps.core.exceptions import BusinessError
from apps.core.pagination import StandardPagination
from apps.reports.models import DeliveryTarget, ReportDefinition, ReportExecution, ReportSchedule
from apps.reports.schedule_service import ReportScheduleService
from apps.reports.serializers import (
    DeliveryTargetSerializer,
    GenerateReportSerializer,
    ReportDefinitionSerializer,
    ReportExecutionSerializer,
    ReportScheduleSerializer,
)
from apps.reports.services import ReportService

_TAG = ['Reports']


@extend_schema(tags=_TAG, summary='Report catalog (only reports you may run)',
               responses={200: ReportDefinitionSerializer(many=True)})
class ReportDefinitionListView(ListAPIView):
    serializer_class = ReportDefinitionSerializer
    required_permission = None  # per-report permission enforced in the service
    pagination_class = None

    def get_queryset(self):
        return ReportService.list_runnable(self.request.user)


@extend_schema(tags=_TAG, summary='Generate a report (async)',
               request=GenerateReportSerializer, responses={202: ReportExecutionSerializer})
class GenerateReportView(APIView):
    required_permission = None

    def post(self, request):
        ser = GenerateReportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        execution = ReportService.generate(
            ser.validated_data['code'],
            ser.validated_data['parameters'],
            ser.validated_data['format'],
            request.user,
        )
        return Response(ReportExecutionSerializer(execution).data, status=202)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='My report executions (poll for status)',
                       parameters=[OpenApiParameter('status', str), OpenApiParameter('code', str)]),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a report execution'),
)
class ReportExecutionViewSet(ReadOnlyModelViewSet):
    serializer_class = ReportExecutionSerializer
    required_permission = None
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ReportExecution.objects.select_related('definition', 'requested_by').order_by('-id')
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(requested_by=user)
        p = self.request.query_params
        if status_val := p.get('status'):
            qs = qs.filter(status=status_val)
        if code := p.get('code'):
            qs = qs.filter(definition__code=code)
        return qs


@extend_schema(tags=_TAG, summary='Download a completed report artifact')
class ReportDownloadView(APIView):
    required_permission = None

    def get(self, request, pk):
        qs = ReportExecution.objects.select_related('definition', 'requested_by')
        if not request.user.is_superuser:
            qs = qs.filter(requested_by=request.user)
        execution = qs.filter(pk=pk).first()
        if execution is None:
            raise Http404
        if execution.status != ReportExecution.Status.COMPLETED or not execution.file:
            return Response({'detail': 'Report is not ready.'}, status=409)
        if execution.expires_at and execution.expires_at < timezone.now():
            return Response({'detail': 'This report artifact has expired.'}, status=410)

        ReportService.record_download(request.user, execution)
        resp = FileResponse(execution.file.open('rb'), as_attachment=True,
                            filename=execution.file.name.split('/')[-1])
        return resp


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List report schedules'),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a report schedule'),
    create=extend_schema(tags=_TAG, summary='Create a recurring report schedule'),
    update=extend_schema(tags=_TAG, summary='Update a report schedule'),
    destroy=extend_schema(tags=_TAG, summary='Delete a report schedule'),
)
class ReportScheduleViewSet(ModelViewSet):
    required_permission = 'report_schedule'
    serializer_class = ReportScheduleSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return ReportSchedule.objects.select_related('definition').filter(is_active=True)

    def perform_create(self, serializer):
        schedule = serializer.save(owner=self.request.user)
        ReportScheduleService.sync_beat(schedule)

    def perform_update(self, serializer):
        schedule = serializer.save()
        ReportScheduleService.sync_beat(schedule)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.is_enabled = False
        instance.save(update_fields=['is_active', 'is_enabled', 'updated_at'])
        ReportScheduleService.sync_beat(instance)

    @extend_schema(tags=_TAG, summary='Enable/disable a schedule')
    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        schedule = self.get_object()
        ReportScheduleService.set_enabled(schedule, not schedule.is_enabled)
        return Response(self.get_serializer(schedule).data)

    @extend_schema(tags=_TAG, summary='Run a schedule now (off-cron)')
    @action(detail=True, methods=['post'], url_path='run-now')
    def run_now(self, request, pk=None):
        schedule = self.get_object()
        result = ReportScheduleService.run(schedule)
        return Response(result)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List delivery targets (data lake / SFTP)'),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a delivery target'),
    create=extend_schema(tags=_TAG, summary='Create a delivery target'),
    update=extend_schema(tags=_TAG, summary='Update a delivery target'),
    partial_update=extend_schema(tags=_TAG, summary='Partial update a delivery target'),
    destroy=extend_schema(tags=_TAG, summary='Deactivate a delivery target'),
)
class DeliveryTargetViewSet(ModelViewSet):
    serializer_class = DeliveryTargetSerializer
    required_permission = 'system_admin'
    pagination_class = StandardPagination

    def get_queryset(self):
        return DeliveryTarget.objects.filter(is_active=True).order_by('code')

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

    @extend_schema(tags=_TAG, summary='Test connectivity (writes a marker file)')
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        from apps.reports.delivery import probe
        try:
            return Response(probe(self.get_object()))
        except Exception as exc:  # noqa: BLE001 — surface the failure to the admin
            return Response({'ok': False, 'error': str(exc)}, status=400)


@extend_schema(
    tags=_TAG, operation_id='report_dataset',
    summary='Pull a dataset as paginated JSON rows (data-lake pull API)',
    parameters=[OpenApiParameter('page', int), OpenApiParameter('page_size', int)],
)
class DatasetView(APIView):
    """Same rows the report generator produces, as JSON — for lake/BI consumers that
    prefer pull over scheduled push. Runs in the REQUESTER'S RBAC scope; confidential
    datasets are access-logged like report downloads."""

    required_permission = None  # per-dataset permission enforced below

    def get(self, request, code):
        from apps.reports.registry import get_generator
        from apps.reports.scope import build_scope
        from apps.reports.services import validate_params

        definition = ReportDefinition.objects.filter(
            code=code, is_active=True, is_dataset=True,
        ).first()
        if definition is None:
            raise Http404
        if not ReportService.can_run(request.user, definition):
            return Response({'detail': 'You do not have permission to pull this dataset.'},
                            status=403)

        params = {k: v for k, v in request.query_params.items()
                  if k not in ('page', 'page_size')}
        try:
            validate_params(definition.param_schema, params)
        except BusinessError as exc:
            return Response({'detail': str(exc)}, status=400)

        generator_cls = get_generator(code)
        if generator_cls is None:
            raise Http404
        scope = build_scope(request.user, definition.required_permission)
        result = generator_cls().run(params, scope, request.user)

        if definition.is_confidential:
            AccessService.record(request.user, definition.code, action='export', object_id=0)

        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(1000, max(1, int(request.query_params.get('page_size', 200))))
        start = (page - 1) * page_size
        rows = result.rows[start:start + page_size]
        return Response({
            'dataset': code,
            'title': result.title,
            'columns': [{'key': c.key, 'label': c.label, 'type': c.type} for c in result.columns],
            'count': result.row_count,
            'page': page,
            'page_size': page_size,
            'has_next': start + page_size < result.row_count,
            'results': rows,
        })
