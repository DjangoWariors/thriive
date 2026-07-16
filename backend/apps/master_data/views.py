from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.pagination import StandardPagination
from apps.core.throttling import BulkImportRateThrottle
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.jobs.utils import BULK_ASYNC_THRESHOLD, count_rows

from .models import SKU, SKUGroup, UOMConversion
from .serializers import (
    SKUBulkImportSerializer,
    SKUGroupPreviewSerializer,
    SKUGroupSerializer,
    SKUSerializer,
    UOMConversionSerializer,
)
from .services import MasterDataService

_SKU_QUERY_PARAMS = [
    OpenApiParameter('search', description='Match against SKU code or name', required=False, type=str),
    OpenApiParameter('brand', description='Filter by exact brand', required=False, type=str),
    OpenApiParameter('category', description='Filter by exact category', required=False, type=str),
    OpenApiParameter('is_focus', description='Filter focus SKUs (true/false)', required=False, type=bool),
    OpenApiParameter('is_npi', description='Filter NPI SKUs (true/false)', required=False, type=bool),
]


def _as_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {'true', '1', 'yes', 'y'}


@extend_schema_view(
    retrieve=extend_schema(tags=['Master Data'], summary='Retrieve SKU'),
    update=extend_schema(tags=['Master Data'], summary='Update SKU'),
    partial_update=extend_schema(tags=['Master Data'], summary='Partial update SKU'),
    destroy=extend_schema(tags=['Master Data'], summary='Deactivate SKU (soft delete)'),
)
class SKUViewSet(ModelViewSet):
    serializer_class = SKUSerializer
    required_permission = 'master_data'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = SKU.objects.filter(is_active=True)
        params = self.request.query_params
        if search := params.get('search'):
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if brand := params.get('brand'):
            qs = qs.filter(brand=brand)
        if category := params.get('category'):
            qs = qs.filter(category=category)
        if 'is_focus' in params:
            qs = qs.filter(is_focus=_as_bool(params.get('is_focus')))
        if 'is_npi' in params:
            qs = qs.filter(is_npi=_as_bool(params.get('is_npi')))
        return qs.order_by('code')

    @extend_schema(
        tags=['Master Data'], summary='List SKUs',
        parameters=_SKU_QUERY_PARAMS, responses={200: SKUSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(tags=['Master Data'], summary='Create SKU')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_destroy(self, instance):
        MasterDataService.deactivate_sku(instance, actor=self.request.user)

    @extend_schema(
        tags=['Master Data'],
        summary='Distinct brands and categories',
        description='Distinct non-empty brands and categories across all active SKUs — '
                    'feeds the filter dropdowns so every value is listed, not just the current page.',
        responses={200: OpenApiResponse(description='{brands: [...], categories: [...]}')},
    )
    @action(detail=False, methods=['get'], url_path='facets')
    def facets(self, request):
        return Response(MasterDataService.get_facets())

    @extend_schema(
        tags=['Master Data'],
        summary='Bulk import SKUs from CSV',
        description=(
            'Upsert SKUs from CSV (header: code,name,brand,category,sub_category,mrp,is_focus,is_npi; '
            'extra columns become custom attributes). Keyed on code. All-or-nothing: if any row is '
            'invalid nothing is written and row errors are returned with status 422.\n\n'
            '• run_async=true (or more than the async threshold of rows) → returns 202 with a bulk '
            'job to poll at /api/v1/jobs/{id}/.'
        ),
        request=SKUBulkImportSerializer,
        responses={
            200: OpenApiResponse(description='Success — {status, created, updated}'),
            202: BulkJobSerializer,
            422: OpenApiResponse(description='Validation failed — {status, errors:[{row, error}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk', throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = SKUBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uploaded = ser.validated_data.get('file')
        raw = uploaded.read().decode('utf-8') if uploaded else ser.validated_data.get('data', '')
        run_async = ser.validated_data.get('run_async', False)

        if run_async or count_rows(raw, 'csv') > BULK_ASYNC_THRESHOLD:
            from apps.master_data.tasks import import_skus_task

            job = JobService.create(
                BulkJob.JobType.SKU_IMPORT, request.user,
                total_rows=count_rows(raw, 'csv'),
                request_id=getattr(request, 'request_id', ''),
            )
            job = run_or_dispatch(import_skus_task, job, raw, request.user.pk)
            return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

        result = MasterDataService.bulk_import_skus(raw, actor=request.user)
        if result.get('status') == 'validation_failed':
            return Response(result, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='List SKU groups'),
    retrieve=extend_schema(tags=['Master Data'], summary='Retrieve SKU group'),
    create=extend_schema(tags=['Master Data'], summary='Create SKU group'),
    update=extend_schema(tags=['Master Data'], summary='Update SKU group'),
    partial_update=extend_schema(tags=['Master Data'], summary='Partial update SKU group'),
    destroy=extend_schema(tags=['Master Data'], summary='Deactivate SKU group (soft delete)'),
)
class SKUGroupViewSet(ModelViewSet):
    serializer_class = SKUGroupSerializer
    required_permission = 'master_data'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = SKUGroup.objects.filter(is_active=True).prefetch_related('skus')
        params = self.request.query_params
        if search := params.get('search'):
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if filter_type := params.get('filter_type'):
            qs = qs.filter(filter_type=filter_type)
        return qs.order_by('code')

    def perform_destroy(self, instance):
        MasterDataService.deactivate_sku_group(instance, actor=self.request.user)

    @extend_schema(
        tags=['Master Data'],
        summary='Resolved SKUs for a group',
        description='Returns the actual SKUs this group resolves to (explicit list or rule match).',
        responses={200: SKUSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='skus')
    def skus(self, request, pk=None):
        group = self.get_object()
        return Response(SKUSerializer(group.get_skus(), many=True).data)

    @extend_schema(
        tags=['Master Data'],
        summary='Preview an unsaved group definition',
        description='Resolves a group definition (filter_type + filter_rules or skus) without saving, '
                    'so the builder preview is authoritative. Returns {count, sample:[...up to 25 SKUs]}.',
        request=SKUGroupPreviewSerializer,
        responses={200: OpenApiResponse(description='{count, sample: SKU[]}')},
    )
    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        ser = SKUGroupPreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        qs = MasterDataService.preview_group(
            ser.validated_data['filter_type'],
            filter_rules=ser.validated_data.get('filter_rules'),
            sku_ids=[s.id for s in ser.validated_data.get('skus', [])],
        )
        return Response({
            'count': qs.count(),
            'sample': SKUSerializer(qs[:25], many=True).data,
        })


@extend_schema_view(
    list=extend_schema(tags=['Master Data'], summary='List UOM conversions'),
    retrieve=extend_schema(tags=['Master Data'], summary='Retrieve UOM conversion'),
    create=extend_schema(tags=['Master Data'], summary='Create UOM conversion'),
    update=extend_schema(tags=['Master Data'], summary='Update UOM conversion'),
    partial_update=extend_schema(tags=['Master Data'], summary='Partial update UOM conversion'),
    destroy=extend_schema(tags=['Master Data'], summary='Deactivate UOM conversion (soft delete)'),
)
class UOMConversionViewSet(ModelViewSet):
    serializer_class = UOMConversionSerializer
    required_permission = 'master_data'
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = UOMConversion.objects.filter(is_active=True)
        params = self.request.query_params
        if search := params.get('search'):
            qs = qs.filter(Q(sku_code__icontains=search) | Q(from_uom__icontains=search))
        if 'sku_code' in params:
            qs = qs.filter(sku_code=params.get('sku_code'))
        return qs.order_by('sku_code', 'from_uom')

    def perform_destroy(self, instance):
        MasterDataService.deactivate_uom_conversion(instance, actor=self.request.user)
