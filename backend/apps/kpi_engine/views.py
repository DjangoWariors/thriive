from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from rest_framework.views import APIView

from apps.core.exceptions import BusinessError
from apps.core.pagination import StandardPagination
from apps.core.scoping import scope_transactions_by_territory
from apps.core.throttling import BulkImportRateThrottle, IntegrationRateThrottle
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.jobs.utils import count_rows

from .models import ExternalMetric, ExternalMetricValue, IntegrationBatch, KPIDefinition, KpiTemplate, Transaction
from .serializers import (
    ExternalMetricSerializer,
    ExternalMetricValueSerializer,
    IntegrationBatchSerializer,
    KPIConfigValidateSerializer,
    KPIDefinitionListSerializer,
    KPIDefinitionSerializer,
    KPIPreviewSerializer,
    KpiTemplateSerializer,
    MetricValueBulkImportSerializer,
    MetricValuePushSerializer,
    TransactionBulkImportSerializer,
    TransactionPushSerializer,
    TransactionSerializer,
)
from .services import ExternalMetricService, IngestionService, KPIService

_KPI_QUERY_PARAMS = [
    OpenApiParameter('search', description='Match against KPI code or name', required=False, type=str),
    OpenApiParameter('kpi_type', description='Filter by KPI type', required=False, type=str),
    OpenApiParameter('category', description='Filter by category', required=False, type=str),
    OpenApiParameter('channel', description='Filter by a channel code in channel_filter', required=False, type=str),
    OpenApiParameter('entity_type', description='Filter by an entity type code in applicable_entity_types', required=False, type=str),
]


@extend_schema_view(
    retrieve=extend_schema(tags=['KPIs'], summary='Retrieve KPI definition'),
    update=extend_schema(tags=['KPIs'], summary='Update KPI (creates a new version)'),
    partial_update=extend_schema(tags=['KPIs'], summary='Partial update KPI (creates a new version)'),
    destroy=extend_schema(tags=['KPIs'], summary='Deactivate KPI (soft delete)'),
)
class KPIDefinitionViewSet(ModelViewSet):
    required_permission = 'kpi_definitions'
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'list':
            return KPIDefinitionListSerializer
        return KPIDefinitionSerializer

    def get_queryset(self):
        qs = KPIDefinition.objects.filter(is_current=True, is_active=True)
        params = self.request.query_params
        if search := params.get('search'):
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if kpi_type := params.get('kpi_type'):
            qs = qs.filter(kpi_type=kpi_type)
        if category := params.get('category'):
            qs = qs.filter(category=category)
        if channel := params.get('channel'):
            qs = qs.filter(channel_filter__contains=channel)
        if entity_type := params.get('entity_type'):
            qs = qs.filter(applicable_entity_types__contains=entity_type)
        return qs.order_by('code')

    def perform_create(self, serializer):
        serializer.instance = KPIService.create_kpi(serializer.validated_data, actor=self.request.user)

    def perform_update(self, serializer):
        serializer.instance = KPIService.update_kpi(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        KPIService.deactivate_kpi(instance, actor=self.request.user)

    @extend_schema(
        tags=['KPIs'], summary='List KPI definitions',
        parameters=_KPI_QUERY_PARAMS, responses={200: KPIDefinitionListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(tags=['KPIs'], summary='Create KPI definition')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        tags=['KPIs'], operation_id='kpi_blueprint', summary='All current KPI definitions',
        description='Returns every current KPI with full config — used by the builder UI.',
        responses={200: KPIDefinitionSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='blueprint')
    def blueprint(self, request):
        qs = KPIDefinition.objects.filter(is_current=True, is_active=True).order_by('category', 'code')
        return Response(KPIDefinitionSerializer(qs, many=True).data)

    @extend_schema(
        tags=['KPIs'], operation_id='kpi_versions', summary='Version history for a KPI',
        responses={200: KPIDefinitionSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        obj = self.get_object()
        qs = KPIDefinition.objects.filter(code=obj.code).order_by('version')
        return Response(KPIDefinitionSerializer(qs, many=True).data)

    @extend_schema(
        tags=['KPIs'], operation_id='kpi_validate', summary='Validate a KPI config',
        description='Structural validation without saving. Returns {valid, errors}.',
        request=KPIConfigValidateSerializer,
        responses={200: OpenApiResponse(description='{valid: bool, errors: [str]}')},
    )
    @action(detail=False, methods=['post'], url_path='validate')
    def validate(self, request):
        ser = KPIConfigValidateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        errors = KPIService.validate_kpi_config(dict(ser.validated_data))
        return Response({'valid': not errors, 'errors': errors})

    @extend_schema(
        tags=['KPIs'], operation_id='kpi_preview', summary='Preview a KPI computation',
        description='Runs an unsaved KPI config through the calculator for one entity + period.',
        request=KPIPreviewSerializer,
        responses={200: OpenApiResponse(description='{entity_id, period_start, period_end, result, unit}')},
    )
    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        ser = KPIPreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        result = KPIService.preview_kpi(
            dict(data['config']), data['entity_id'], data['period_start'], data['period_end'],
            as_of=data.get('as_of'),
        )
        return Response(result)


@extend_schema_view(
    list=extend_schema(tags=['KPIs'], summary='List KPI templates', responses={200: KpiTemplateSerializer(many=True)}),
    retrieve=extend_schema(tags=['KPIs'], summary='Retrieve a KPI template'),
)
class KpiTemplateViewSet(ReadOnlyModelViewSet):
    """Read-only starting points for the builder. Configurable per client via admin —
    no template is hardcoded in the frontend."""

    required_permission = 'kpi_definitions'
    serializer_class = KpiTemplateSerializer
    pagination_class = None  # small, curated list — return the full array like /blueprint/

    def get_queryset(self):
        return KpiTemplate.objects.filter(is_active=True).order_by('display_order', 'name')


_TXN_QUERY_PARAMS = [
    OpenApiParameter('attributed_node_id', description='Filter by attributed geography node id', required=False, type=int),
    OpenApiParameter('channel_code', description='Filter by channel code', required=False, type=str),
    OpenApiParameter('transaction_level', description='primary / secondary / tertiary', required=False, type=str),
    OpenApiParameter('transaction_type', description='sale / return / credit_note', required=False, type=str),
    OpenApiParameter('date_from', description='Earliest transaction_date (YYYY-MM-DD)', required=False, type=str),
    OpenApiParameter('date_to', description='Latest transaction_date (YYYY-MM-DD)', required=False, type=str),
]


@extend_schema_view(
    retrieve=extend_schema(tags=['Transactions'], summary='Retrieve transaction'),
    create=extend_schema(tags=['Transactions'], summary='Create a single transaction'),
)
class TransactionViewSet(ModelViewSet):
    serializer_class = TransactionSerializer
    required_permission = 'kpi_definitions'
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = Transaction.objects.filter(is_active=True)
        params = self.request.query_params
        if node_id := params.get('attributed_node_id'):
            qs = qs.filter(attributed_node_id=node_id)
        if channel := params.get('channel_code'):
            qs = qs.filter(channel_code=channel)
        if level := params.get('transaction_level'):
            qs = qs.filter(transaction_level=level)
        if txn_type := params.get('transaction_type'):
            qs = qs.filter(transaction_type=txn_type)
        if date_from := params.get('date_from'):
            qs = qs.filter(transaction_date__gte=date_from)
        if date_to := params.get('date_to'):
            qs = qs.filter(transaction_date__lte=date_to)
        # Territory-scope: a placed user sees the transactions of the geography they own
        # (via assignments, expanded to subtrees). attributed_node_id is a plain id column.
        qs = scope_transactions_by_territory(qs, self.request.user, self.required_permission)
        return qs.order_by('-transaction_date', '-id')

    def perform_create(self, serializer):
        # Normalise the single created row to the base unit (the import path does this per row).
        from apps.master_data.services import MasterDataService
        data = serializer.validated_data
        base = MasterDataService.convert_to_base(
            data.get('sku_code', ''), data.get('uom', ''), data.get('quantity', 0),
        )
        serializer.save(base_quantity=base)

    @extend_schema(
        tags=['Transactions'], summary='List transactions',
        parameters=_TXN_QUERY_PARAMS, responses={200: TransactionSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        from apps.hierarchy.models import GeographyNode
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        node_ids = {t.attributed_node_id for t in page}
        labels = {
            n.pk: f'{n.name} ({n.code})'
            for n in GeographyNode.objects.filter(pk__in=node_ids).only('id', 'name', 'code')
        }
        serializer = TransactionSerializer(
            page, many=True,
            context={**self.get_serializer_context(), 'node_labels': labels},
        )
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        tags=['Transactions'],
        summary='Bulk import transactions from CSV',
        description=(
            'Idempotent upsert keyed on (source, external_ref): re-importing the same file '
            'updates rows in place instead of duplicating them. All-or-nothing validation. '
            'Returns a BulkJob (202) — poll /api/v1/jobs/{id}/ for progress and the final result.'
        ),
        request=TransactionBulkImportSerializer,
        responses={202: BulkJobSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk', throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = TransactionBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uploaded = ser.validated_data.get('file')
        raw = uploaded.read().decode('utf-8') if uploaded else ser.validated_data.get('data', '')

        job = JobService.create(
            BulkJob.JobType.TRANSACTION_IMPORT, request.user,
            total_rows=count_rows(raw, 'csv'),
            request_id=getattr(request, 'request_id', ''),
        )
        job = run_or_dispatch(import_transactions_task_ref(), job, raw, 'csv', request.user.pk)
        return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


def import_transactions_task_ref():
    # Local import keeps Celery task discovery lazy (mirrors hierarchy's pattern).
    from apps.kpi_engine.tasks import import_transactions_task
    return import_transactions_task


def import_metric_values_task_ref():
    from apps.kpi_engine.tasks import import_metric_values_task
    return import_metric_values_task


@extend_schema_view(
    list=extend_schema(tags=['External Metrics'], summary='List external metrics'),
    retrieve=extend_schema(tags=['External Metrics'], summary='Retrieve external metric'),
    create=extend_schema(tags=['External Metrics'], summary='Create external metric'),
    update=extend_schema(tags=['External Metrics'], summary='Update external metric'),
    partial_update=extend_schema(tags=['External Metrics'], summary='Partial update external metric'),
    destroy=extend_schema(tags=['External Metrics'], summary='Deactivate external metric'),
)
class ExternalMetricViewSet(ModelViewSet):
    """Catalog of non-transaction fact streams (SFA calls, agency scores, TLSD…)."""

    serializer_class = ExternalMetricSerializer
    required_permission = 'kpi_definitions'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ExternalMetric.objects.filter(is_active=True)
        if search := self.request.query_params.get('search'):
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if granularity := self.request.query_params.get('granularity'):
            qs = qs.filter(granularity=granularity)
        return qs.order_by('code')

    def perform_create(self, serializer):
        serializer.instance = ExternalMetricService.create(serializer.validated_data, actor=self.request.user)

    def perform_update(self, serializer):
        serializer.instance = ExternalMetricService.update(
            serializer.instance, serializer.validated_data, actor=self.request.user,
        )

    def perform_destroy(self, instance):
        ExternalMetricService.deactivate(instance, actor=self.request.user)


_METRIC_VALUE_PARAMS = [
    OpenApiParameter('metric', description='Filter by metric code', required=False, type=str),
    OpenApiParameter('entity', description='Filter by entity id', required=False, type=int),
    OpenApiParameter('node_id', description='Filter by geography node id', required=False, type=int),
    OpenApiParameter('date_from', description='Earliest measured_on (YYYY-MM-DD)', required=False, type=str),
    OpenApiParameter('date_to', description='Latest measured_on (YYYY-MM-DD)', required=False, type=str),
]


@extend_schema_view(
    retrieve=extend_schema(tags=['External Metrics'], summary='Retrieve metric value'),
)
class MetricValueViewSet(ReadOnlyModelViewSet):
    serializer_class = ExternalMetricValueSerializer
    required_permission = 'kpi_definitions'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ExternalMetricValue.objects.filter(is_active=True).select_related('metric')
        params = self.request.query_params
        if metric := params.get('metric'):
            qs = qs.filter(metric__code=metric)
        if entity := params.get('entity'):
            qs = qs.filter(entity_id=entity)
        if node_id := params.get('node_id'):
            qs = qs.filter(node_id=node_id)
        if date_from := params.get('date_from'):
            qs = qs.filter(measured_on__gte=date_from)
        if date_to := params.get('date_to'):
            qs = qs.filter(measured_on__lte=date_to)
        return qs.order_by('-measured_on', '-id')

    @extend_schema(
        tags=['External Metrics'], summary='List metric values',
        parameters=_METRIC_VALUE_PARAMS, responses={200: ExternalMetricValueSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=['External Metrics'],
        summary='Bulk import metric values from CSV',
        description=(
            'Columns: metric_code, measured_on, value, entity_id|node_id (per metric grain), '
            'source?, external_ref?. All-or-nothing validation; idempotent upsert. '
            'Returns a BulkJob (202) — poll /api/v1/jobs/{id}/.'
        ),
        request=MetricValueBulkImportSerializer,
        responses={202: BulkJobSerializer},
    )
    @action(detail=False, methods=['post'], url_path='bulk', throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = MetricValueBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uploaded = ser.validated_data.get('file')
        raw = uploaded.read().decode('utf-8') if uploaded else ser.validated_data.get('data', '')

        job = JobService.create(
            BulkJob.JobType.METRIC_IMPORT, request.user,
            total_rows=count_rows(raw, 'csv'),
            request_id=getattr(request, 'request_id', ''),
        )
        job = run_or_dispatch(import_metric_values_task_ref(), job, raw, 'csv', request.user.pk)
        return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class TransactionPushView(APIView):
    """JSON push for DMS/SFA transaction feeds (API-key or JWT). Partial accept with
    per-row errors; idempotent on (source, external_ref); one IntegrationBatch per push."""

    required_permission = 'integration_push'
    throttle_classes = [IntegrationRateThrottle]

    @extend_schema(
        tags=['Transactions'], operation_id='transactions_push',
        summary='Push transactions (JSON, partial accept)',
        request=TransactionPushSerializer,
        responses={200: OpenApiResponse(
            description='{batch_id, status, received, accepted, rejected, errors, replayed}',
        )},
    )
    def post(self, request):
        ser = TransactionPushSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = IngestionService.push_transactions(
            source=ser.validated_data['source'],
            rows=ser.validated_data['rows'],
            client_batch_ref=ser.validated_data.get('client_batch_ref', ''),
            actor=request.user,
        )
        return Response(result)


class MetricValuePushView(APIView):
    """JSON push for machine integrations (API-key or JWT). Partial accept with
    per-row errors; every push is recorded on an IntegrationBatch."""

    required_permission = 'integration_push'
    throttle_classes = [IntegrationRateThrottle]

    @extend_schema(
        tags=['External Metrics'], operation_id='metric_values_push',
        summary='Push metric values (JSON, partial accept)',
        request=MetricValuePushSerializer,
        responses={200: OpenApiResponse(
            description='{batch_id, status, received, accepted, rejected, errors, replayed}',
        )},
    )
    def post(self, request):
        ser = MetricValuePushSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = IngestionService.push_metric_values(
            source=ser.validated_data['source'],
            rows=ser.validated_data['rows'],
            client_batch_ref=ser.validated_data.get('client_batch_ref', ''),
            actor=request.user,
        )
        return Response(result)


@extend_schema_view(
    list=extend_schema(tags=['Integrations'], summary='List integration batches'),
    retrieve=extend_schema(tags=['Integrations'], summary='Retrieve integration batch (incl. row errors)'),
)
class IntegrationBatchViewSet(ReadOnlyModelViewSet):
    serializer_class = IntegrationBatchSerializer
    required_permission = 'integration_monitor'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = IntegrationBatch.objects.filter(is_active=True).select_related('pushed_by')
        params = self.request.query_params
        if kind := params.get('batch_kind'):
            qs = qs.filter(batch_kind=kind)
        if source := params.get('source'):
            qs = qs.filter(source=source)
        if batch_status := params.get('status'):
            qs = qs.filter(status=batch_status)
        return qs.order_by('-created_at')
