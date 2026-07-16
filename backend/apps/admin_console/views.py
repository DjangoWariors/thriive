from django.conf import settings as django_settings
from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.admin_console.models import FeatureFlag, SystemSetting
from apps.admin_console.serializers import (
    FeatureFlagSerializer,
    SettingUpdateSerializer,
    SystemSettingSerializer,
)
from apps.admin_console.services import SystemSettingService
from apps.core.pagination import StandardPagination
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer

_TAG = ['Admin']


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List system settings',
                       parameters=[OpenApiParameter('category', str)]),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a system setting'),
)
class SystemSettingViewSet(ReadOnlyModelViewSet):
    required_permission = 'system_admin'
    serializer_class = SystemSettingSerializer
    pagination_class = None

    def get_queryset(self):
        qs = SystemSetting.objects.filter(is_active=True)
        if cat := self.request.query_params.get('category'):
            qs = qs.filter(category=cat)
        return qs

    @extend_schema(tags=_TAG, summary='Update a setting value (audited)',
                   request=SettingUpdateSerializer, responses={200: SystemSettingSerializer})
    @action(detail=True, methods=['post'])
    def update_value(self, request, pk=None):
        setting = self.get_object()
        ser = SettingUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        row = SystemSettingService.set(setting.key, ser.validated_data['value'], request.user)
        return Response(SystemSettingSerializer(row, context={'request': request}).data)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List feature flags'),
    create=extend_schema(tags=_TAG, summary='Create a feature flag'),
    update=extend_schema(tags=_TAG, summary='Update a feature flag'),
    destroy=extend_schema(tags=_TAG, summary='Delete a feature flag'),
)
class FeatureFlagViewSet(ModelViewSet):
    required_permission = 'system_admin'
    serializer_class = FeatureFlagSerializer
    pagination_class = None
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return FeatureFlag.objects.filter(is_active=True)


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='Monitor bulk jobs (all users)',
                       parameters=[OpenApiParameter('job_type', str), OpenApiParameter('status', str)]),
    retrieve=extend_schema(tags=_TAG, summary='Bulk job detail with per-row errors'),
)
class JobsMonitorViewSet(ReadOnlyModelViewSet):
    required_permission = 'system_admin'
    serializer_class = BulkJobSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = BulkJob.objects.all().order_by('-created_at')
        p = self.request.query_params
        if jt := p.get('job_type'):
            qs = qs.filter(job_type=jt)
        if st := p.get('status'):
            qs = qs.filter(status=st)
        return qs


@extend_schema(tags=_TAG, summary='Scheduled task health (celery-beat)')
class SchedulesHealthView(APIView):
    required_permission = 'system_admin'

    def get(self, request):
        try:
            from django_celery_beat.models import PeriodicTask
        except Exception:  # pragma: no cover
            return Response([])
        rows = []
        for t in PeriodicTask.objects.select_related('crontab', 'interval').all():
            rows.append({
                'name': t.name,
                'task': t.task,
                'enabled': t.enabled,
                'schedule': str(t.crontab or t.interval or ''),
                'last_run_at': t.last_run_at,
                'total_run_count': t.total_run_count,
            })
        return Response(rows)


@extend_schema(tags=_TAG, summary='System health snapshot')
class SystemHealthView(APIView):
    required_permission = 'system_admin'

    def get(self, request):
        db_ok = True
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
        except Exception:  # noqa: BLE001
            db_ok = False

        cache_ok = True
        try:
            from django.core.cache import cache
            cache.set('health_probe', '1', 5)
            cache_ok = cache.get('health_probe') == '1'
        except Exception:  # noqa: BLE001
            cache_ok = False

        queued = BulkJob.objects.filter(status=BulkJob.Status.QUEUED)
        oldest = queued.order_by('created_at').first()
        oldest_age = (timezone.now() - oldest.created_at).total_seconds() if oldest else 0

        return Response({
            'database': 'ok' if db_ok else 'down',
            'cache': 'ok' if cache_ok else 'down',
            'broker_configured': bool(getattr(django_settings, 'CELERY_BROKER_URL', '')),
            'queued_jobs': queued.count(),
            'oldest_queued_job_age_seconds': int(oldest_age),
        })
