"""Seed an illustrative FMCG product master so the master-data module can be exercised
end-to-end (filters, facets, SKU groups, rule preview, UOM conversions).

Idempotent: SKUs / groups / conversions are keyed and skipped if they already exist.

These are illustrative *configuration* records, not platform logic — a real client would
load their own SKU master via the bulk importer or API. They live here only to make the
platform demonstrable and to back the manual-test guide.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.master_data.models import SKU, SKUGroup, UOMConversion
from apps.master_data.services import MasterDataService

# code, name, brand, category, sub_category, mrp, is_focus, is_npi, attributes
SKUS = [
    ('ACM-SOAP-100', 'Acme Soap 100g', 'Acme', 'Personal Care', 'Soap', '35', True, False, {'pack_size': 'small'}),
    ('ACM-SOAP-150', 'Acme Soap 150g', 'Acme', 'Personal Care', 'Soap', '49', True, False, {'pack_size': 'large'}),
    ('ACM-SHMP-180', 'Acme Shampoo 180ml', 'Acme', 'Personal Care', 'Haircare', '120', False, False, {'pack_size': 'large'}),
    ('ACM-SHMP-SAC', 'Acme Shampoo Sachet', 'Acme', 'Personal Care', 'Haircare', '3', False, False, {'pack_size': 'small'}),
    ('ACM-DET-1KG', 'Acme Detergent 1kg', 'Acme', 'Home Care', 'Detergent', '110', True, False, {'pack_size': 'large'}),
    ('ACM-DET-500', 'Acme Detergent 500g', 'Acme', 'Home Care', 'Detergent', '60', False, False, {'pack_size': 'small'}),
    ('GLX-BISC-75', 'Globex Biscuits 75g', 'Globex', 'Foods', 'Biscuits', '10', False, False, {'pack_size': 'small'}),
    ('GLX-BISC-200', 'Globex Biscuits 200g', 'Globex', 'Foods', 'Biscuits', '30', True, False, {'pack_size': 'large'}),
    ('GLX-NOOD-70', 'Globex Noodles 70g', 'Globex', 'Foods', 'Noodles', '14', False, True, {'pack_size': 'small'}),
    ('GLX-JUICE-1L', 'Globex Juice 1L', 'Globex', 'Beverages', 'Juice', '99', False, True, {'pack_size': 'large'}),
    ('INI-TOOTH-100', 'Initech Toothpaste 100g', 'Initech', 'Personal Care', 'Oral Care', '55', True, False, {'pack_size': 'large'}),
    ('INI-TOOTH-NEW', 'Initech Herbal Toothpaste 100g', 'Initech', 'Personal Care', 'Oral Care', '65', True, True, {'pack_size': 'large'}),
    ('INI-FLOSS-NEW', 'Initech Dental Floss', 'Initech', 'Personal Care', 'Oral Care', '90', False, True, {}),
    ('GLX-CHOC-40', 'Globex Chocolate 40g', 'Globex', 'Foods', 'Confectionery', '20', False, False, {'pack_size': 'small'}),
]

# code, name, sku_codes (explicit list)
EXPLICIT_GROUPS = [
    ('PERSONAL_CARE_HERO', 'Personal Care Heroes',
     ['ACM-SOAP-150', 'ACM-SHMP-180', 'INI-TOOTH-100']),
]

# code, name, rule
RULE_GROUPS = [
    ('GLOBEX_FOODS', 'Globex Foods', {'brand': 'Globex', 'category': 'Foods'}),
    ('LARGE_PACKS', 'Large Packs', {'attributes': {'pack_size': 'large'}}),
]

# sku_code (blank = global), from_uom, to_uom, factor
UOM_CONVERSIONS = [
    ('', 'case', 'unit', '24'),
    ('', 'inner', 'unit', '12'),
    ('GLX-JUICE-1L', 'case', 'unit', '12'),   # juice ships 12 to a case, not 24
    ('', 'dozen', 'unit', '12'),
]


class Command(BaseCommand):
    help = 'Seed an illustrative FMCG product master (idempotent): SKUs, groups, UOM conversions.'

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_skus()
        self._seed_explicit_groups()
        self._seed_rule_groups()
        self._seed_uom()
        self.stdout.write(self.style.SUCCESS(
            f'Master data ready — {SKU.objects.count()} SKUs, '
            f'{SKUGroup.objects.count()} groups, {UOMConversion.objects.count()} conversions.'
        ))

    def _seed_skus(self):
        created = skipped = 0
        for code, name, brand, cat, sub, mrp, focus, npi, attrs in SKUS:
            if SKU.objects.filter(code=code).exists():
                skipped += 1
                continue
            MasterDataService.create_sku({
                'code': code, 'name': name, 'brand': brand, 'category': cat,
                'sub_category': sub, 'mrp': Decimal(mrp), 'is_focus': focus,
                'is_npi': npi, 'attributes': attrs,
            })
            created += 1
        self.stdout.write(f'SKUs: {created} created, {skipped} skipped.')

    def _seed_explicit_groups(self):
        for code, name, sku_codes in EXPLICIT_GROUPS:
            if SKUGroup.objects.filter(code=code).exists():
                continue
            ids = list(SKU.objects.filter(code__in=sku_codes).values_list('id', flat=True))
            MasterDataService.create_sku_group({
                'name': name, 'code': code, 'filter_type': SKUGroup.FILTER_EXPLICIT, 'skus': ids,
            })
            self.stdout.write(f'  + group {code} (explicit, {len(ids)} SKUs)')

    def _seed_rule_groups(self):
        # FOCUS / NPI rule groups are seeded by seed_fmcg_kpis; add a few more for variety.
        for code, name, rule in RULE_GROUPS:
            if SKUGroup.objects.filter(code=code).exists():
                continue
            MasterDataService.create_sku_group({
                'name': name, 'code': code, 'filter_type': SKUGroup.FILTER_RULE, 'filter_rules': rule,
            })
            self.stdout.write(f'  + group {code} (rule)')

    def _seed_uom(self):
        created = skipped = 0
        for sku_code, from_uom, to_uom, factor in UOM_CONVERSIONS:
            if UOMConversion.objects.filter(sku_code=sku_code, from_uom=from_uom).exists():
                skipped += 1
                continue
            MasterDataService.create_uom_conversion({
                'sku_code': sku_code, 'from_uom': from_uom, 'to_uom': to_uom, 'factor': Decimal(factor),
            })
            created += 1
        self.stdout.write(f'UOM conversions: {created} created, {skipped} skipped.')
