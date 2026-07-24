import logging
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError

from .models import APIKey, LoginAttempt, OTPToken, Role, User, UserRole

logger = logging.getLogger(__name__)


class AuthService:

    @staticmethod
    def change_password(user, old_password: str, new_password: str) -> None:
        """Change the current user's password after verifying the old one.
        OTP-only accounts have no usable password and cannot use this flow.
        New password is run through Django's configured validators.
        """
        if not user.has_usable_password():
            raise BusinessError('This account signs in with OTP and has no password to change.')
        if not user.check_password(old_password):
            raise BusinessError('Current password is incorrect.')
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise BusinessError(' '.join(exc.messages))
        user.set_password(new_password)
        user.save(update_fields=['password'])
        AuditService.log('change_password', 'accounts.User', user.pk, user, {})

    @staticmethod
    def _resolve_user(identifier: str):
        if '@' in identifier:
            return User.objects.filter(email=identifier).first()
        if identifier.isdigit():
            return User.objects.filter(mobile=identifier).first()
        return (
            User.objects.filter(employee_id=identifier).first()
            or User.objects.filter(email=identifier).first()
        )

    @staticmethod
    def _log(user, identifier, method, ip, user_agent, success, reason=''):
        LoginAttempt.objects.create(
            user=user,
            identifier=identifier,
            method=method,
            ip_address=ip or None,
            user_agent=user_agent or '',
            success=success,
            failure_reason=reason,
        )

    @staticmethod
    def _generate_otp(length: int) -> str:
        return str(secrets.randbelow(10 ** length)).zfill(length)

    @staticmethod
    def _mask_identifier(identifier: str) -> str:
        if '@' in identifier:
            local, domain = identifier.split('@', 1)
            if len(local) <= 1:
                return f'{local}@{domain}'
            return f'{local[0]}{"*" * (len(local) - 1)}@{domain}'
        if identifier.isdigit():
            return ('*' * max(0, len(identifier) - 4)) + identifier[-4:]
        if len(identifier) <= 3:
            return identifier
        return f'{identifier[0]}{"*" * (len(identifier) - 2)}{identifier[-1]}'



    @classmethod
    def authenticate_password(cls, identifier: str, password: str, ip=None, user_agent=None):
        max_attempts = settings.THRIIVE_MAX_LOGIN_ATTEMPTS
        lockout_minutes = settings.THRIIVE_LOCKOUT_MINUTES

        user = cls._resolve_user(identifier)


        if user is None:
            cls._log(None, identifier, 'password', ip, user_agent, False, 'user_not_found')
            return {'status': 'failed', 'user': None, 'tokens': None}

        if user.locked_until and user.locked_until > timezone.now():
            cls._log(user, identifier, 'password', ip, user_agent, False, 'account_locked')
            return {'status': 'locked', 'user': user, 'tokens': None}

        if not user.is_active:
            cls._log(user, identifier, 'password', ip, user_agent, False, 'inactive_user')
            return {'status': 'failed', 'user': None, 'tokens': None}
        if not user.check_password(password):
            user.failed_login_count += 1
            if user.failed_login_count >= max_attempts:
                user.locked_until = timezone.now() + timedelta(minutes=lockout_minutes)
            user.save(update_fields=['failed_login_count', 'locked_until'])
            cls._log(user, identifier, 'password', ip, user_agent, False, 'wrong_password')
            if user.locked_until and user.locked_until > timezone.now():
                return {'status': 'locked', 'user': user, 'tokens': None}
            return {'status': 'failed', 'user': None, 'tokens': None}

        user.failed_login_count = 0
        user.locked_until = None
        # Stamp last_login here: JWT issuance never goes through Django's login(), so
        # without this the admin Users grid reads "Never" for everyone, forever.
        user.last_login = timezone.now()
        user.save(update_fields=['failed_login_count', 'locked_until', 'last_login'])



        refresh = RefreshToken.for_user(user)
        tokens = {'access': str(refresh.access_token), 'refresh': str(refresh)}
        cls._log(user, identifier, 'password', ip, user_agent, True)
        return {'status': 'success', 'user': user, 'tokens': tokens}



    @classmethod
    def request_otp(cls, identifier: str):
        rate_limit = settings.THRIIVE_OTP_RATE_LIMIT
        otp_length = settings.THRIIVE_OTP_LENGTH
        expiry_seconds = settings.THRIIVE_OTP_EXPIRY_SECONDS
        window_cutoff = timezone.now() - timedelta(minutes=15)

        recent_count = OTPToken.objects.filter(
            identifier=identifier,
            purpose='login',
            created_at__gte=window_cutoff,
        ).count()

        if recent_count >= rate_limit:
            return {'status': 'rate_limited', 'masked_identifier': None, 'expires_in': None}

        otp = cls._generate_otp(otp_length)
        OTPToken.objects.create(
            identifier=identifier,
            otp=otp,
            purpose='login',
            expires_at=timezone.now() + timedelta(seconds=expiry_seconds),
            max_attempts=3,
        )

        masked = cls._mask_identifier(identifier)

        # Always log in DEBUG so developers can test without an SMS/email gateway
        logger.info('[OTP] %s -> %s (dev mode)', masked, otp)

        return {
            'status': 'success',
            'masked_identifier': masked,
            'expires_in': expiry_seconds,
        }

    @classmethod
    def verify_otp(cls, identifier: str, otp: str, ip=None, user_agent=None):
        now = timezone.now()

        token = (
            OTPToken.objects.filter(
                identifier=identifier,
                purpose='login',
                is_used=False,
                expires_at__gt=now,
            )
            .order_by('-created_at')
            .first()
        )

        if token is None:
            cls._log(None, identifier, 'otp', ip, user_agent, False, 'no_valid_token')
            return {'status': 'failed', 'user': None, 'tokens': None}

        if token.attempts >= token.max_attempts:
            cls._log(None, identifier, 'otp', ip, user_agent, False, 'max_attempts_exceeded')
            return {'status': 'failed', 'user': None, 'tokens': None}

        token.attempts += 1

        if token.otp != otp:
            token.save(update_fields=['attempts'])
            cls._log(None, identifier, 'otp', ip, user_agent, False, 'wrong_otp')
            return {'status': 'failed', 'user': None, 'tokens': None}

        token.is_used = True
        token.save(update_fields=['attempts', 'is_used'])

        user = cls._resolve_user(identifier)
        if user is None or not user.is_active:
            cls._log(None, identifier, 'otp', ip, user_agent, False, 'user_not_found')
            return {'status': 'failed', 'user': None, 'tokens': None}

        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        refresh = RefreshToken.for_user(user)
        tokens = {'access': str(refresh.access_token), 'refresh': str(refresh)}
        cls._log(user, identifier, 'otp', ip, user_agent, True)
        return {'status': 'success', 'user': user, 'tokens': tokens}


class UserService:
    """All business logic + DB writes for User administration."""

    @staticmethod
    def _sync_roles(user: User, roles) -> None:
        """Make the user's active role assignments exactly match ``roles``. """
        today = date.today()
        desired = {r.id for r in roles}
        existing = {ur.role_id: ur for ur in user.user_roles.all()}

        for role_id, ur in existing.items():
            should_be_active = role_id in desired
            if ur.is_active != should_be_active:
                ur.is_active = should_be_active
                ur.save(update_fields=['is_active'])

        for role in roles:
            if role.id not in existing:
                UserRole.objects.create(user=user, role=role, effective_from=today)

    @classmethod
    @transaction.atomic
    def create_user(cls, data: dict, actor=None) -> User:
        password = data.pop('password', None)
        roles = data.pop('role_ids', None)

        user = User(**data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()

        if roles is not None:
            cls._sync_roles(user, roles)

        AuditService.log(
            action='create',
            entity_type='user',
            entity_id=user.id,
            user=actor,
            changes={
                'email': user.email,
                'mobile': user.mobile,
                'employee_id': user.employee_id,
                'roles': [r.code for r in (roles or [])],
            },
        )
        return user

    @classmethod
    @transaction.atomic
    def update_user(cls, user: User, data: dict, actor=None) -> User:
        password = data.pop('password', None)
        roles = data.pop('role_ids', None)

        changed = []
        for attr, val in data.items():
            if getattr(user, attr) != val:
                changed.append(attr)
            setattr(user, attr, val)
        if password:
            user.set_password(password)
            changed.append('password')
        user.save()

        if roles is not None:
            cls._sync_roles(user, roles)
            changed.append('roles')

        AuditService.log(
            action='update',
            entity_type='user',
            entity_id=user.id,
            user=actor,
            changes={'fields': changed},
        )
        return user

    @staticmethod
    @transaction.atomic
    def deactivate_user(user: User, actor=None) -> None:
        user.is_active = False
        user.save(update_fields=['is_active'])
        AuditService.log(
            action='delete',
            entity_type='user',
            entity_id=user.id,
            user=actor,
            changes={'is_active': False},
        )

    @staticmethod
    @transaction.atomic
    def reactivate_user(user: User, actor=None) -> None:
        user.is_active = True
        user.save(update_fields=['is_active'])
        AuditService.log(
            action='reactivate',
            entity_type='user',
            entity_id=user.id,
            user=actor,
            changes={'is_active': True},
        )

    @classmethod
    @transaction.atomic
    def bulk_assign_roles(cls, user_ids, role_codes, actor=None, mode: str = 'add') -> dict:
        """Assign roles to many users at once. All-or-nothing."""

        roles = list(Role.objects.filter(code__in=role_codes, is_active=True))
        found_codes = {r.code for r in roles}
        missing = [c for c in role_codes if c not in found_codes]
        if missing:
            transaction.set_rollback(True)
            return {
                'status': 'validation_failed',
                'errors': [{'id': 0, 'errors': [f'Role codes not found: {missing}.']}],
            }

        users = list(User.objects.filter(pk__in=user_ids))
        found_users = {u.pk for u in users}
        errors = [
            {'id': uid, 'errors': ['User not found.']}
            for uid in user_ids if uid not in found_users
        ]
        if errors:
            transaction.set_rollback(True)
            return {'status': 'validation_failed', 'errors': errors}

        for user in users:
            if mode == 'replace':
                cls._sync_roles(user, roles)
            else:
                by_id = {r.id: r for r in roles}
                active_ids = {ur.role_id for ur in user.user_roles.filter(is_active=True)}
                for existing in Role.objects.filter(id__in=active_ids):
                    by_id.setdefault(existing.id, existing)
                cls._sync_roles(user, list(by_id.values()))

            AuditService.log(
                action='update',
                entity_type='user',
                entity_id=user.id,
                user=actor,
                changes={'roles_assigned': sorted(found_codes), 'mode': mode},
            )

        return {'status': 'success', 'updated': len(users)}

    @classmethod
    @transaction.atomic
    def bulk_import_users(cls, data, fmt: str, actor=None, dry_run: bool = False) -> dict:
        """Import users from CSV text or a JSON array."""
        import csv
        import io
        import json

        from apps.core.exceptions import BusinessError
        from apps.hierarchy.models import Node

        if fmt == 'csv':
            rows = list(csv.DictReader(io.StringIO(data)))
        elif fmt == 'json':
            rows = json.loads(data) if isinstance(data, str) else data
        else:
            raise BusinessError(f"Unsupported import format: '{fmt}'. Use 'csv' or 'json'.")

        def cell(row, key):
            value = row.get(key)
            return value.strip() if isinstance(value, str) else (value or '')

        role_cache: dict = {}
        entity_cache: dict = {}
        validation_errors: list[dict] = []
        normalised: list[dict] = []
        seen = {'email': set(), 'mobile': set(), 'employee_id': set()}
        seen_entities: set = set()

        for i, row in enumerate(rows, start=1):
            row_errors: list[str] = []

            first_name = cell(row, 'first_name')
            identifiers = {
                'email': cell(row, 'email') or None,
                'mobile': cell(row, 'mobile') or None,
                'employee_id': cell(row, 'employee_id') or None,
            }

            if not first_name:
                row_errors.append('first_name is required.')
            if not any(identifiers.values()):
                row_errors.append('At least one of email, mobile, or employee_id is required.')

            for field, val in identifiers.items():
                if not val:
                    continue
                if val in seen[field]:
                    row_errors.append(f'Duplicate {field} within file: {val}.')
                seen[field].add(val)
                if User.objects.filter(**{field: val}).exists():
                    row_errors.append(f'{field} already exists: {val}.')

            role_objs = []
            roles_raw = cell(row, 'roles')
            if roles_raw:
                for code in [c.strip() for c in str(roles_raw).split(',') if c.strip()]:
                    if code not in role_cache:
                        role_cache[code] = Role.objects.filter(code=code, is_active=True).first()
                    role = role_cache[code]
                    if role is None:
                        row_errors.append(f"Role code '{code}' not found.")
                    else:
                        role_objs.append(role)

            entity = None
            entity_code = cell(row, 'entity_code')
            if entity_code:
                if entity_code not in entity_cache:
                    entity_cache[entity_code] = Node.objects.filter(
                        code=entity_code, is_current=True, is_active=True
                    ).first()
                entity = entity_cache[entity_code]
                if entity is None:
                    row_errors.append(f"Node code '{entity_code}' not found.")
                elif entity_code in seen_entities:
                    row_errors.append(f'Duplicate entity_code within file: {entity_code}.')
                elif User.objects.filter(entity=entity).exists():
                    row_errors.append(
                        f"Node '{entity_code}' is already linked to another user."
                    )
                seen_entities.add(entity_code)

            if row_errors:
                validation_errors.append({'row': i, 'errors': row_errors})

            normalised.append({
                'fields': {
                    'first_name': first_name,
                    'last_name': cell(row, 'last_name'),
                    'email': identifiers['email'],
                    'mobile': identifiers['mobile'],
                    'employee_id': identifiers['employee_id'],
                    'designation': cell(row, 'designation'),
                    'department': cell(row, 'department'),
                },
                'password': cell(row, 'password') or None,
                'roles': role_objs,
                'entity': entity,
            })

        if validation_errors:
            return {'status': 'validation_failed', 'errors': validation_errors}

        if dry_run:
            return {'status': 'valid', 'rows': len(normalised), 'would_create': len(normalised)}

        created = 0
        for item in normalised:
            user = User(**item['fields'], entity=item['entity'])
            if item['password']:
                user.set_password(item['password'])
            else:
                user.set_unusable_password()
            user.save()
            cls._sync_roles(user, item['roles'])
            created += 1

        AuditService.log(
            action='bulk_import',
            entity_type='user',
            entity_id=0,
            user=actor,
            changes={'created': created},
        )
        return {'status': 'success', 'created': created}


class ApiKeyService:
    """Issue / revoke machine credentials. The plaintext key is returned exactly
    once from ``issue`` — only its sha256 is stored."""

    @staticmethod
    @transaction.atomic
    def issue(name: str, user: User, expires_at=None, actor=None) -> tuple[APIKey, str]:
        import hashlib

        prefix = secrets.token_hex(6)  # 12 chars, the lookup handle
        secret = secrets.token_urlsafe(32)
        key = APIKey.objects.create(
            name=name,
            key_prefix=prefix,
            hashed_key=hashlib.sha256(secret.encode()).hexdigest(),
            user=user,
            expires_at=expires_at,
        )
        AuditService.log(
            action='create',
            entity_type='api_key',
            entity_id=key.id,
            user=actor,
            changes={'name': name, 'key_prefix': prefix, 'service_user_id': user.id},
        )
        return key, f'{prefix}.{secret}'

    @staticmethod
    @transaction.atomic
    def revoke(key: APIKey, actor=None) -> None:
        key.is_active = False
        key.save(update_fields=['is_active', 'updated_at'])
        AuditService.log(
            action='delete',
            entity_type='api_key',
            entity_id=key.id,
            user=actor,
            changes={'key_prefix': key.key_prefix, 'revoked': True},
        )


class RoleService:
    """All business logic + DB writes for Role administration."""

    @staticmethod
    def _validate_permissions(perms: dict) -> None:
        """ final_payout and report_payout are always restricted to individual access.
        Managers may see team achievements, but never team payout data. Invalid
        team/subtree grants are rejected when assigned and safely downgraded during
        permission resolution (`core.permissions.highest_level`).
        """
        from .permission_catalog import CONFIDENTIAL_RESOURCES, RESOURCE_LEVELS

        errors = []
        for code, level in (perms or {}).items():
            if code in CONFIDENTIAL_RESOURCES and level not in RESOURCE_LEVELS[code]:
                allowed = ', '.join(lvl for lvl in RESOURCE_LEVELS[code] if lvl != 'none')
                errors.append(
                    f'"{code}" is payout-confidential and cannot be granted at level '
                    f'"{level}". Allowed: {allowed}.'
                )
        if errors:
            raise BusinessError(' '.join(errors))

    @staticmethod
    @transaction.atomic
    def create_role(data: dict, actor=None) -> Role:
        RoleService._validate_permissions(data.get('permissions'))
        role = Role.objects.create(**data)
        AuditService.log(
            action='create',
            entity_type='role',
            entity_id=role.id,
            user=actor,
            changes={'code': role.code, 'name': role.name},
        )
        return role

    @staticmethod
    @transaction.atomic
    def update_role(role: Role, data: dict, actor=None) -> Role:
        if 'permissions' in data:
            RoleService._validate_permissions(data['permissions'])
        changed = []
        for attr, val in data.items():
            if getattr(role, attr) != val:
                changed.append(attr)
            setattr(role, attr, val)
        role.save()
        AuditService.log(
            action='update',
            entity_type='role',
            entity_id=role.id,
            user=actor,
            changes={'fields': changed},
        )
        return role

    @staticmethod
    @transaction.atomic
    def delete_role(role: Role, actor=None) -> None:
        from rest_framework.exceptions import PermissionDenied

        if role.is_system_role:
            raise PermissionDenied('System roles cannot be deleted.')
        role_id, code = role.id, role.code
        role.delete()
        AuditService.log(
            action='delete',
            entity_type='role',
            entity_id=role_id,
            user=actor,
            changes={'code': code},
        )
