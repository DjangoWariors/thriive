import csv
import io
from datetime import date

from django.db.models import Q
from django.http import HttpResponse
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as _JWTRefreshView

from apps.core.scoping import NodeScopedQuerysetMixin
from apps.core.throttling import BulkImportRateThrottle
from apps.jobs.dispatch import run_or_dispatch
from apps.jobs.models import BulkJob
from apps.jobs.serializers import BulkJobSerializer
from apps.jobs.services import JobService
from apps.jobs.utils import BULK_ASYNC_THRESHOLD, count_rows

from .models import APIKey, Role, User
from .permission_catalog import LEVEL_LABELS, LEVELS, PERMISSION_CATALOG
from .serializers import (
    ApiKeyIssuedSerializer,
    ApiKeySerializer,
    ChangePasswordSerializer,
    ErrorResponse,
    LoginResponse,
    LogoutSerializer,
    MeUpdateSerializer,
    OTPRequestResponse,
    OTPRequestSerializer,
    OTPVerifySerializer,
    PasswordLoginRequest,
    PermissionCatalogSerializer,
    RoleSerializer,
    UserAdminSerializer,
    UserBulkImportResultSerializer,
    UserBulkImportSerializer,
    UserBulkRolesSerializer,
    UserSerializer,
)
from .services import ApiKeyService, AuthService, RoleService, UserService

_ERR_401 = OpenApiResponse(response=ErrorResponse, description='Invalid credentials')
_ERR_423 = OpenApiResponse(response=ErrorResponse, description='Account locked')
_ERR_429 = OpenApiResponse(response=ErrorResponse, description='Too many OTP requests')


def _extract_ip(request):
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    return ip or None


class PasswordLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_login_password',
        summary='Password login',
        description='Authenticate with email / mobile / employee_id and password. Returns JWT tokens.',
        request=PasswordLoginRequest,
        responses={200: LoginResponse, 401: _ERR_401, 423: _ERR_423},
    )
    def post(self, request):
        ser = PasswordLoginRequest(data=request.data)
        ser.is_valid(raise_exception=True)

        result = AuthService.authenticate_password(
            identifier=ser.validated_data['identifier'],
            password=ser.validated_data['password'],
            ip=_extract_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        if result['status'] == 'locked':
            return Response(
                {'error': True, 'status_code': 423, 'detail': 'Account locked due to too many failed attempts.'},
                status=status.HTTP_423_LOCKED,
            )
        if result['status'] == 'failed':
            return Response(
                {'error': True, 'status_code': 401, 'detail': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(
            {**result['tokens'], 'user': UserSerializer(result['user']).data},
            status=status.HTTP_200_OK,
        )



class OTPRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_otp_request',
        summary='Request OTP',
        description='Send a one-time password to the given email or mobile identifier.',
        request=OTPRequestSerializer,
        responses={200: OTPRequestResponse, 429: _ERR_429},
    )
    def post(self, request):
        ser = OTPRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        result = AuthService.request_otp(identifier=ser.validated_data['identifier'])

        if result['status'] == 'rate_limited':
            return Response(
                {'error': True, 'status_code': 429, 'detail': 'Too many OTP requests. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response(
            {
                'message': 'OTP sent successfully.',
                'masked_identifier': result['masked_identifier'],
                'expires_in': result['expires_in'],
            },
            status=status.HTTP_200_OK,
        )


class OTPVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_otp_verify',
        summary='Verify OTP',
        description='Verify a one-time password and receive JWT tokens.',
        request=OTPVerifySerializer,
        responses={200: LoginResponse, 401: _ERR_401},
    )
    def post(self, request):
        ser = OTPVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        result = AuthService.verify_otp(
            identifier=ser.validated_data['identifier'],
            otp=ser.validated_data['otp'],
            ip=_extract_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        if result['status'] == 'failed':
            return Response(
                {'error': True, 'status_code': 401, 'detail': 'Invalid or expired OTP.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(
            {**result['tokens'], 'user': UserSerializer(result['user']).data},
            status=status.HTTP_200_OK,
        )



class TokenRefreshView(_JWTRefreshView):
    @extend_schema(
        tags=['Auth'],
        operation_id='auth_token_refresh',
        summary='Refresh access token',
        description='Exchange a valid refresh token for a new access token. Rotates refresh token.',
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_logout',
        summary='Logout',
        description='Blacklist the supplied refresh token, invalidating the session.',
        request=LogoutSerializer,
        responses={200: OpenApiResponse(description='Logged out')},
    )
    def post(self, request):
        ser = LogoutSerializer(data=request.data)
        if ser.is_valid():
            try:
                token = RefreshToken(ser.validated_data['refresh'])
                token.blacklist()
            except TokenError:
                pass
        return Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_me_get',
        summary='Get current user',
        responses={200: UserSerializer},
    )
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_me_update',
        summary='Update own profile',
        request=MeUpdateSerializer,
        responses={200: UserSerializer},
    )
    def patch(self, request):
        ser = MeUpdateSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_change_password',
        summary='Change own password',
        request=ChangePasswordSerializer,
        responses={200: OpenApiResponse(description='Password changed')},
    )
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        AuthService.change_password(
            request.user,
            ser.validated_data['old_password'],
            ser.validated_data['new_password'],
        )
        return Response({'detail': 'Password changed.'}, status=status.HTTP_200_OK)


class PermissionCatalogView(APIView):
    """Metadata for the role editor.
        Defines every configurable permission resource, its display label, valid access
        levels, and the global permission hierarchy.
        All definitions come from `apps.accounts.permission_catalog`, allowing the
        frontend to generate the permission matrix directly from the backend and
        prevent inconsistencies.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Auth'],
        operation_id='auth_permission_catalog',
        summary='Permission catalog (resources, groups, levels)',
        responses={200: PermissionCatalogSerializer},
    )
    def get(self, request):
        return Response({
            'groups': PERMISSION_CATALOG,
            'levels': LEVELS,
            'level_labels': LEVEL_LABELS,
        })


_USER_LIST_PARAMS = [
    OpenApiParameter('search', str, description='Search name, email, mobile, or employee ID.'),
    OpenApiParameter('status', str, description="Status filter: 'active' (default), 'inactive', or 'all'."),
    OpenApiParameter('role', str, description='Filter by assigned role code (active assignments only).'),
    OpenApiParameter('entity_type', str, description='Filter by linked entity type code.'),
    OpenApiParameter('department', str, description='Filter by exact department.'),
]


@extend_schema_view(
    list=extend_schema(tags=['Users'], summary='List users', parameters=_USER_LIST_PARAMS),
    retrieve=extend_schema(tags=['Users'], summary='Retrieve user'),
    create=extend_schema(tags=['Users'], summary='Create user'),
    update=extend_schema(tags=['Users'], summary='Update user'),
    partial_update=extend_schema(tags=['Users'], summary='Partial update user'),
    destroy=extend_schema(tags=['Users'], summary='Deactivate user (soft delete)'),
)
class UserViewSet(NodeScopedQuerysetMixin, ModelViewSet):
    required_permission = 'user_management'
    # Scope to the requester's subtree: users are matched via their linked
    # entity's path.
    scope_path_field = 'entity__path'
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['first_name', 'last_name', 'email', 'mobile', 'employee_id']
    ordering_fields = ['first_name', 'last_name', 'email', 'department', 'date_joined', 'last_login']
    ordering = ['id']

    def get_queryset(self):
        qs = User.objects.select_related('entity__entity_type').order_by('id')
        params = self.request.query_params

        status_val = params.get('status', 'active')
        if status_val == 'inactive':
            qs = qs.filter(is_active=False)
        elif status_val != 'all':
            qs = qs.filter(is_active=True)

        if role_code := params.get('role'):
            today = date.today()
            qs = qs.filter(
                user_roles__is_active=True,
                user_roles__role__code=role_code,
                user_roles__effective_from__lte=today,
            ).filter(
                Q(user_roles__effective_to__isnull=True)
                | Q(user_roles__effective_to__gte=today),
            ).distinct()

        if entity_type := params.get('entity_type'):
            qs = qs.filter(entity__entity_type__code=entity_type)

        if department := params.get('department'):
            qs = qs.filter(department=department)

        return self.scope_queryset(qs)

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return UserAdminSerializer
        return UserSerializer

    def perform_destroy(self, instance):
        UserService.deactivate_user(instance, actor=self.request.user)

    @extend_schema(
        tags=['Users'],
        operation_id='user_reactivate',
        summary='Reactivate a deactivated user',
        responses={200: UserSerializer},
    )
    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        # Bypass the active-only default queryset so inactive users are reachable.
        user = User.objects.filter(pk=pk).first()
        if user is None:
            return Response(
                {'error': True, 'status_code': 404, 'detail': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.check_object_permissions(request, user)
        UserService.reactivate_user(user, actor=request.user)
        return Response(UserSerializer(user).data)

    @extend_schema(
        tags=['Users'],
        operation_id='user_departments',
        summary='List distinct departments',
        description='Distinct, non-empty department names across active users — for filter dropdowns.',
        responses={200: OpenApiResponse(response=list, description='List of department names')},
    )
    @action(detail=False, methods=['get'])
    def departments(self, request):
        values = (
            self.scope_queryset(User.objects.filter(is_active=True))
            .exclude(department='')
            .order_by('department')
            .values_list('department', flat=True)
            .distinct()
        )
        return Response(list(values))

    @extend_schema(
        tags=['Users'],
        operation_id='user_bulk_import',
        summary='Bulk import users',
        description='Import users from CSV text or a JSON array. All-or-nothing: if any '
        'row fails validation, nothing is created.\n\n'
        '• dry_run=true → validate only, returns {status: valid|validation_failed} and creates nothing.\n'
        '• run_async=true (or more than the async threshold of rows) → returns 202 with a '
        'bulk job to poll at /api/v1/jobs/{id}/.',
        request=UserBulkImportSerializer,
        responses={
            201: UserBulkImportResultSerializer,
            202: BulkJobSerializer,
            200: UserBulkImportResultSerializer,
        },
    )
    @action(detail=False, methods=['post'], throttle_classes=[BulkImportRateThrottle])
    def bulk(self, request):
        ser = UserBulkImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data['data']
        fmt = ser.validated_data['format']
        dry_run = ser.validated_data.get('dry_run', False)
        run_async = ser.validated_data.get('run_async', False)

        if dry_run:
            result = UserService.bulk_import_users(data=data, fmt=fmt, actor=request.user, dry_run=True)
            code = status.HTTP_200_OK if result['status'] == 'valid' else status.HTTP_422_UNPROCESSABLE_ENTITY
            return Response(result, status=code)

        if run_async or count_rows(data, fmt) > BULK_ASYNC_THRESHOLD:
            from apps.accounts.tasks import import_users_task

            job = JobService.create(
                BulkJob.JobType.USER_IMPORT, request.user,
                total_rows=count_rows(data, fmt),
                request_id=getattr(request, 'request_id', ''),
            )
            job = run_or_dispatch(import_users_task, job, data, fmt, request.user.pk)
            return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

        result = UserService.bulk_import_users(data=data, fmt=fmt, actor=request.user)
        code = status.HTTP_201_CREATED if result['status'] == 'success' else status.HTTP_200_OK
        return Response(result, status=code)

    @extend_schema(
        tags=['Users'],
        operation_id='user_bulk_roles',
        summary='Bulk assign roles to users',
        description="Assign roles to many users at once. mode='add' unions with each user's "
        "current roles; mode='replace' sets the exact role set. All-or-nothing.",
        request=UserBulkRolesSerializer,
        responses={
            200: OpenApiResponse(description='Success — {status, updated}'),
            422: OpenApiResponse(description='Validation failed — {status, errors: [{id, errors}]}'),
        },
    )
    @action(detail=False, methods=['post'], url_path='bulk-roles')
    def bulk_roles(self, request):
        ser = UserBulkRolesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = UserService.bulk_assign_roles(
            user_ids=ser.validated_data['user_ids'],
            role_codes=ser.validated_data['role_codes'],
            actor=request.user,
            mode=ser.validated_data['mode'],
        )
        code = status.HTTP_200_OK if result['status'] == 'success' else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(result, status=code)

    @extend_schema(
        tags=['Users'],
        operation_id='user_export',
        summary='Export users as CSV',
        description='Stream the current (filtered) user list as a CSV download. Honours the '
        'same search/status/role/entity_type/department filters as the list endpoint.',
        parameters=_USER_LIST_PARAMS,
        responses={200: OpenApiResponse(description='CSV file')},
    )
    @action(detail=False, methods=['get'])
    def export(self, request):
        qs = self.filter_queryset(self.get_queryset()).select_related('entity')
        today = date.today()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'first_name', 'last_name', 'email', 'mobile', 'employee_id',
            'designation', 'department', 'status', 'roles', 'entity_code',
            'entity', 'last_login',
        ])
        for user in qs:
            active_roles = (
                user.user_roles
                .filter(is_active=True, effective_from__lte=today)
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
                .select_related('role')
            )
            writer.writerow([
                user.first_name,
                user.last_name,
                user.email or '',
                user.mobile or '',
                user.employee_id or '',
                user.designation,
                user.department,
                'active' if user.is_active else 'inactive',
                ','.join(ur.role.code for ur in active_roles),
                user.entity.code if user.entity_id else '',
                user.entity.name if user.entity_id else '',
                user.last_login.isoformat() if user.last_login else '',
            ])

        response = HttpResponse(buffer.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users.csv"'
        return response


@extend_schema_view(
    list=extend_schema(tags=['Roles'], summary='List roles'),
    retrieve=extend_schema(tags=['Roles'], summary='Retrieve role'),
    create=extend_schema(tags=['Roles'], summary='Create role'),
    update=extend_schema(tags=['Roles'], summary='Update role'),
    partial_update=extend_schema(tags=['Roles'], summary='Partial update role'),
    destroy=extend_schema(tags=['Roles'], summary='Delete role'),
)
class RoleViewSet(ModelViewSet):
    serializer_class = RoleSerializer
    required_permission = 'role_management'

    def get_queryset(self):
        return Role.objects.filter(is_active=True).order_by('id')

    def perform_destroy(self, instance):
        RoleService.delete_role(instance, actor=self.request.user)


@extend_schema_view(
    list=extend_schema(tags=['API Keys'], summary='List API keys'),
    retrieve=extend_schema(tags=['API Keys'], summary='Retrieve API key'),
    create=extend_schema(
        tags=['API Keys'], summary='Issue an API key',
        description='The plaintext key is returned once in this response and never again.',
        responses={201: ApiKeyIssuedSerializer},
    ),
    destroy=extend_schema(tags=['API Keys'], summary='Revoke API key'),
)
class ApiKeyViewSet(ModelViewSet):
    serializer_class = ApiKeySerializer
    required_permission = 'system_admin'
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return APIKey.objects.filter(is_active=True).select_related('user').order_by('-created_at')

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key, plaintext = ApiKeyService.issue(
            name=ser.validated_data['name'],
            user=ser.validated_data['user'],
            expires_at=ser.validated_data.get('expires_at'),
            actor=request.user,
        )
        data = ApiKeyIssuedSerializer(key).data
        data['key'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        ApiKeyService.revoke(instance, actor=self.request.user)
