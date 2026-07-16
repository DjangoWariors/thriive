"""MasterDataService — all business logic + DB writes for SKU / SKUGroup."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.audit.services import AuditService
from apps.core.exceptions import BusinessError

from .models import SKU, SKUGroup, UOMConversion

# CSV columns recognised by the bulk importer. 'code' is the upsert key.
_CSV_FIELDS = ('code', 'name', 'brand', 'category', 'sub_category', 'mrp', 'is_focus', 'is_npi')
_TRUE_VALUES = {'true', '1', 'yes', 'y', 't'}


def _to_bool(value) -> bool:
    return str(value).strip().lower() in _TRUE_VALUES


def _to_decimal(value):
    raw = str(value).strip()
    if raw == '':
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        raise BusinessError(f'Invalid MRP value: "{value}"')


class MasterDataService:

    @staticmethod
    def get_facets() -> dict:
        """Distinct non-empty brands and categories across active SKUs, for filter dropdowns.
        Independent of pagination so every value is offered, not just the current page's."""
        brands = (
            SKU.objects.filter(is_active=True).exclude(brand='')
            .values_list('brand', flat=True).distinct().order_by('brand')
        )
        categories = (
            SKU.objects.filter(is_active=True).exclude(category='')
            .values_list('category', flat=True).distinct().order_by('category')
        )
        return {'brands': list(brands), 'categories': list(categories)}

    @staticmethod
    def preview_group(filter_type: str, filter_rules: dict | None = None,
                      sku_ids: list[int] | None = None):
        """Resolve an *unsaved* group definition to a queryset of active SKUs so the builder
        preview is backend-authoritative. Mirrors ``SKUGroup.get_skus`` without a saved row."""
        if filter_type == SKUGroup.FILTER_RULE:
            return SKUGroup.resolve_rule(filter_rules or {})
        return SKU.objects.filter(is_active=True, id__in=sku_ids or []).order_by('code')

    @staticmethod
    def convert_to_base(sku_code: str, uom: str, quantity) -> Decimal:
        """Normalise ``quantity`` (in ``uom``) to the base unit. SKU-specific conversion wins
        over a global one; with no conversion configured the quantity passes through unchanged."""
        qty = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity or 0))
        if not uom:
            return qty
        conv = (
            UOMConversion.objects.filter(sku_code=sku_code, from_uom=uom, is_active=True).first()
            or UOMConversion.objects.filter(sku_code='', from_uom=uom, is_active=True).first()
        )
        return qty * conv.factor if conv else qty

    @staticmethod
    @transaction.atomic
    def create_sku(data: dict, actor=None) -> SKU:
        code = data.get('code')
        if code and SKU.objects.filter(code=code).exists():
            raise BusinessError(f'SKU with code "{code}" already exists.')
        sku = SKU.objects.create(**data)
        AuditService.log('create', 'sku', sku.id, actor, {'code': sku.code, 'name': sku.name})
        return sku

    @staticmethod
    @transaction.atomic
    def update_sku(sku: SKU, data: dict, actor=None) -> SKU:
        changed = []
        for attr, val in data.items():
            if getattr(sku, attr, None) != val:
                changed.append(attr)
            setattr(sku, attr, val)
        sku.save()
        AuditService.log('update', 'sku', sku.id, actor, {'fields': changed})
        return sku

    @staticmethod
    @transaction.atomic
    def deactivate_sku(sku: SKU, actor=None) -> None:
        sku.is_active = False
        sku.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'sku', sku.id, actor, {'is_active': False})

    @staticmethod
    @transaction.atomic
    def bulk_import_skus(csv_text: str, actor=None) -> dict:
        """Upsert SKUs from CSV text, keyed on ``code``.

        Returns {created, updated, errors:[{row, error}]}. Validates every row first;
        if any row is invalid nothing is written (all-or-nothing).
        """
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise BusinessError('CSV is empty or has no header row.')

        header = {h.strip() for h in reader.fieldnames}
        if 'code' not in header:
            raise BusinessError('CSV must include a "code" column.')

        parsed: list[dict] = []
        errors: list[dict] = []

        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                   for k, v in raw.items()}
            code = (row.get('code') or '').strip()
            if not code:
                errors.append({'row': i, 'error': 'Missing code.'})
                continue
            if not (row.get('name') or '').strip():
                errors.append({'row': i, 'error': 'Missing name.'})
                continue
            try:
                fields = {
                    'name': row.get('name', '').strip(),
                    'brand': (row.get('brand') or '').strip(),
                    'category': (row.get('category') or '').strip(),
                    'sub_category': (row.get('sub_category') or '').strip(),
                    'mrp': _to_decimal(row.get('mrp', '')),
                    'is_focus': _to_bool(row.get('is_focus', '')),
                    'is_npi': _to_bool(row.get('is_npi', '')),
                }
            except BusinessError as exc:
                errors.append({'row': i, 'error': str(exc)})
                continue
            # Any column beyond the recognised set becomes a custom attribute. Only set
            # `attributes` when at least one extra column carries a value, so a plain
            # import never wipes attributes on an existing SKU.
            extra = {k: v for k, v in row.items()
                     if k and k not in _CSV_FIELDS and (v or '').strip() != ''}
            if extra:
                fields['attributes'] = extra
            parsed.append({'code': code, 'fields': fields})

        if errors:
            return {'status': 'validation_failed', 'created': 0, 'updated': 0, 'errors': errors}

        created = updated = 0
        for item in parsed:
            sku, was_created = SKU.objects.update_or_create(
                code=item['code'],
                defaults={**item['fields'], 'is_active': True},
            )
            created += int(was_created)
            updated += int(not was_created)

        AuditService.log(
            'bulk_import', 'sku', 0, actor,
            {'created': created, 'updated': updated, 'total': len(parsed)},
        )
        return {'status': 'success', 'created': created, 'updated': updated, 'errors': []}


    @staticmethod
    @transaction.atomic
    def create_sku_group(data: dict, actor=None) -> SKUGroup:
        skus = data.pop('skus', None)
        code = data.get('code')
        if code and SKUGroup.objects.filter(code=code).exists():
            raise BusinessError(f'SKU group with code "{code}" already exists.')
        group = SKUGroup.objects.create(**data)
        if skus is not None and group.filter_type == SKUGroup.FILTER_EXPLICIT:
            group.skus.set(skus)
        AuditService.log(
            'create', 'sku_group', group.id, actor,
            {'code': group.code, 'filter_type': group.filter_type},
        )
        return group

    @staticmethod
    @transaction.atomic
    def update_sku_group(group: SKUGroup, data: dict, actor=None) -> SKUGroup:
        skus = data.pop('skus', None)
        changed = []
        for attr, val in data.items():
            if getattr(group, attr, None) != val:
                changed.append(attr)
            setattr(group, attr, val)
        group.save()
        if skus is not None and group.filter_type == SKUGroup.FILTER_EXPLICIT:
            group.skus.set(skus)
            changed.append('skus')
        AuditService.log('update', 'sku_group', group.id, actor, {'fields': changed})
        return group

    @staticmethod
    @transaction.atomic
    def deactivate_sku_group(group: SKUGroup, actor=None) -> None:
        group.is_active = False
        group.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'sku_group', group.id, actor, {'is_active': False})

    @staticmethod
    @transaction.atomic
    def create_uom_conversion(data: dict, actor=None) -> UOMConversion:
        sku_code = data.get('sku_code', '')
        from_uom = data.get('from_uom')
        if UOMConversion.objects.filter(sku_code=sku_code, from_uom=from_uom).exists():
            scope = sku_code or 'global'
            raise BusinessError(f'A conversion for "{from_uom}" ({scope}) already exists.')
        conv = UOMConversion.objects.create(**data)
        AuditService.log(
            'create', 'uom_conversion', conv.id, actor,
            {'sku_code': conv.sku_code, 'from_uom': conv.from_uom, 'factor': str(conv.factor)},
        )
        return conv

    @staticmethod
    @transaction.atomic
    def update_uom_conversion(conv: UOMConversion, data: dict, actor=None) -> UOMConversion:
        changed = []
        for attr, val in data.items():
            if getattr(conv, attr, None) != val:
                changed.append(attr)
            setattr(conv, attr, val)
        conv.save()
        AuditService.log('update', 'uom_conversion', conv.id, actor, {'fields': changed})
        return conv

    @staticmethod
    @transaction.atomic
    def deactivate_uom_conversion(conv: UOMConversion, actor=None) -> None:
        conv.is_active = False
        conv.save(update_fields=['is_active', 'updated_at'])
        AuditService.log('delete', 'uom_conversion', conv.id, actor, {'is_active': False})
