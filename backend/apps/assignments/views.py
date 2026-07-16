from datetime import date

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.exceptions import BusinessError

from .models import Assignment
from .serializers import (
    AssignmentCreateSerializer,
    AssignmentEndSerializer,
    AssignmentSerializer,
    AssignmentTransferSerializer,
)
from .services import AssignmentService


def _parse_on(request) -> date:
    raw = request.query_params.get('on')
    if not raw:
        return date.today()
    parsed = date.fromisoformat(raw) if _is_iso(raw) else None
    if parsed is None:
        raise BusinessError("'on' must be an ISO date (YYYY-MM-DD).")
    return parsed


def _is_iso(raw: str) -> bool:
    try:
        date.fromisoformat(raw)
        return True
    except ValueError:
        return False


@extend_schema_view(
    list=extend_schema(
        tags=['Assignments'],
        summary='List assignments',
        parameters=[
            OpenApiParameter('scope', description='Filter by geography node id', required=False, type=int),
            OpenApiParameter('assignee', description='Filter by organisation entity id', required=False, type=int),
            OpenApiParameter('role', description='owner | stand_in | supervisor', required=False, type=str),
            OpenApiParameter('open', description='If true, only currently-open assignments', required=False, type=bool),
            OpenApiParameter('q', description='Search by assignee name or territory name/code', required=False, type=str),
        ],
    ),
    retrieve=extend_schema(tags=['Assignments'], summary='Retrieve assignment'),
)
class AssignmentViewSet(ModelViewSet):
    serializer_class = AssignmentSerializer
    required_permission = 'hierarchy_management'
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = Assignment.objects.filter(is_active=True).select_related('assignee', 'scope')
        params = self.request.query_params
        if scope_id := params.get('scope'):
            qs = qs.filter(scope_id=scope_id)
        if assignee_id := params.get('assignee'):
            qs = qs.filter(assignee_id=assignee_id)
        if role := params.get('role'):
            qs = qs.filter(role_in_scope=role)
        if params.get('open', '').lower() in ('true', '1', 'yes'):
            qs = qs.filter(effective_to__isnull=True)
        if q := params.get('q', '').strip():
            qs = qs.filter(
                Q(assignee__name__icontains=q)
                | Q(scope__name__icontains=q)
                | Q(scope__code__icontains=q)
            )
        return qs.order_by('-effective_from')

    @extend_schema(
        tags=['Assignments'],
        operation_id='assignment_create',
        summary='Open a new assignment',
        request=AssignmentCreateSerializer,
        responses={201: AssignmentSerializer},
    )
    def create(self, request, *args, **kwargs):
        ser = AssignmentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        assignment = AssignmentService.create(user=request.user, **ser.validated_data)
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Assignments'],
        operation_id='assignment_transfer',
        summary='Transfer a territory to a new holder (effective-dated)',
        description='Closes the current holder on the day before effective_from and opens a '
                    'new assignment. The geography, its outlets and targets are untouched.',
        request=AssignmentTransferSerializer,
        responses={200: AssignmentSerializer},
    )
    @action(detail=False, methods=['post'], url_path='transfer')
    def transfer(self, request):
        ser = AssignmentTransferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        assignment = AssignmentService.transfer(user=request.user, **ser.validated_data)
        return Response(AssignmentSerializer(assignment).data)

    @extend_schema(
        tags=['Assignments'],
        operation_id='assignment_end',
        summary='Close an open assignment',
        request=AssignmentEndSerializer,
        responses={200: AssignmentSerializer},
    )
    @action(detail=True, methods=['post'], url_path='end')
    def end(self, request, pk=None):
        ser = AssignmentEndSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        assignment = AssignmentService.end(int(pk), user=request.user, **ser.validated_data)
        return Response(AssignmentSerializer(assignment).data)

    @extend_schema(
        tags=['Assignments'],
        operation_id='assignment_owner_of',
        summary='Who owns a geography scope on a date',
        parameters=[
            OpenApiParameter('scope', description='Geography node id', required=True, type=int),
            OpenApiParameter('on', description='As-of ISO date (default today)', required=False, type=str),
        ],
        responses={200: AssignmentSerializer},
    )
    @action(detail=False, methods=['get'], url_path='owner-of')
    def owner_of(self, request):
        scope_id = request.query_params.get('scope')
        if not scope_id:
            raise BusinessError("'scope' query parameter is required.")
        owner = AssignmentService.owner_of(int(scope_id), on=_parse_on(request))
        if owner is None:
            return Response({'owner': None})
        from apps.assignments.serializers import _NodeRefSerializer
        return Response({'owner': _NodeRefSerializer(owner).data})

    @extend_schema(
        tags=['Assignments'],
        operation_id='assignment_scopes_owned_by',
        summary='Which territories a user owns on a date',
        parameters=[
            OpenApiParameter('user', description='User id (default: the requester)', required=False, type=int),
            OpenApiParameter('on', description='As-of ISO date (default today)', required=False, type=str),
        ],
    )
    @action(detail=False, methods=['get'], url_path='scopes-owned-by')
    def scopes_owned_by(self, request):
        from apps.accounts.models import User

        user_id = request.query_params.get('user')
        target = request.user if not user_id else User.objects.filter(pk=user_id).first()
        if target is None:
            raise BusinessError(f'User {user_id} not found.')
        nodes = AssignmentService.scopes_owned_by(target, on=_parse_on(request))
        from apps.assignments.serializers import _GeographyRefSerializer
        return Response(_GeographyRefSerializer(nodes, many=True).data)
