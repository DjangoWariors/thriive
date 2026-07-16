from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import APIKey, LoginAttempt, OTPToken, Role, User, UserRole


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'mobile', 'employee_id', 'first_name', 'last_name', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active', 'is_superuser')
    search_fields = ('email', 'mobile', 'employee_id', 'first_name', 'last_name')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Identity', {'fields': ('mobile', 'employee_id', 'first_name', 'last_name', 'designation', 'department')}),
        ('Node', {'fields': ('entity',)}),
        ('Access', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Security', {'fields': ('failed_login_count', 'locked_until')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
    )
    filter_horizontal = ('groups', 'user_permissions')


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_system_role', 'is_active')
    list_filter = ('is_system_role', 'is_active')
    search_fields = ('name', 'code')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'effective_from', 'effective_to', 'is_active')
    list_filter = ('is_active', 'role')
    search_fields = ('user__email', 'user__mobile', 'role__name')
    raw_id_fields = ('user', 'role')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OTPToken)
class OTPTokenAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'purpose', 'is_used', 'attempts', 'expires_at', 'created_at')
    list_filter = ('purpose', 'is_used')
    search_fields = ('identifier',)
    readonly_fields = ('created_at',)


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key_prefix', 'user', 'expires_at', 'last_used_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'key_prefix', 'user__email')
    raw_id_fields = ('user',)
    readonly_fields = ('key_prefix', 'hashed_key', 'last_used_at', 'created_at', 'updated_at')


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'method', 'success', 'ip_address', 'timestamp')
    list_filter = ('method', 'success')
    search_fields = ('identifier', 'ip_address')
    readonly_fields = ('timestamp',)
    raw_id_fields = ('user',)
