from django.db import models

from apps.core.models import BaseModel


class SKU(BaseModel):
    """A single product / stock-keeping unit."""

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=150, blank=True, default='', db_index=True)
    category = models.CharField(max_length=150, blank=True, default='', db_index=True)
    sub_category = models.CharField(max_length=150, blank=True, default='')
    mrp = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    is_focus = models.BooleanField(default=False, db_index=True)
    is_npi = models.BooleanField(default=False, db_index=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'master_data_sku'
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='sku_code_uniq'),
        ]
        indexes = [
            models.Index(fields=['brand', 'category']),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'


class SKUGroup(BaseModel):
    """A named collection of SKUs, defined either explicitly (a fixed list) or by a
    rule (a set of filter criteria evaluated against the SKU master)."""

    FILTER_EXPLICIT = 'explicit'
    FILTER_RULE = 'rule'
    FILTER_TYPE_CHOICES = [
        (FILTER_EXPLICIT, 'Explicit (fixed list)'),
        (FILTER_RULE, 'Rule (dynamic filter)'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    filter_type = models.CharField(
        max_length=20, choices=FILTER_TYPE_CHOICES, default=FILTER_EXPLICIT,
    )
    filter_rules = models.JSONField(default=dict, blank=True)
    skus = models.ManyToManyField(SKU, blank=True, related_name='groups')

    _RULE_FIELDS = ('brand', 'category', 'sub_category', 'is_focus', 'is_npi')

    class Meta:
        db_table = 'master_data_skugroup'
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='skugroup_code_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'

    @classmethod
    def resolve_rule(cls, filter_rules):
        """Resolve a rule's ``filter_rules`` to a queryset of active SKUs, independent
        of any saved group. Shared by ``get_skus`` and the unsaved-rule preview so the
        UI preview can never diverge from what the group will actually resolve to.

        Filters on the fixed master columns AND on arbitrary SKU Master attributes via
        an optional ``attributes`` map, e.g. ``{"brand": "Acme", "attributes": {"pack_size": "large"}}``.
        """
        qs = SKU.objects.filter(is_active=True)
        rules = filter_rules or {}
        for field in cls._RULE_FIELDS:
            if field in rules and rules[field] not in (None, ''):
                qs = qs.filter(**{field: rules[field]})
        for key, value in (rules.get('attributes') or {}).items():
            if value not in (None, ''):
                qs = qs.filter(**{f'attributes__{key}': value})
        return qs.order_by('code')

    def get_skus(self):
        """Resolve the group to a queryset of active SKUs."""
        if self.filter_type == self.FILTER_RULE:
            return self.resolve_rule(self.filter_rules)
        return self.skus.filter(is_active=True).order_by('code')


class UOMConversion(BaseModel):
    """Converts a sold quantity into a canonical base unit so volume KPIs can sum across
    mixed packs (cases, inners, units, kg). A case-count means nothing added to a kg-count
    until both are normalised. Conversions are looked up SKU-specific first (a case of brand
    X may hold 24 units, brand Y 12), then a global rule, else factor 1 (no-op)."""

    sku_code = models.CharField(max_length=50, blank=True, default='', db_index=True)  # blank = global
    from_uom = models.CharField(max_length=20)
    to_uom = models.CharField(max_length=20)  # the base unit
    factor = models.DecimalField(max_digits=15, decimal_places=6, default=1)

    class Meta:
        db_table = 'master_data_uomconversion'
        ordering = ['sku_code', 'from_uom']
        constraints = [
            models.UniqueConstraint(fields=['sku_code', 'from_uom'], name='uom_conv_sku_from_uniq'),
        ]

    def __str__(self):
        scope = self.sku_code or 'global'
        return f'{scope}: 1 {self.from_uom} = {self.factor} {self.to_uom}'
