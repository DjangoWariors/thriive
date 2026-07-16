from datetime import date

from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import APIKey, Role, User



class _UserComputedFieldsMixin:
    """SerializerMethodField implementations for User representations."""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_active_roles(self, obj):
        today = date.today()
        user_roles = (
            obj.user_roles
            .filter(is_active=True, effective_from__lte=today)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
            .select_related('role')
        )
        return [
            {
                'id': ur.role.id,
                'name': ur.role.name,
                'code': ur.role.code,
                'permissions': ur.role.permissions,
            }
            for ur in user_roles
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_entity_info(self, obj):
        entity = getattr(obj, 'entity', None)
        if entity is None:
            return None
        entity_type = getattr(entity, 'entity_type', None)
        return {
            'id': entity.id,
            'name': entity.name,
            'code': entity.code,
            'type': getattr(entity_type, 'code', None),
            'path': entity.path,
        }

    @extend_schema_field(serializers.CharField())
    def get_portal_type(self, obj):
        entity = getattr(obj, 'entity', None)
        if entity is None:
            return 'admin'
        entity_type = getattr(entity, 'entity_type', None)
        if entity_type is None:
            #'admin' | 'partner'; never null.
            return 'admin'
        display_config = getattr(entity_type, 'display_config', None) or {}
        return display_config.get('portal_type', 'admin')


class PasswordLoginRequest(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField()


class OTPRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField()


class OTPRequestResponse(serializers.Serializer):
    message = serializers.CharField()
    masked_identifier = serializers.CharField()
    expires_in = serializers.IntegerField()


class OTPVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField()
    otp = serializers.CharField(min_length=1, max_length=10)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()



class UserSerializer(_UserComputedFieldsMixin, serializers.ModelSerializer):
    """Read-only user representation used in auth responses and /me/."""

    active_roles = serializers.SerializerMethodField()
    entity_info = serializers.SerializerMethodField()
    portal_type = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'mobile', 'employee_id',
            'first_name', 'last_name', 'designation', 'department',
            'is_superuser', 'is_active', 'last_login',
            'date_joined', 'active_roles', 'entity_info', 'portal_type',
            'has_password',
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_has_password(self, obj):
        return obj.has_usable_password()


class UserAdminSerializer(_UserComputedFieldsMixin, serializers.ModelSerializer):
    """Full read/write serializer for admin CRUD on User."""

    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
        style={'input_type': 'password'},
    )
    role_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False,
        queryset=Role.objects.filter(is_active=True),
    )
    active_roles = serializers.SerializerMethodField()
    entity_info = serializers.SerializerMethodField()
    portal_type = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'mobile', 'employee_id',
            'first_name', 'last_name', 'designation', 'department',
            'is_staff', 'is_active', 'date_joined',
            'password', 'role_ids', 'active_roles', 'entity_info', 'portal_type',
        ]
        read_only_fields = ['id', 'date_joined']

    def _actor(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def create(self, validated_data):
        from .services import UserService
        return UserService.create_user(validated_data, actor=self._actor())

    def update(self, instance, validated_data):
        from .services import UserService
        return UserService.update_user(instance, validated_data, actor=self._actor())


class MeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'designation', 'department']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class UserBulkImportSerializer(serializers.Serializer):
    """Request body for POST /auth/users/bulk/."""

    format = serializers.ChoiceField(choices=['csv', 'json'], default='csv')
    data = serializers.CharField(
        help_text='CSV text or JSON array. Columns: first_name, last_name, email, '
        'mobile, employee_id, designation, department, password, roles '
        '(comma-separated role codes), entity_code (optional — links to an '
        'existing entity).',
    )
    dry_run = serializers.BooleanField(
        default=False,
        help_text='Validate every row and return a preview/errors without creating anything.',
    )
    run_async = serializers.BooleanField(
        default=False,
        help_text='Process as a background job and return a job_id to poll. '
        'Imports larger than the async threshold are forced async regardless.',
    )


class _BulkRowErrorSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())


class UserBulkImportResultSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['success', 'valid', 'validation_failed'])
    created = serializers.IntegerField(required=False)
    rows = serializers.IntegerField(required=False)
    would_create = serializers.IntegerField(required=False)
    errors = _BulkRowErrorSerializer(many=True, required=False)


class UserBulkRolesSerializer(serializers.Serializer):
    """Request body for POST /auth/users/bulk-roles/."""

    user_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    role_codes = serializers.ListField(
        child=serializers.CharField(), allow_empty=False,
    )
    mode = serializers.ChoiceField(
        choices=['add', 'replace'], default='add',
        help_text="'add' unions with existing roles; 'replace' sets the exact role set.",
    )



class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            'id', 'name', 'code', 'description',
            'permissions', 'is_system_role', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_system_role', 'created_at', 'updated_at']

    def _actor(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def create(self, validated_data):
        from .services import RoleService
        return RoleService.create_role(validated_data, actor=self._actor())

    def update(self, instance, validated_data):
        from .services import RoleService
        return RoleService.update_role(instance, validated_data, actor=self._actor())



class LoginResponse(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class ErrorResponse(serializers.Serializer):
    error = serializers.BooleanField()
    status_code = serializers.IntegerField()
    detail = serializers.CharField()


class _PermissionResourceSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    levels = serializers.ListField(child=serializers.CharField())


class _PermissionGroupSerializer(serializers.Serializer):
    group = serializers.CharField()
    resources = _PermissionResourceSerializer(many=True)


class PermissionCatalogSerializer(serializers.Serializer):
    """Schema for the permission-catalog endpoint (documentation only)."""
    groups = _PermissionGroupSerializer(many=True)
    levels = serializers.ListField(child=serializers.CharField())
    level_labels = serializers.DictField(child=serializers.CharField())


class ApiKeySerializer(serializers.ModelSerializer):
    user_display = serializers.CharField(source='user.__str__', read_only=True)

    class Meta:
        model = APIKey
        fields = [
            'id', 'name', 'key_prefix', 'user', 'user_display',
            'expires_at', 'last_used_at', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'key_prefix', 'last_used_at', 'is_active', 'created_at']


class ApiKeyIssuedSerializer(ApiKeySerializer):
    """Create response — carries the plaintext key, shown exactly once."""

    key = serializers.CharField(read_only=True)

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ['key']
