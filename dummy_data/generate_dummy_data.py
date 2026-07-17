"""Regenerate the dummy-data CSVs from the live dev DB.

Node ids change on every re-seed, and the sales CSV needs numeric
``attributed_node_id`` values — so these files are generated, not hand-written.
Re-run after any ``seed_haleon --reset``:

    cd backend
    venv\\Scripts\\python.exe manage.py shell < ..\\dummy_data\\generate_dummy_data.py

Writes four files next to this script (see dummy_data/README.md for the flow):
    sales_history_aug2025.csv  LY history -> baselines + contribution splits for an Aug-2026 plan
    sales_actuals_jul2026.csv  extra July MTD sales -> move this month's achievements on recompute
    sales_actuals_aug2026.csv  August sales -> actuals against the August targets (compute from Aug 1)
    targets_aug2026_india.csv  India-level plan-less targets (API upload; no UI screen for this one)
"""
import csv
from pathlib import Path

from django.conf import settings

from apps.hierarchy.models import GeographyNode

# Anchor on the repo layout (backend/ -> repo root -> dummy_data), not __file__:
# under `manage.py shell` this code runs via exec and __file__ is unreliable.
OUT = Path(settings.BASE_DIR).parent / 'dummy_data'

# GT sales attribute at towns; MT (no towns in this world) at the MT districts.
towns = list(GeographyNode.objects.filter(level='town', is_active=True).order_by('code')
             .values('id', 'code', 'name'))
mt_districts = list(GeographyNode.objects.filter(level='district', code__contains='_MT_', is_active=True)
                    .order_by('code').values('id', 'code', 'name'))
outlets = list(GeographyNode.objects.filter(level='outlet', is_active=True).order_by('code')
               .values('id', 'code', 'name'))
if not towns:
    raise SystemExit('No towns found — is the seed loaded?')

SKUS = ['ENO-REG-5G', 'SEN-FRESH-75', 'CRO-ADV-15', 'SEN-WHITE-75']  # core + focus + one NPI
TXN_COLS = ['attributed_node_id', 'transaction_date', 'transaction_type', 'transaction_level',
            'channel_code', 'sku_code', 'outlet_code', 'bill_ref', 'gross_amount',
            'discount_amount', 'tax_amount', 'net_amount', 'quantity', 'uom', 'source',
            'external_ref']


def txn_row(ref, node, date, sku_i, weight, channel, outlet_code='', kind='sale'):
    """Deterministic amounts: ``weight`` skews nodes apart so contribution splits are uneven."""
    gross = 800 + 350 * weight + 120 * sku_i
    discount = round(gross * 0.05)
    tax = round(gross * 0.12)
    return {
        'attributed_node_id': node['id'], 'transaction_date': date,
        'transaction_type': kind, 'transaction_level': 'secondary',
        'channel_code': channel, 'sku_code': SKUS[sku_i],
        'outlet_code': outlet_code, 'bill_ref': f'DUMMY-BILL-{ref}',
        'gross_amount': gross, 'discount_amount': discount, 'tax_amount': tax,
        'net_amount': gross - discount, 'quantity': 5 + weight + sku_i,
        'uom': 'unit', 'source': 'manual_entry', 'external_ref': f'DUMMY-{ref}',
    }


def write(name, cols, rows):
    with open(OUT / name, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f'  {name}: {len(rows)} rows')


# ── 1. LY history (Aug 2025): feeds the baseline suggestion + contribution split
#      of a plan you create for Aug 2026 ──────────────────────────────────────
rows, ref = [], 0
for w_, node in enumerate(towns):
    for sku_i in range(len(SKUS)):
        for day in (4, 11, 19, 26):
            ref += 1
            rows.append(txn_row(f'H{ref:04d}', node, f'2025-08-{day:02d}', sku_i, w_, 'GT'))
for w_, node in enumerate(mt_districts):
    for sku_i in range(len(SKUS)):
        for day in (6, 14, 22, 28):
            ref += 1
            rows.append(txn_row(f'H{ref:04d}', node, f'2025-08-{day:02d}', sku_i, w_ + 2, 'MT',
                                outlet_code=f'DMART-{node["code"][-3:]}-01'))
write('sales_history_aug2025.csv', TXN_COLS, rows)

# ── 2. Extra July-2026 MTD sales: recompute this month and watch achievements
#      move on the published Jul plan ─────────────────────────────────────────
rows, ref = [], 0
for w_, node in enumerate(towns):
    for sku_i in range(3):
        for day in (2, 9, 16):
            ref += 1
            rows.append(txn_row(f'A{ref:04d}', node, f'2026-07-{day:02d}', sku_i, w_, 'GT'))
for w_, node in enumerate(outlets):  # partner-owned outlet nodes get their own sales
    ref += 1
    rows.append(txn_row(f'A{ref:04d}', node, '2026-07-10', 0, w_, 'GT', outlet_code=node['code']))
ref += 1  # one return, to see returns subtract
rows.append(txn_row(f'A{ref:04d}', towns[0], '2026-07-15', 0, 1, 'GT', kind='return'))
write('sales_actuals_jul2026.csv', TXN_COLS, rows)

# ── 2b. August-2026 sales: actuals against the August targets. Attributed at
#      towns/MT districts like real sales — they roll up to the India-level
#      target. Achievement compute clips at today, so these count from Aug 1. ──
rows, ref = [], 0
for w_, node in enumerate(towns):
    for sku_i in range(len(SKUS)):
        for day in (3, 10, 18, 25):
            ref += 1
            rows.append(txn_row(f'G{ref:04d}', node, f'2026-08-{day:02d}', sku_i, w_, 'GT'))
for w_, node in enumerate(mt_districts):
    for sku_i in range(3):
        for day in (5, 13, 21):
            ref += 1
            rows.append(txn_row(f'G{ref:04d}', node, f'2026-08-{day:02d}', sku_i, w_ + 2, 'MT',
                                outlet_code=f'DMART-{node["code"][-3:]}-01'))
write('sales_actuals_aug2026.csv', TXN_COLS, rows)

# ── 3. India-level plan-less targets for Aug 2026 (the AOP trio at the nation
#      root). No UI screen: POST it to /targets/allocations/bulk/
nation = GeographyNode.objects.get(level='nation', is_active=True)
write('targets_aug2026_india.csv',
      ['period_code', 'kpi_code', 'geography_node_code', 'target_value'],
      [{'period_code': 'FY2026-M08', 'kpi_code': kpi,
        'geography_node_code': nation.code, 'target_value': value}
       for kpi, value in (('CORE_VALUE', 600000), ('FOCUS_NPI_VALUE', 150000),
                          ('EC_OVERALL', 60))])

print('Done. Files in', OUT)
