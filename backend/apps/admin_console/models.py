from django.db import models

from apps.core.models import BaseModel


class SystemSetting(BaseModel):
    """A single configurable platform setting. The 'generic platform' promise:
    TDS rates, fiscal calendar, rounding, currency, and report branding are
    records here — never hardcoded. Change history is captured in AuditLog
    (every set() writes an audit entry), so a versioned mixin isn't needed."""

    class Category(models.TextChoices):
        FINANCIAL = 'financial', 'Financial'
        TDS = 'tds', 'TDS'
        LOCALE = 'locale', 'Locale'
        BRANDING = 'branding', 'Branding'
        SECURITY = 'security', 'Security'
        FEATURE = 'feature', 'Feature'

    key = models.CharField(max_length=80, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    value = models.JSONField()
    value_type = models.CharField(max_length=20, default='string')  # number|string|bool|json
    description = models.CharField(max_length=255, blank=True, default='')
    is_sensitive = models.BooleanField(default=False)

    class Meta:
        db_table = 'admin_systemsetting'
        ordering = ['category', 'key']

    def __str__(self):
        return f'{self.key}={self.value}'


class FeatureFlag(BaseModel):
    """Toggle a capability on/off, optionally for a role or entity type only."""

    class Scope(models.TextChoices):
        GLOBAL = 'global', 'Global'
        ROLE = 'role', 'Role'
        ENTITY_TYPE = 'entity_type', 'Node Type'

    code = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True, default='')
    is_enabled = models.BooleanField(default=False)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.GLOBAL)
    scope_value = models.CharField(max_length=60, blank=True, default='')

    class Meta:
        db_table = 'admin_featureflag'
        ordering = ['code']

    def __str__(self):
        return f'{self.code}={"on" if self.is_enabled else "off"}'
