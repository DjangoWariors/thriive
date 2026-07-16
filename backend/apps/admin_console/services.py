"""SystemSetting / FeatureFlag access. The single source for configurable
financial, fiscal, locale, and branding values consumed by reports and engines."""
from decimal import Decimal

from django.core.cache import cache

from apps.admin_console.models import FeatureFlag, SystemSetting
from apps.audit.services import AuditService

_CACHE_PREFIX = 'sysset:'
_CACHE_TTL = 300

# Defaults used when a setting row is absent — keeps engines working before seeding
# and documents the platform defaults (India FY, Budget-2026 TDS rates).
_DEFAULTS = {
    'tds.194h.rate': 2,
    'tds.194h.threshold': 20000,
    'tds.194r.rate': 10,
    'tds.194r.threshold': 20000,
    'tds.no_pan_rate': 20,
    'fiscal_year_start_month': 4,
    'rounding.mode': 'half_up',
    'locale.currency': 'INR',
    'branding.color_primary': '#8B1A1A',
    'branding.company_name': 'Thriive',
    'branding.address': '',
}


class SystemSettingService:

    @staticmethod
    def get(key: str, default=None):
        cache_key = f'{_CACHE_PREFIX}{key}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        row = SystemSetting.objects.filter(key=key, is_active=True).first()
        value = row.value if row is not None else _DEFAULTS.get(key, default)
        if value is not None:
            cache.set(cache_key, value, _CACHE_TTL)
        return value

    @staticmethod
    def set(key: str, value, user, *, category=None, value_type=None,
            description=None, is_sensitive=None) -> SystemSetting:
        row = SystemSetting.objects.filter(key=key).first()
        old = row.value if row is not None else None
        if row is None:
            row = SystemSetting(key=key, category=category or SystemSetting.Category.FEATURE,
                                value=value, value_type=value_type or 'string')
        else:
            row.value = value
        if category is not None:
            row.category = category
        if value_type is not None:
            row.value_type = value_type
        if description is not None:
            row.description = description
        if is_sensitive is not None:
            row.is_sensitive = is_sensitive
        row.is_active = True
        row.save()
        cache.delete(f'{_CACHE_PREFIX}{key}')
        AuditService.log('update', 'admin_console.SystemSetting', row.pk, user,
                         {'key': key, 'old': old, 'new': value})
        return row

    # ── typed convenience reads (consumed by reports + engines) ────────────────
    @staticmethod
    def get_decimal(key: str) -> Decimal:
        return Decimal(str(SystemSettingService.get(key)))

    @staticmethod
    def get_tds_config() -> dict:
        g = SystemSettingService.get
        return {
            'h_rate': Decimal(str(g('tds.194h.rate'))),
            'h_threshold': Decimal(str(g('tds.194h.threshold'))),
            'r_rate': Decimal(str(g('tds.194r.rate'))),
            'r_threshold': Decimal(str(g('tds.194r.threshold'))),
            'no_pan_rate': Decimal(str(g('tds.no_pan_rate'))),
        }

    @staticmethod
    def get_fiscal() -> dict:
        return {'start_month': int(SystemSettingService.get('fiscal_year_start_month'))}

    @staticmethod
    def get_branding() -> dict:
        g = SystemSettingService.get
        return {
            'color_primary': g('branding.color_primary'),
            'company_name': g('branding.company_name'),
            'address': g('branding.address'),
        }


class FeatureService:

    @staticmethod
    def is_enabled(code: str, user=None) -> bool:
        # Per-client toggle hook: no core code path depends on a flag; clients
        # create flags and gate their own customisations through this check.
        flag = FeatureFlag.objects.filter(code=code, is_active=True).first()
        if flag is None or not flag.is_enabled:
            return False
        if flag.scope == FeatureFlag.Scope.GLOBAL or user is None:
            return flag.is_enabled
        if flag.scope == FeatureFlag.Scope.ENTITY_TYPE:
            ent = getattr(user, 'entity', None)
            return bool(ent and ent.entity_type.code == flag.scope_value)
        if flag.scope == FeatureFlag.Scope.ROLE:
            from apps.core.permissions import highest_level  # noqa: F401
            from apps.accounts.models import UserRole
            return UserRole.objects.filter(
                user=user, is_active=True, role__code=flag.scope_value).exists()
        return flag.is_enabled
