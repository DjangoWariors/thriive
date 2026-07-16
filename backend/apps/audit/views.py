from django.apps import apps as django_apps
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.audit.models import AccessLog, AuditLog, ComputationLog
from apps.audit.serializers import (
    AccessLogSerializer,
    AuditLogSerializer,
    ChainVerifyRequestSerializer,
    ChainVerifyResponseSerializer,
    ComputationLogSerializer,
)
from apps.audit.services import AuditService
from apps.core.pagination import StandardPagination

_TAG = ['Audit']


def _user_labels(user_ids) -> dict[int, str]:
    """Batch-resolve user_id → display label, avoiding N+1 in log lists."""
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    User = django_apps.get_model('accounts', 'User')
    labels = {}
    for u in User.objects.filter(pk__in=ids).only('id', 'first_name', 'last_name', 'email'):
        name = f'{u.first_name} {u.last_name}'.strip()
        labels[u.pk] = name or u.email or f'User #{u.pk}'
    return labels


def _apply_date_range(qs, params, field='timestamp'):
    if date_from := params.get('date_from'):
        qs = qs.filter(**{f'{field}__date__gte': date_from})
    if date_to := params.get('date_to'):
        qs = qs.filter(**{f'{field}__date__lte': date_to})
    return qs


_LOG_PARAMS = [
    OpenApiParameter('action', str, description='Filter by action (create/update/move/deactivate/login…).'),
    OpenApiParameter('entity_type', str, description='Filter by record type, e.g. hierarchy.Node.'),
    OpenApiParameter('user', int, description='Filter by acting user id.'),
    OpenApiParameter('q', str, description='Free-text search within the changes payload.'),
    OpenApiParameter('date_from', str, description='ISO date lower bound (inclusive).'),
    OpenApiParameter('date_to', str, description='ISO date upper bound (inclusive).'),
]


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List audit log entries', parameters=_LOG_PARAMS),
    retrieve=extend_schema(tags=_TAG, summary='Retrieve a single audit entry'),
)
class AuditLogViewSet(ReadOnlyModelViewSet):
    required_permission = 'audit_logs'
    serializer_class = AuditLogSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = AuditLog.objects.all().order_by('-id')
        p = self.request.query_params
        if val := p.get('action'):
            qs = qs.filter(action=val)
        if val := p.get('entity_type'):
            qs = qs.filter(entity_type=val)
        if val := p.get('user'):
            qs = qs.filter(user_id=val)
        if val := p.get('q'):
            qs = qs.filter(changes__icontains=val)
        return _apply_date_range(qs, p)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        rows = getattr(self, '_page_rows', None)
        if rows is not None:
            ctx['user_labels'] = _user_labels(r.user_id for r in rows)
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        self._page_rows = page if page is not None else list(qs)
        ser = self.get_serializer(self._page_rows, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


@extend_schema(tags=_TAG, summary='Full audit history for one record',
               responses={200: AuditLogSerializer(many=True)})
class RecordHistoryView(ListAPIView):
    required_permission = 'audit_logs'
    serializer_class = AuditLogSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return AuditLog.objects.filter(
            entity_type=self.kwargs['entity_type'],
            entity_id=self.kwargs['entity_id'],
        ).order_by('-id')

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['user_labels'] = _user_labels(
            AuditLog.objects.filter(
                entity_type=self.kwargs['entity_type'],
                entity_id=self.kwargs['entity_id'],
            ).values_list('user_id', flat=True)
        )
        return ctx


_COMP_PARAMS = [
    OpenApiParameter('computation_type', str, description='payout / achievement.'),
    OpenApiParameter('period', int, description='Filter by target period id.'),
    OpenApiParameter('entity', int, description='Filter by entity id.'),
]


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='List computation logs', parameters=_COMP_PARAMS),
    retrieve=extend_schema(tags=_TAG, summary='Computation snapshot (explain this number)'),
)
class ComputationLogViewSet(ReadOnlyModelViewSet):
    required_permission = 'audit_logs'
    serializer_class = ComputationLogSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ComputationLog.objects.all().order_by('-id')
        p = self.request.query_params
        if val := p.get('computation_type'):
            qs = qs.filter(computation_type=val)
        if val := p.get('period'):
            qs = qs.filter(period_id=val)
        if val := p.get('entity'):
            qs = qs.filter(entity_id=val)
        return qs


_ACCESS_PARAMS = [
    OpenApiParameter('resource', str, description='payout / payout_register…'),
    OpenApiParameter('subject_entity', int, description='Whose data was disclosed.'),
    OpenApiParameter('user', int, description='Who accessed it.'),
    OpenApiParameter('date_from', str), OpenApiParameter('date_to', str),
]


@extend_schema_view(
    list=extend_schema(tags=_TAG, summary='Disclosure trail for confidential reads',
                       parameters=_ACCESS_PARAMS),
)
class AccessLogViewSet(ReadOnlyModelViewSet):
    """Higher bar than audit_logs: seeing the disclosure trail is itself sensitive."""
    required_permission = 'audit_access'
    serializer_class = AccessLogSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        qs = AccessLog.objects.all().order_by('-id')
        p = self.request.query_params
        if val := p.get('resource'):
            qs = qs.filter(resource=val)
        if val := p.get('subject_entity'):
            qs = qs.filter(subject_entity_id=val)
        if val := p.get('user'):
            qs = qs.filter(user_id=val)
        return _apply_date_range(qs, p)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        rows = getattr(self, '_page_rows', None)
        if rows is not None:
            ctx['user_labels'] = _user_labels(r.user_id for r in rows)
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        self._page_rows = page if page is not None else list(qs)
        ser = self.get_serializer(self._page_rows, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


@extend_schema(tags=_TAG, summary='Verify audit chain integrity',
               request=ChainVerifyRequestSerializer,
               responses={200: ChainVerifyResponseSerializer})
class ChainVerifyView(APIView):
    required_permission = 'audit_logs'

    def post(self, request):
        ser = ChainVerifyRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = AuditService.verify_chain(
            ser.validated_data.get('start_id'),
            ser.validated_data.get('end_id'),
        )
        return Response(result)
