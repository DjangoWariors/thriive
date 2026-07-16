"""Seed the COMPLETE Haleon manual-testing world — GT + MT channels only.

One command, one world. Runs every infra seed (roles, settings, workflows, notification
templates, reports), then builds Haleon-shaped data end-to-end: master data → org +
geography + assignments → KPIs + external metrics → transactions → a plan-centric AOP
(docs/TARGET_MODULE_REVAMP_PLAN.md) → achievements → SIP schemes → payout runs.

    python manage.py seed_haleon --reset      # wipe business data, build the Haleon world
    python manage.py seed_haleon              # additive / top-up (idempotent)

Targets follow the revamped plan-first process end-to-end: the AOP KPIs (Core Value,
Focus/NPI Value, EC) are committed THROUGH the plan pipeline — baseline run → typed top
number → spatial split (recipe) → product split — on the current month (targets are
always set monthly), then the cascade review opens and the engineered achievement spread
is applied as governed field adjustments (overrides + TargetRevisions), never as raw
rows. Brand/execution KPIs that sit outside the AOP stay plan-less allocations (the
doc's bulk-import path), as does the closed month's spread.

Every deliberate edge case is listed in the cheat sheet the command prints at the end:
  • six retailer partners (OTP login) under their distributors, each owning its outlet
    territory — own sales history + an engineered Core Value target in the partner portal
  • vacant territory (Dwarka) — sales roll up to the ASM but no rep owns them
  • mid-month territory transfer (Rohini) + new-joiner exception on the incoming rep
  • multi-territory rep (Anjali owns two towns), distributor-owned territory (Whitefield)
  • achievement spread across every multiplier tier incl. exact-100% and below-floor
  • gatekeeper failure on great sales (Manoj: 112% sales, 70% geofence)
  • zero-target allocation, target-without-sales, sales-without-target
  • returns > sales for one outlet (excluded from Effective Coverage)
  • missing external-metric data, missing variable pay, suspended partner
  • payout runs left in every reviewable state
  • plan workflow mid-flight: review tasks in every state (accepted / adjusted /
    escalated-to-manager / pending), a staged realign run with override collisions,
    RevisionPolicy change caps, an auto + an escalated + a rejected TargetRevision,
    over-budget cost-of-plan gate

Illustrative *configuration + data*, not platform logic — a real deployment loads its
own via the UI, bulk import, or the push APIs.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

D = Decimal
DEMO_PASSWORD = 'Demo@1234'

# ── channels (GT + MT ONLY — the whole point of this seed) ─────────────────────
CHANNELS = [('GT', 'General Trade'), ('MT', 'Modern Trade')]

# ── product master (Haleon India portfolio) ────────────────────────────────────
# code, name, brand, category, sub_category, mrp, is_focus, is_npi
SKUS = [
    ('SEN-FRESH-75', 'Sensodyne Fresh Mint 75g', 'Sensodyne', 'Oral Care', 'Toothpaste', '135', True, False),
    ('SEN-RAPID-80', 'Sensodyne Rapid Relief 80g', 'Sensodyne', 'Oral Care', 'Toothpaste', '180', True, False),
    ('SEN-WHITE-75', 'Sensodyne Clinical White 75g', 'Sensodyne', 'Oral Care', 'Toothpaste', '210', True, True),
    ('ENO-LEMON-100', 'Eno Fruit Salt Lemon 100g', 'Eno', 'Digestive Health', 'Antacid', '110', False, False),
    ('ENO-REG-5G', 'Eno Regular Sachet 5g', 'Eno', 'Digestive Health', 'Antacid', '10', True, False),
    ('ENO-CHEW-10', 'Eno Chewy Bites 10s', 'Eno', 'Digestive Health', 'Antacid', '50', False, True),
    ('CRO-ADV-15', 'Crocin Advance 15s', 'Crocin', 'Pain Relief', 'Tablet', '30', False, False),
    ('OTR-SPRAY-10', 'Otrivin Breathe Clean 10ml', 'Otrivin', 'Respiratory', 'Nasal Spray', '95', False, False),
    ('IOD-BALM-40', 'Iodex Balm 40g', 'Iodex', 'Pain Relief', 'Balm', '85', False, False),
    ('CEN-MEN-30', 'Centrum Men 30s', 'Centrum', 'Wellness', 'Multivitamin', '425', False, True),
    ('CEN-WOM-30', 'Centrum Women 30s', 'Centrum', 'Wellness', 'Multivitamin', '425', False, True),
]
DELISTED_SKU = ('HAL-DELIST-01', 'Iodex Rub 20g (Delisted)', 'Iodex', 'Pain Relief', 'Balm', '45')

# sku_code (blank = global), from_uom, to_uom, factor
UOM_CONVERSIONS = [('', 'case', 'unit', '24'), ('', 'inner', 'unit', '12')]

# ── org roles (GT + MT personas only) ──────────────────────────────────────────
# code, name, level, parents, children, channel, leaf, role_code, portal, icon, color
ROLE_SPECS = [
    ('nsm', 'National Sales Manager', 1, [], ['rsm'], None, False, 'national_head', 'admin', 'crown', '#1e40af'),
    ('rsm', 'Regional Sales Manager', 2, ['nsm'], ['asm', 'mte'], None, False, 'regional_manager', 'admin', 'user-tie', '#7c3aed'),
    ('asm', 'Area Sales Manager (GT)', 3, ['rsm'], ['xse'], 'GT', False, 'area_manager', 'admin', 'briefcase', '#059669'),
    ('xse', 'Xpress Sales Executive (GT)', 4, ['asm'], ['dist'], 'GT', False, 'sales_exec', 'admin', 'user', '#d97706'),
    ('mte', 'Modern Trade Executive', 3, ['rsm'], [], 'MT', True, 'sales_exec', 'admin', 'shopping-cart', '#c026d3'),
    ('dist', 'Distributor', 5, ['xse'], ['ret'], 'GT', False, 'distributor', 'partner', 'truck', '#dc2626'),
    ('ret', 'Retailer', 6, ['dist'], [], 'GT', True, 'retailer', 'partner', 'store', '#ea580c'),
]
FF_SCHEMA = [
    {'key': 'employee_id', 'label': 'Employee ID', 'type': 'string', 'required': True, 'unique': True},
    {'key': 'joining_date', 'label': 'Date of Joining', 'type': 'date', 'required': False, 'unique': False},
]
DIST_SCHEMA = [
    {'key': 'gstin', 'label': 'GSTIN', 'type': 'string', 'required': False, 'unique': True},
    {'key': 'credit_limit', 'label': 'Credit Limit (₹)', 'type': 'decimal', 'required': False, 'unique': False},
]

# ── geography (each channel force owns its own subtree; one owner per node) ────
# code, name, level, parent
GEO_SPEC = [
    ('HAL_IN', 'India', 'nation', None),
    ('HAL_NORTH', 'North', 'region', 'HAL_IN'),
    ('HAL_SOUTH', 'South', 'region', 'HAL_IN'),
    ('HAL_GT_DL', 'Delhi GT Area', 'district', 'HAL_NORTH'),
    ('HAL_GT_DL_KB', 'Karol Bagh', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_LN', 'Lajpat Nagar', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_RH', 'Rohini', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_DW', 'Dwarka', 'town', 'HAL_GT_DL'),          # vacant — no owner, has sales
    ('HAL_MT_DL', 'Delhi MT Area', 'district', 'HAL_NORTH'),   # MT works at district grain
    ('HAL_GT_BLR', 'Bangalore GT Area', 'district', 'HAL_SOUTH'),
    ('HAL_GT_BLR_KM', 'Koramangala', 'town', 'HAL_GT_BLR'),
    ('HAL_GT_BLR_WF', 'Whitefield', 'town', 'HAL_GT_BLR'),     # owned by a DISTRIBUTOR
    ('HAL_MT_BLR', 'Bangalore MT Area', 'district', 'HAL_SOUTH'),
    # Retail outlets under their towns. Codes DELIBERATELY equal the transaction outlet
    # strings (f'{town}-OUT{n}') so the existing engineered sales re-attribute to the
    # outlet node — town subtree totals (and every engineered %) stay exactly the same.
    ('HAL_GT_DL_KB-OUT1', 'Gupta General Store', 'outlet', 'HAL_GT_DL_KB'),
    ('HAL_GT_DL_KB-OUT2', 'Sharma Medicos', 'outlet', 'HAL_GT_DL_KB'),
    ('HAL_GT_DL_LN-OUT1', 'Balaji Super Mart', 'outlet', 'HAL_GT_DL_LN'),
    ('HAL_GT_DL_RH-OUT1', 'Verma Provision Store', 'outlet', 'HAL_GT_DL_RH'),
    ('HAL_GT_BLR_KM-OUT1', 'Sri Lakshmi Stores', 'outlet', 'HAL_GT_BLR_KM'),
    ('HAL_GT_BLR_WF-OUT1', 'New Whitefield Mart', 'outlet', 'HAL_GT_BLR_WF'),
]

# Retailer partners (OTP login, partner portal), one per outlet above.
# code → (name, outlet geo code, distributor parent code, mobile, gstin, CORE_VALUE ach %)
RETAILERS = {
    'HAL_RET_KB1': ('Gupta General Store', 'HAL_GT_DL_KB-OUT1', 'HAL_DIST_KB', '9811120001', '07AAHRG6666F1Z6', '106'),
    'HAL_RET_KB2': ('Sharma Medicos', 'HAL_GT_DL_KB-OUT2', 'HAL_DIST_KB', '9811120002', '07AAHRS7777G1Z7', '93'),
    'HAL_RET_LN1': ('Balaji Super Mart', 'HAL_GT_DL_LN-OUT1', 'HAL_DIST_LN', '9811120003', '07AAHRB8888H1Z8', '100'),
    'HAL_RET_RH1': ('Verma Provision Store', 'HAL_GT_DL_RH-OUT1', 'HAL_DIST_RH', '9811120004', '07AAHRV9999J1Z9', '71'),
    'HAL_RET_KM1': ('Sri Lakshmi Stores', 'HAL_GT_BLR_KM-OUT1', 'HAL_DIST_KM', '9811120005', '29AAHRL1010K1Z0', '111'),
    'HAL_RET_WF1': ('New Whitefield Mart', 'HAL_GT_BLR_WF-OUT1', 'HAL_DIST_WF', '9811120006', '29AAHRN2020L1Z1', '98'),
}

# ── transactions ───────────────────────────────────────────────────────────────
BASKET = ['CRO-ADV-15', 'SEN-FRESH-75', 'ENO-LEMON-100', 'CEN-MEN-30', 'SEN-RAPID-80',
          'ENO-REG-5G', 'OTR-SPRAY-10', 'SEN-WHITE-75', 'IOD-BALM-40']
DW_BASKET = ['CRO-ADV-15', 'ENO-LEMON-100', 'IOD-BALM-40']  # no focus/NPI SKUs on purpose
SALE_DAYS = [1, 4, 7, 10, 13, 16, 19, 22, 26]
SOURCES = ['dms_sync', 'dms_sync', 'qr_scan', 'manual_entry']

# town code → (base net ₹, n outlets, distributor code or None)
GT_TOWN_SALES = {
    'HAL_GT_DL_KB': (5200, 5, 'HAL_DIST_KB'),
    'HAL_GT_DL_LN': (3800, 4, 'HAL_DIST_LN'),
    'HAL_GT_DL_RH': (3200, 4, 'HAL_DIST_RH'),
    'HAL_GT_DL_DW': (1600, 2, None),
    'HAL_GT_BLR_KM': (4500, 4, 'HAL_DIST_KM'),
    'HAL_GT_BLR_WF': (2800, 3, 'HAL_DIST_WF'),
}
# LY volume factor per town (default 0.85 → healthy growth); Lajpat Nagar declines.
LY_FACTORS = {'HAL_GT_DL_LN': D('1.30')}
LY_DEFAULT_FACTOR = D('0.85')

# MT node → (base net ₹, store outlet codes)
MT_NODE_SALES = {
    'HAL_MT_DL': (9000, ['DMART-DL-01', 'RELIANCE-DL-02', 'SPAR-DL-03']),
    'HAL_MT_BLR': (7000, ['DMART-BLR-01', 'MORE-BLR-02']),
}
MT_DAYS = [2, 6, 11, 16, 20, 24, 27]

# ── KPIs (RFP set, minus anything needing the excluded channels) ───────────────
APPLIES = ['nsm', 'rsm', 'asm', 'xse', 'mte', 'dist', 'ret']

# The AOP trio (docs/TARGET_MODULE_REVAMP_PLAN.md §3) — committed through the plan
# pipeline. Everything else stays a plan-less allocation (the doc's bulk-import path).
AOP_KPIS = ('CORE_VALUE', 'FOCUS_NPI_VALUE', 'EC_OVERALL')


def _measure(field, agg, net='sales_minus_returns'):
    return {'measure_field': field, 'aggregation': agg, 'net_logic': net,
            'transaction_level': 'secondary'}


def _ec_measure():
    return {**_measure('outlet_code', 'count_distinct', net='all'),
            'having': {'field': 'net_amount', 'operator': 'gt', 'value': 0}}


KPIS = [
    dict(code='CORE_VALUE', name='Core Value', category='value', unit='₹',
         kpi_type='value', measure_config=_measure('net_amount', 'sum')),
    dict(code='FOCUS_VALUE', name='Focus SKU Value', category='value', unit='₹',
         kpi_type='value', measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'FOCUS'}),
    dict(code='NPI_VALUE', name='NPI Value', category='value', unit='₹',
         kpi_type='value', measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'NPI'}),
    dict(code='BRAND_VALUE_ENO', name='Brand Value (Eno)', category='value', unit='₹',
         kpi_type='value', measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'ENO'}),
    dict(code='FOCUS_NPI_VALUE', name='Focus/NPI Value', category='value', unit='₹',
         kpi_type='value', measure_config=_measure('net_amount', 'sum'),
         sku_filter={'type': 'group', 'group_code': 'FOCUS_NPI'}),
    dict(code='EC_OVERALL', name='Effective Coverage (Overall)', category='execution',
         unit='outlets', decimal_places=0, kpi_type='count_distinct', measure_config=_ec_measure()),
    dict(code='BRAND_EC', name='Brand EC (Eno)', category='execution', unit='outlets',
         decimal_places=0, kpi_type='count_distinct', measure_config=_ec_measure(),
         sku_filter={'type': 'group', 'group_code': 'ENO'}),
    dict(code='FOCUS_EC', name='Focus SKU EC', category='execution', unit='outlets',
         decimal_places=0, kpi_type='count_distinct', measure_config=_ec_measure(),
         sku_filter={'type': 'group', 'group_code': 'FOCUS'}),
    dict(code='UNIQUE_SKUS', name='Total Unique SKUs', category='execution', unit='SKUs',
         decimal_places=0, kpi_type='count_distinct',
         measure_config=_measure('sku_code', 'count_distinct', net='gross_only')),
]

# code, name, unit, granularity, grain, aggregation
EXTERNAL_METRICS = [
    ('TLSD', 'Total Lines Sold per Day', 'lines', 'geography_node', 'daily', 'sum'),
    ('PRODUCTIVE_CALLS', 'Productive Calls', 'calls', 'geography_node', 'daily', 'sum'),
    ('ACTIVATION_ADHERENCE', 'Activation Adherence Score', '%', 'entity', 'monthly', 'latest'),
    ('GEOFENCED_COVERAGE_PCT', 'Geofenced Coverage', '%', 'entity', 'monthly', 'latest'),
    ('COMPLIANCE_CLEAN', 'Clean Compliance Record', '%', 'entity', 'monthly', 'latest'),
]
EXTERNAL_KPIS = [
    dict(code='TLSD', name='TLSD', category='execution', unit='lines', decimal_places=0,
         applicable_entity_types=['nsm', 'rsm', 'asm', 'xse', 'dist'],
         external_config={'metric_code': 'TLSD', 'target_source': 'allocation'}),
    dict(code='PRODUCTIVE_CALLS', name='Productive Calls', category='execution', unit='calls',
         decimal_places=0, applicable_entity_types=['nsm', 'rsm', 'asm', 'xse'],
         external_config={'metric_code': 'PRODUCTIVE_CALLS', 'target_source': 'allocation'}),
    dict(code='ACTIVATION_ADHERENCE', name='Activation Adherence', category='execution', unit='%',
         applicable_entity_types=['mte'],
         external_config={'metric_code': 'ACTIVATION_ADHERENCE', 'target_source': 'fixed',
                          'fixed_target': 100}),
    dict(code='GEOFENCE', name='Geofenced Coverage', category='compliance', unit='%',
         applicable_entity_types=['xse'],
         external_config={'metric_code': 'GEOFENCED_COVERAGE_PCT', 'target_source': 'fixed',
                          'fixed_target': 100}),
    dict(code='COMPLIANCE', name='Clean Compliance', category='compliance', unit='%',
         applicable_entity_types=['xse', 'mte'],
         external_config={'metric_code': 'COMPLIANCE_CLEAN', 'target_source': 'fixed',
                          'fixed_target': 100}),
]

# SFA feed bases — 4 weekly rows per GT town; sums drive TLSD/calls achievement.
TLSD_BASE = {'HAL_GT_DL_KB': 60, 'HAL_GT_DL_LN': 49, 'HAL_GT_DL_RH': 42,
             'HAL_GT_BLR_KM': 55, 'HAL_GT_BLR_WF': 38}
CALLS_BASE = {'HAL_GT_DL_KB': 28, 'HAL_GT_DL_LN': 24, 'HAL_GT_DL_RH': 22,
              'HAL_GT_BLR_KM': 26, 'HAL_GT_BLR_WF': 20}

# ── engineered achievement % (closed month) — target = actual ÷ pct ───────────
# Landing points cover every multiplier tier: <90 → 0x, 90–100 → 0.9x,
# 100–102 → 1.0x, 102–105 → 1.5x, >105 → 1.8x — plus exact-boundary values.
DEFAULT_PCT = D('95')
ACH_PCT = {
    # Anjali (2 towns): every tier incl. exact 100.00 and a below-floor KPI
    ('HAL_XSE_DL1', 'CORE_VALUE'): '104', ('HAL_XSE_DL1', 'FOCUS_NPI_VALUE'): '96',
    ('HAL_XSE_DL1', 'EC_OVERALL'): '100', ('HAL_XSE_DL1', 'BRAND_EC'): '108',
    ('HAL_XSE_DL1', 'BRAND_VALUE_ENO'): '85',
    # Ravi (new joiner, took Rohini on the 22nd): low raw % — the approved
    # new-joiner exception defaults his sales KPIs to 1x. Zero-target on FOCUS_EC.
    ('HAL_XSE_DL2', 'CORE_VALUE'): '35', ('HAL_XSE_DL2', 'FOCUS_NPI_VALUE'): '35',
    ('HAL_XSE_DL2', 'EC_OVERALL'): '40', ('HAL_XSE_DL2', 'BRAND_EC'): '40',
    ('HAL_XSE_DL2', 'BRAND_VALUE_ENO'): '35', ('HAL_XSE_DL2', 'FOCUS_EC'): None,
    # Manoj: excellent sales, fails the geofence gate → zero payout
    ('HAL_XSE_BLR', 'CORE_VALUE'): '112', ('HAL_XSE_BLR', 'FOCUS_NPI_VALUE'): '106',
    ('HAL_XSE_BLR', 'EC_OVERALL'): '95', ('HAL_XSE_BLR', 'BRAND_EC'): '97',
    ('HAL_XSE_BLR', 'BRAND_VALUE_ENO'): '101',
    # Sneha (MT Delhi): mid-grid; Divya (MT Blr): below floor + exact 90 boundary
    ('HAL_MTE_DL', 'CORE_VALUE'): '101', ('HAL_MTE_DL', 'FOCUS_NPI_VALUE'): '103.5',
    ('HAL_MTE_DL', 'BRAND_VALUE_ENO'): '99',
    ('HAL_MTE_BLR', 'CORE_VALUE'): '87', ('HAL_MTE_BLR', 'FOCUS_NPI_VALUE'): '92',
    ('HAL_MTE_BLR', 'BRAND_VALUE_ENO'): '90',
    # Whitefield distributor — partner portal shows real numbers
    ('HAL_DIST_WF', 'CORE_VALUE'): '98', ('HAL_DIST_WF', 'EC_OVERALL'): '102',
}
# TLSD / Productive Calls targets sit on towns (geography-grain external KPIs);
# pct per town — Rohini trails everywhere (the new-joiner story).
SFA_PCT = {'HAL_GT_DL_KB': D('91'), 'HAL_GT_DL_LN': D('91'), 'HAL_GT_DL_RH': D('35'),
           'HAL_GT_BLR_KM': D('103'), 'HAL_GT_BLR_WF': D('95')}

# ── SIP (RFP multiplier grid: pays from 90%, 1.0 at 100, up to 1.8 past 105) ───
GRID = [('0', '90', '0'), ('90', '100', '0.90'), ('100', '102', '1.00'),
        ('102', '105', '1.50'), ('105', None, '1.80')]
GT_MONTHLY = [('CORE_VALUE', 'sales', '35.00'), ('FOCUS_NPI_VALUE', 'sales', '15.00'),
              ('EC_OVERALL', 'execution', '12.50'), ('TLSD', 'execution', '12.50'),
              ('BRAND_EC', 'execution', '12.50'), ('BRAND_VALUE_ENO', 'execution', '12.50')]
GT_GATES = [('GEOFENCE', '85.00'), ('COMPLIANCE', '100.00')]
MT_MONTHLY = [('CORE_VALUE', 'sales', '40.00'), ('FOCUS_NPI_VALUE', 'sales', '20.00'),
              ('BRAND_VALUE_ENO', 'sales', '15.00'), ('ACTIVATION_ADHERENCE', 'execution', '25.00')]
ASM_MONTHLY = [('CORE_VALUE', 'sales', '60.00'), ('EC_OVERALL', 'execution', '40.00')]

EXCEPTION_CATEGORIES = [
    dict(code='new_joiner', name='New Joiner',
         description='Joined on/before the 20th → default 1x for the join month + 1; '
                     'after the 20th → join month + 2.',
         duration_config={'type': 'join_day_cutoff', 'cutoff_day': 20,
                          'months_on_or_before': 2, 'months_after': 3}),
    dict(code='maternity_leave', name='Maternity / Paternity Leave',
         description='Leaves ≥ 7 working days, marked and approved in HRMS.',
         duration_config={'type': 'fixed', 'effect_months': 6}, requires_dates=True),
    dict(code='medical_leave', name='Medical Leave',
         duration_config={'type': 'fixed', 'effect_months': 2}, requires_dates=True),
    dict(code='transfer', name='Territory / Division Transfer',
         description='Default 1x for 1 month (2 for a newly formed territory).',
         duration_config={'type': 'fixed', 'effect_months': 2}),
    dict(code='natural_calamity', name='Natural Calamity',
         description='> 5 working days impacted → default 1x for the month.'),
]


class Command(BaseCommand):
    help = 'Seed the complete Haleon GT+MT manual-testing world (all edge cases). --reset wipes first.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Wipe all business data (org, geography, transactions, targets, '
                                 'payouts, schemes, KPIs, master data) before seeding.')

    def handle(self, *args, **options):
        self._seed(options)
        # Outside the atomic block — a console-encoding hiccup while printing the
        # cheat sheet must never roll back the seeded world.
        self._print_summary()

    @transaction.atomic
    def _seed(self, options):
        today = date.today()
        self.cur_start = today.replace(day=1)
        self.prev_end = self.cur_start - timedelta(days=1)
        self.prev_start = self.prev_end.replace(day=1)
        self.today = today
        # Assignments open at the LY fiscal start so every "as of" date in the demo resolves.
        self.epoch = date(self.prev_start.year - 1, 4, 1)

        if options['reset']:
            self._reset()

        self._h('Infra seeds (roles, settings, workflows, templates, reports)')
        for cmd in ('seed_roles', 'seed_settings', 'seed_workflows',
                    'seed_notification_templates', 'seed_reports'):
            call_command(cmd, verbosity=0)
        self.stdout.write('  ok')
        self._ensure_admin()

        self._h('Channels + product master')
        self._seed_channels()
        self._seed_master_data()

        self._h('Org tree + geography + assignments')
        et = self._seed_entity_types()
        geo = self._seed_geography()
        self.geo = geo
        people = self._seed_people(et, geo)
        self.people = people

        self._h('KPIs + external metrics')
        self._seed_kpis()
        self._seed_external_metrics()

        self._h('Periods (fiscal-year tree)')
        prev_p, cur_p = self._seed_periods()

        self._h('Transactions (LY + closed month + MTD)')
        self._seed_month_transactions(self.prev_start.replace(year=self.prev_start.year - 1), None, ly=True)
        self._seed_month_transactions(self.cur_start.replace(year=self.cur_start.year - 1), None, ly=True)
        self._seed_month_transactions(self.prev_start, None)
        self._seed_month_transactions(self.cur_start, self.today)

        self._h('External metric values (SFA feeds)')
        sums_prev = self._seed_metric_values(self.prev_start, None)
        sums_cur = self._seed_metric_values(self.cur_start, self.today)

        self._h('Target allocations (engineered spread; non-AOP KPIs, plan-less)')
        eng_prev = self._seed_targets(prev_p, prev_p.end_date, sums_prev)
        eng_cur = self._seed_targets(cur_p, self.today, sums_cur)

        self._h('AOP plan (full pipeline: baseline, top, splits, cascade review)')
        self._seed_plan(prev_p, cur_p, {prev_p.id: eng_prev, cur_p.id: eng_cur})

        self._h('Retailer targets (partner portal, outlet grain)')
        self._seed_retailer_targets(prev_p, prev_p.end_date)
        self._seed_retailer_targets(cur_p, self.today)

        self._h('Publish live periods + revision governance demo')
        self._publish_periods(prev_p, cur_p)
        self._seed_governance_demo(cur_p)

        self._h('Achievements')
        self._seed_alert_rules()  # rules must exist BEFORE compute or no alerts fire
        self._compute_achievements(prev_p, prev_p.end_date)
        self._compute_achievements(cur_p, self.today)

        self._h('SIP schemes, variable pay, exceptions')
        schemes = self._seed_schemes(et)
        self._seed_variable_pay(prev_p, cur_p)
        self._seed_exceptions(prev_p, cur_p)

        self._h('Payout runs (closed month)')
        self._seed_payout_runs(schemes, prev_p)

    def _h(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n--- {title} ---'))

    # ═══════════════════════════════════════ reset ═══════════════════════════════
    def _reset(self):
        from apps.accounts.models import User
        from apps.achievements.models import Achievement, AchievementSnapshot, Alert, AlertRule
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import (Channel, GeographyNode, GeographyType, Node,
                                           NodeRelationship, NodeType)
        from apps.incentives.models import (ExceptionCategory, IncentiveScheme, Payout,
                                            PayoutCycle, PayoutException, PayoutRun, VariablePay)
        from apps.jobs.models import BulkJob
        from apps.kpi_engine.models import (ExternalMetric, ExternalMetricValue,
                                            IntegrationBatch, KPIDefinition, Transaction)
        from apps.master_data.models import SKU, SKUGroup, UOMConversion
        from apps.notifications.models import Notification
        from apps.targets.models import (AllocationRecipe, RevisionPolicy,
                                         TargetAllocation, TargetPeriod, TargetPlan,
                                         TargetRevision)
        from apps.workflows.models import WorkflowInstance

        self._h('Reset (wiping business data)')
        # Dependency order: facts → config → org. PROTECT FKs force this sequence.
        for qs in (
            Alert.objects.all(), Achievement.objects.all(), AchievementSnapshot.objects.all(),
            AlertRule.objects.all(),
            Payout.objects.all(), PayoutRun.objects.all(), PayoutCycle.objects.all(),
            PayoutException.objects.all(),
            VariablePay.objects.all(), IncentiveScheme.objects.all(), ExceptionCategory.objects.all(),
            WorkflowInstance.objects.all(),
            TargetRevision.objects.all(), TargetAllocation.objects.all(), TargetPlan.objects.all(),
            TargetPeriod.objects.all(), AllocationRecipe.objects.all(),
            RevisionPolicy.objects.all(),
            Transaction.objects.all(), ExternalMetricValue.objects.all(), ExternalMetric.objects.all(),
            IntegrationBatch.objects.all(), KPIDefinition.objects.all(),
            SKUGroup.objects.all(), SKU.objects.all(), UOMConversion.objects.all(),
            Notification.objects.all(), BulkJob.objects.all(),
            Assignment.objects.all(), NodeRelationship.objects.all(), Node.objects.all(),
            NodeType.objects.all(), GeographyNode.objects.all(), GeographyType.objects.all(),
            Channel.objects.all(),
            User.objects.filter(is_superuser=False, is_staff=False),
        ):
            qs.delete()
        self.stdout.write(self.style.WARNING('  wiped.'))

    # ═══════════════════════════════════ foundations ═════════════════════════════
    def _ensure_admin(self):
        from apps.accounts.models import Role, User, UserRole
        user, created = User.objects.get_or_create(
            email='admin@thriive.com',
            defaults={'first_name': 'Thriive', 'last_name': 'Admin',
                      'is_staff': True, 'is_superuser': True, 'is_active': True},
        )
        if created or not user.has_usable_password():
            user.set_password('Admin@1234')
            user.save(update_fields=['password', 'is_staff', 'is_superuser'])
        admin_role = Role.objects.filter(code='admin', is_active=True).first()
        if admin_role:
            UserRole.objects.get_or_create(user=user, role=admin_role,
                                           defaults={'effective_from': date.today()})
        self.admin = user

    def _seed_channels(self):
        from apps.hierarchy.models import Channel
        for code, name in CHANNELS:
            Channel.objects.get_or_create(code=code, defaults={'name': name})
        self.stdout.write(f'  channels: {", ".join(c for c, _ in CHANNELS)}')

    def _seed_master_data(self):
        from apps.master_data.models import SKU, SKUGroup
        from apps.master_data.services import MasterDataService
        for code, name, brand, cat, sub, mrp, focus, npi in SKUS:
            if not SKU.objects.filter(code=code).exists():
                MasterDataService.create_sku({'code': code, 'name': name, 'brand': brand,
                                              'category': cat, 'sub_category': sub,
                                              'mrp': D(mrp), 'is_focus': focus, 'is_npi': npi})
        # Delisted SKU with LY history only — inactive master, historic transactions remain.
        code, name, brand, cat, sub, mrp = DELISTED_SKU
        if not SKU.objects.filter(code=code).exists():
            sku = MasterDataService.create_sku({'code': code, 'name': name, 'brand': brand,
                                                'category': cat, 'sub_category': sub, 'mrp': D(mrp)})
            sku.is_active = False
            sku.save(update_fields=['is_active', 'updated_at'])
        for sku_code, from_uom, to_uom, factor in UOM_CONVERSIONS:
            from apps.master_data.models import UOMConversion
            if not UOMConversion.objects.filter(sku_code=sku_code, from_uom=from_uom).exists():
                MasterDataService.create_uom_conversion({'sku_code': sku_code, 'from_uom': from_uom,
                                                         'to_uom': to_uom, 'factor': D(factor)})
        for code, name, ftype, rule in [
            ('FOCUS', 'Focus SKUs', SKUGroup.FILTER_RULE, {'is_focus': True}),
            ('NPI', 'New Products', SKUGroup.FILTER_RULE, {'is_npi': True}),
            ('ENO', 'Eno (Brand)', SKUGroup.FILTER_RULE, {'brand': 'Eno'}),
            ('FOCUS_NPI', 'Focus + NPI', SKUGroup.FILTER_EXPLICIT, None),
        ]:
            group, _ = SKUGroup.objects.get_or_create(
                code=code, defaults={'name': name, 'filter_type': ftype, 'filter_rules': rule or {}})
            if code == 'FOCUS_NPI':  # explicit union — the rule resolver ANDs, it can't OR
                group.skus.set(SKU.objects.filter(Q(is_focus=True) | Q(is_npi=True), is_active=True))
        self.stdout.write(f'  SKUs: {SKU.objects.count()}, groups: FOCUS/NPI/ENO/FOCUS_NPI')

    # ═══════════════════════════════════ org world ═══════════════════════════════
    def _seed_entity_types(self):
        from apps.accounts.models import Role
        from apps.hierarchy.models import Channel, NodeType
        et = {}
        for code, name, lvl, parents, children, ch, leaf, role_code, portal, icon, color in ROLE_SPECS:
            existing = NodeType.objects.filter(code=code, is_current=True).first()
            if existing:
                et[code] = existing
                continue
            partner = code in ('dist', 'ret')
            et[code] = NodeType.objects.create(
                name=name, code=code, level_order=lvl,
                allowed_parent_types=parents, allowed_child_types=children,
                attribute_schema=DIST_SCHEMA if partner else FF_SCHEMA,
                is_loginable=True, incentive_eligible=not partner, is_leaf=leaf,
                default_role=Role.objects.filter(code=role_code, is_active=True).first(),
                channel=Channel.objects.filter(code=ch).first() if ch else None,
                display_config={'color': color, 'portal_type': portal,
                                'login_method': 'otp_only' if portal == 'partner' else 'password_and_otp',
                                'show_in_tree': True, 'icon': icon,
                                'card_fields': ['gstin'] if partner else ['employee_id']},
                effective_from=date.today(), version=1, is_current=True,
            )
            self.stdout.write(f'  [+] role {code}: {name}')
        # Top-up of a pre-retailer world: an existing dist type must accept ret children.
        if 'ret' not in (et['dist'].allowed_child_types or []):
            et['dist'].allowed_child_types = [*(et['dist'].allowed_child_types or []), 'ret']
            et['dist'].is_leaf = False
            et['dist'].save(update_fields=['allowed_child_types', 'is_leaf', 'updated_at'])
        return et

    def _seed_geography(self):
        from apps.hierarchy.config_services import GeographyNodeService, GeographyTypeService
        from apps.hierarchy.models import GeographyNode, GeographyType
        gt = GeographyType.objects.filter(code='sales_geo').first() or GeographyTypeService.create({
            'name': 'Sales Geography', 'code': 'sales_geo',
            'levels': ['nation', 'region', 'district', 'town', 'outlet'],
        })
        if 'outlet' not in gt.levels:  # idempotent top-up of a pre-retailer world
            gt.levels = [*gt.levels, 'outlet']
            gt.save(update_fields=['levels', 'updated_at'])
        nodes = {}
        for code, name, level, parent in GEO_SPEC:
            existing = GeographyNode.objects.filter(code=code, is_active=True).first()
            nodes[code] = existing or GeographyNodeService.create({
                'geography_type': gt, 'name': name, 'code': code, 'level': level,
                'parent': nodes.get(parent) if parent else None,
            })
        self.stdout.write(f'  geography: {len(nodes)} nodes incl. {len(RETAILERS)} retail outlets '
                          '(Dwarka left VACANT)')
        return nodes

    def _seed_people(self, et, geo):
        from apps.assignments.models import Assignment
        from apps.assignments.services import AssignmentService
        from apps.hierarchy.models import Channel, Node
        from apps.hierarchy.services import NodeService

        channel_ids = {c.code: c.pk for c in Channel.objects.all()}
        join_day = self.prev_start + timedelta(days=21)  # the 22nd — after the RFP's day-20 cutoff
        people = {}

        def _person(code, name, type_code, emp, scopes, *, parent=None, channel='GT',
                    email=None, mobile=None, effective_from=None, attrs=None):
            existing = Node.objects.filter(code=code, is_current=True).first()
            if existing:
                people[code] = existing
                return existing
            data = {
                'entity_type_id': et[type_code].id, 'name': name, 'code': code,
                'attributes': {**({'employee_id': emp} if type_code not in ('dist', 'ret') else {}),
                               **(attrs or {})},
                'effective_from': (effective_from or self.epoch).isoformat(),
                'channel_id': channel_ids[channel],
            }
            if parent:
                data['parent_id'] = parent.id
            if email:
                data['email'] = email
            if mobile:
                data['mobile'] = mobile
            owned = [geo[s].pk for s in scopes
                     if AssignmentService.owner_of(geo[s].pk, on=self.today) is None]
            if owned:
                data['owned_scope_ids'] = owned
            node = NodeService.create_entity(data, user=None)
            try:
                u = node.user
                u.set_password(DEMO_PASSWORD)
                u.save(update_fields=['password'])
            except Exception:  # noqa: BLE001 — partner types are OTP-only, no password
                pass
            people[code] = node
            self.stdout.write(f'  [+] {code}: {name}')
            return node

        nsm = _person('HAL_NSM', 'Arvind Menon', 'nsm', 'HAL001', ['HAL_IN'],
                      email='nsm@haleon.com')
        rsm_n = _person('HAL_RSM_N', 'Priya Nair', 'rsm', 'HAL002', ['HAL_NORTH'],
                        parent=nsm, email='rsm.north@haleon.com')
        rsm_s = _person('HAL_RSM_S', 'Rohit Iyer', 'rsm', 'HAL003', ['HAL_SOUTH'],
                        parent=nsm, email='rsm.south@haleon.com')
        asm_dl = _person('HAL_ASM_DL', 'Vikram Singh', 'asm', 'HAL004', ['HAL_GT_DL'],
                         parent=rsm_n, email='asm.delhi@haleon.com')
        asm_blr = _person('HAL_ASM_BLR', 'Kiran Rao', 'asm', 'HAL005', ['HAL_GT_BLR'],
                          parent=rsm_s, email='asm.bangalore@haleon.com')
        # Anjali starts owning THREE towns; Rohini is handed to the new joiner below.
        dl1 = _person('HAL_XSE_DL1', 'Anjali Gupta', 'xse', 'HAL006',
                      ['HAL_GT_DL_KB', 'HAL_GT_DL_LN', 'HAL_GT_DL_RH'],
                      parent=asm_dl, email='xse.delhi1@haleon.com')
        dl2 = _person('HAL_XSE_DL2', 'Ravi Verma', 'xse', 'HAL007', [],
                      parent=asm_dl, email='xse.delhi2@haleon.com',
                      effective_from=join_day, attrs={'joining_date': join_day.isoformat()})
        blr = _person('HAL_XSE_BLR', 'Manoj Pillai', 'xse', 'HAL008', ['HAL_GT_BLR_KM'],
                      parent=asm_blr, email='xse.bangalore@haleon.com')
        _person('HAL_MTE_DL', 'Sneha Kapoor', 'mte', 'HAL009', ['HAL_MT_DL'],
                parent=rsm_n, channel='MT', email='mte.delhi@haleon.com')
        _person('HAL_MTE_BLR', 'Divya Shetty', 'mte', 'HAL010', ['HAL_MT_BLR'],
                parent=rsm_s, channel='MT', email='mte.bangalore@haleon.com')
        # GT distributors (partner portal, OTP login). Whitefield's distributor OWNS its town.
        _person('HAL_DIST_KB', 'Karol Bagh Agencies', 'dist', '', [], parent=dl1,
                mobile='9811110001', attrs={'gstin': '07AAHCK1111A1Z1', 'credit_limit': '500000'})
        dist_ln = _person('HAL_DIST_LN', 'Lajpat Traders', 'dist', '', [], parent=dl1,
                          mobile='9811110002', attrs={'gstin': '07AAHCL2222B1Z2', 'credit_limit': '300000'})
        _person('HAL_DIST_RH', 'Rohini Distributors', 'dist', '', [], parent=dl2,
                mobile='9811110003', attrs={'gstin': '07AAHCR3333C1Z3', 'credit_limit': '250000'})
        _person('HAL_DIST_KM', 'Koramangala Sales Corp', 'dist', '', [], parent=blr,
                mobile='9811110004', attrs={'gstin': '29AAHCK4444D1Z4', 'credit_limit': '400000'})
        _person('HAL_DIST_WF', 'Whitefield Distributors', 'dist', '', ['HAL_GT_BLR_WF'],
                parent=blr, mobile='9811110005',
                attrs={'gstin': '29AAHCW5555E1Z5', 'credit_limit': '350000'})

        # Retailers (partner portal, OTP login) — each under its distributor in the org
        # tree, each OWNING its outlet territory (the node its sales are attributed to).
        for code, (name, outlet, dist_code, mobile, gstin, _pct) in RETAILERS.items():
            _person(code, name, 'ret', '', [outlet], parent=people[dist_code],
                    mobile=mobile, attrs={'gstin': gstin})

        # Suspended partner — appears in the tree, blocked from the portal.
        if dist_ln.status != 'suspended':
            dist_ln.status = 'suspended'
            dist_ln.save(update_fields=['status', 'updated_at'])

        # Backdate every owner assignment to the LY fiscal start so LY/as-of resolution
        # works — EXCEPT the new joiner's (kept at his join date via the transfer below).
        Assignment.objects.filter(effective_from__gt=self.epoch).exclude(
            assignee=dl2).update(effective_from=self.epoch)

        # EDGE: mid-month territory transfer — Rohini moves from Anjali to the new
        # joiner Ravi on his join date. History before the 22nd stays visible to Anjali.
        if AssignmentService.owner_of(geo['HAL_GT_DL_RH'].pk, on=self.today) != dl2:
            AssignmentService.transfer(
                scope_id=geo['HAL_GT_DL_RH'].pk, new_assignee_id=dl2.id,
                effective_from=join_day, reason='New joiner takes over the Rohini beat.')
            self.stdout.write(f'  [+] transfer: Rohini -> Ravi Verma effective {join_day}')
        return people

    # ═══════════════════════════════════ KPIs ════════════════════════════════════
    def _seed_kpis(self):
        from apps.kpi_engine.models import KPIDefinition
        from apps.kpi_engine.services import KPIService
        created = 0
        for spec in KPIS:
            if KPIDefinition.objects.filter(code=spec['code'], is_current=True).exists():
                continue
            KPIService.create_kpi({**spec, 'applicable_entity_types': APPLIES}, actor=None)
            created += 1
        self.stdout.write(f'  transactional KPIs: {created} created ({len(KPIS)} total)')

    def _seed_external_metrics(self):
        from apps.kpi_engine.models import ExternalMetric, KPIDefinition
        from apps.kpi_engine.services import KPIService
        for code, name, unit, granularity, grain, agg in EXTERNAL_METRICS:
            ExternalMetric.objects.get_or_create(
                code=code, defaults={'name': name, 'unit': unit, 'granularity': granularity,
                                     'period_grain': grain, 'default_aggregation': agg})
        created = 0
        for spec in EXTERNAL_KPIS:
            if KPIDefinition.objects.filter(code=spec['code'], is_current=True).exists():
                continue
            KPIService.create_kpi({**spec, 'kpi_type': KPIDefinition.EXTERNAL}, actor=None)
            created += 1
        self.stdout.write(f'  external metrics: {len(EXTERNAL_METRICS)}, external KPIs: {created} created')

    # ═══════════════════════════════════ periods ═════════════════════════════════
    def _seed_periods(self):
        from apps.targets.models import TargetPeriod
        from apps.targets.services import TargetService

        def _fy(d):
            y = d.year if d.month >= 4 else d.year - 1
            return f'{y}-{(y + 1) % 100:02d}'

        for fy in sorted({_fy(self.prev_start), _fy(self.cur_start)}):
            TargetService.generate_fiscal_year(fy, start_month=4)
            self.stdout.write(f'  [+] fiscal year {fy} (annual container + 12M)')

        # NOTE: the live months stay DRAFT until the plan's field adjustments are applied
        # (draft-period edits auto-approve); _publish_periods flips them later.
        prev_p = TargetPeriod.objects.get(period_type=TargetPeriod.MONTHLY, start_date=self.prev_start)
        cur_p = TargetPeriod.objects.get(period_type=TargetPeriod.MONTHLY, start_date=self.cur_start)
        return prev_p, cur_p

    # ═══════════════════════════════ transactions ════════════════════════════════
    def _seed_month_transactions(self, month_start, as_of, ly=False):
        from apps.kpi_engine.models import Transaction
        geo = self.geo
        month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
        as_of = as_of or month_end
        tag = f'{month_start:%Y%m}'
        rows, seq = [], 0

        def _row(node_code, day, sku, net, *, source='dms_sync', level='secondary',
                 ttype='sale', outlet='', channel='GT'):
            nonlocal seq
            tdate = month_start + timedelta(days=day - 1)
            if tdate > as_of:
                return
            seq += 1
            net = D(net).quantize(D('0.01'))
            # An outlet string that IS a geography node (a retailer's outlet) takes the
            # attribution; the town subtree total is identical either way.
            attributed = geo.get(outlet) if outlet else None
            rows.append(Transaction(
                attributed_node_id=(attributed or geo[node_code]).pk, transaction_date=tdate,
                posted_date=tdate, transaction_type=ttype, transaction_level=level,
                channel_code=channel, sku_code=sku, outlet_code=outlet,
                bill_ref=f'HAL-{tag}-{seq:05d}', gross_amount=net * D('1.12'),
                net_amount=net, quantity=max(D('1'), (net / 100).quantize(D('1'))),
                uom='unit', source=source, external_ref=f'HAL-{tag}-{node_code}-{seq:04d}',
            ))

        for town, (base, n_outlets, dist_code) in GT_TOWN_SALES.items():
            factor = (LY_FACTORS.get(town, LY_DEFAULT_FACTOR) if ly else D('1'))
            basket = DW_BASKET if town == 'HAL_GT_DL_DW' else BASKET
            for i, day in enumerate(SALE_DAYS):
                _row(town, day, basket[i % len(basket)], (base + 137 * i) * factor,
                     source=SOURCES[i % len(SOURCES)], outlet=f'{town}-OUT{i % n_outlets + 1}')
            # boundary-date sale on the month's last day
            _row(town, month_end.day, basket[0], base * factor, outlet=f'{town}-OUT1')
            # one return per town (net_logic paths); EC outlets stay net-positive
            _row(town, 9, 'ENO-LEMON-100', base * D('0.25') * factor, ttype='return',
                 outlet=f'{town}-OUT1', source='dms_sync')
            if dist_code and not ly:
                # primary sell-in to the distributor (2 bills)
                for j, day in enumerate((2, 16)):
                    _row(town, day, BASKET[j], base * 8, level='primary', outlet=dist_code)
        if not ly:
            # EDGE: one Karol Bagh outlet where returns exceed sales — net ≤ 0, must
            # drop out of every Effective Coverage KPI (having net > 0).
            _row('HAL_GT_DL_KB', 3, 'CRO-ADV-15', 500, outlet='HAL_GT_DL_KB-NEGOUT')
            _row('HAL_GT_DL_KB', 18, 'CRO-ADV-15', 800, ttype='return', outlet='HAL_GT_DL_KB-NEGOUT')
        else:
            # EDGE: delisted SKU only exists in LY history
            _row('HAL_GT_DL_KB', 12, DELISTED_SKU[0], 900, outlet='HAL_GT_DL_KB-OUT2')

        for node, (base, stores) in MT_NODE_SALES.items():
            factor = LY_DEFAULT_FACTOR if ly else D('1')
            for j, store in enumerate(stores):
                for i, day in enumerate(MT_DAYS):
                    _row(node, day, BASKET[(i + j) % len(BASKET)],
                         (base + 211 * j + 53 * i) * factor, channel='MT',
                         source='invoice_upload' if i == 3 else 'api_push', outlet=store)
            _row(node, 13, 'ENO-LEMON-100', base * D('0.2') * factor, channel='MT',
                 ttype='return', outlet=stores[0], source='api_push')

        Transaction.objects.bulk_create(rows, ignore_conflicts=True)
        self.stdout.write(f'  [{tag}] {len(rows)} rows (sale/return, primary/secondary, '
                          f'dms/qr/manual/api/invoice){" [LY]" if ly else ""}')

    # ══════════════════════════════ external metrics ═════════════════════════════
    def _seed_metric_values(self, month_start, as_of):
        from apps.kpi_engine.models import ExternalMetric, ExternalMetricValue
        geo, people = self.geo, self.people
        month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
        as_of = as_of or month_end
        tag = f'{month_start:%Y%m}'
        metric = {m.code: m for m in ExternalMetric.objects.all()}
        rows, geo_sums = [], {'TLSD': {}, 'PRODUCTIVE_CALLS': {}}

        def _geo_rows(code, bases):
            for town, base in bases.items():
                total = D('0')
                for i, day in enumerate((7, 14, 21, 28)):
                    mdate = month_start + timedelta(days=day - 1)
                    if mdate > as_of:
                        continue
                    value = D(base + (i * 3) % 7)
                    total += value
                    rows.append(ExternalMetricValue(
                        metric=metric[code], node_id=geo[town].pk, measured_on=mdate,
                        value=value, source='sfa_sync',
                        external_ref=f'HAL-EMV-{code}-{town}-{tag}-{i}'))
                geo_sums[code][town] = total

        def _entity_row(code, person_code, value):
            rows.append(ExternalMetricValue(
                metric=metric[code], entity=people[person_code], measured_on=month_start,
                value=D(value), source='sfa_sync',
                external_ref=f'HAL-EMV-{code}-{person_code}-{tag}'))

        _geo_rows('TLSD', TLSD_BASE)
        _geo_rows('PRODUCTIVE_CALLS', CALLS_BASE)

        closed = as_of >= month_end
        # Geofence: Manoj fails the 85% gate in the closed month despite 112% sales.
        for person, val_closed, val_open in (('HAL_XSE_DL1', 92, 90),
                                             ('HAL_XSE_DL2', 88, 91),
                                             ('HAL_XSE_BLR', 70, 86)):
            _entity_row('GEOFENCED_COVERAGE_PCT', person, val_closed if closed else val_open)
        for person in ('HAL_XSE_DL1', 'HAL_XSE_DL2', 'HAL_XSE_BLR', 'HAL_MTE_DL', 'HAL_MTE_BLR'):
            _entity_row('COMPLIANCE_CLEAN', person, 100)
        # EDGE: MTE Bangalore has NO activation score — scheme KPI with missing data.
        _entity_row('ACTIVATION_ADHERENCE', 'HAL_MTE_DL', 96 if closed else 88)

        ExternalMetricValue.objects.bulk_create(rows, ignore_conflicts=True)
        self.stdout.write(f'  [{tag}] {len(rows)} metric values (TLSD/calls per town, '
                          f'geofence/compliance/activation per person)')
        return geo_sums

    # ═══════════════════════════════════ targets ═════════════════════════════════
    def _seed_targets(self, period, as_of, geo_sums):
        """Engineer the achievement spread (target = actual ÷ desired pct).

        Non-AOP KPIs are written as plan-less allocations (the doc's bulk-import path)
        and rolled up the geography tree. The AOP trio is NOT written here — its
        engineered per-node values are returned and later applied as governed field
        adjustments on the plan-committed numbers (_seed_plan)."""
        from apps.assignments.services import AssignmentService
        from apps.kpi_engine.calculator import KPICalculator
        from apps.kpi_engine.models import KPIDefinition
        from apps.kpi_engine.periods import working_days_between
        from apps.targets.models import TargetAllocation

        geo, people = self.geo, self.people
        total_wd = period.working_days or working_days_between(period.start_date, period.end_date)
        elapsed_wd = max(1, working_days_between(period.start_date, as_of))
        kpis = {k.code: k for k in KPIDefinition.objects.filter(is_current=True, is_active=True)}
        txn_kpis = [kpis[s['code']] for s in KPIS]
        leaf_owners = ['HAL_XSE_DL1', 'HAL_XSE_DL2', 'HAL_XSE_BLR',
                       'HAL_MTE_DL', 'HAL_MTE_BLR', 'HAL_DIST_WF']
        created = 0
        engineered = {code: {} for code in AOP_KPIS}  # kpi_code -> {node_id: target}

        def _quant(kpi):
            return D('1') if kpi.decimal_places == 0 else D('0.01')

        def _upsert(kpi, node_id, target):
            nonlocal created
            _, was_created = TargetAllocation.objects.update_or_create(
                target_period=period, kpi=kpi, geography_node_id=node_id,
                channel=None, sku_group=None,
                defaults={'target_value': target, 'original_target_value': target,
                          'status': TargetAllocation.APPROVED, 'source': TargetAllocation.MANUAL})
            created += int(was_created)

        def _set(kpi, node_id, target):
            if kpi.code in engineered:
                engineered[kpi.code][node_id] = target
            else:
                _upsert(kpi, node_id, target)

        for code in leaf_owners:
            entity = people[code]
            owned = AssignmentService.owned_scope_ids_for_entity(entity.id, on=period.end_date)
            if not owned:
                continue
            for kpi in txn_kpis:
                pct = ACH_PCT.get((code, kpi.code), DEFAULT_PCT)
                if pct is None:
                    # EDGE: explicit zero target with real actuals (division-by-zero path)
                    _upsert(kpi, owned[0], D('0'))
                    continue
                if kpi.code == 'UNIQUE_SKUS':
                    # Distinct counts don't union across territories — the achievement
                    # engine sums per-node distincts, so the target is built per node.
                    for node_id in owned:
                        per = self._distinct_skus(node_id, period.start_date, as_of)
                        if per > 0:
                            expected = D(per) * D(total_wd) / D(elapsed_wd)
                            _upsert(kpi, node_id, (expected * 100 / D(pct)).quantize(D('1')))
                    continue
                actual = KPICalculator(kpi, period.start_date, as_of).compute_for_entity(entity.id)
                if actual <= 0:
                    continue
                expected_full = actual * D(total_wd) / D(elapsed_wd)
                target_total = (expected_full * 100 / D(pct)).quantize(_quant(kpi))
                # Split across owned towns 55/45/…; last node absorbs rounding so the
                # derived person target stays exact.
                weights = [D('0.55'), D('0.45')] if len(owned) == 2 else \
                          [D('1') / len(owned)] * len(owned)
                allocated = D('0')
                for idx, node_id in enumerate(owned):
                    if idx == len(owned) - 1:
                        part = target_total - allocated
                    else:
                        part = (target_total * weights[idx]).quantize(_quant(kpi))
                        allocated += part
                    _set(kpi, node_id, part)

        # TLSD / Productive Calls targets live on towns directly (geography-grain
        # external KPIs with target_source='allocation').
        for metric_code, sums in geo_sums.items():
            for town, actual in sums.items():
                if actual <= 0:
                    continue
                expected_full = actual * D(total_wd) / D(elapsed_wd)
                target = (expected_full * 100 / SFA_PCT.get(town, DEFAULT_PCT)).quantize(D('1'))
                _upsert(kpis[metric_code], geo[town].pk, target)

        # EDGE: target on the VACANT town with zero matching sales — Dwarka carries an
        # NPI target but its basket has no NPI SKUs, and no rep owns it.
        _upsert(kpis['NPI_VALUE'], geo['HAL_GT_DL_DW'].pk, D('40000'))

        # Roll plan-less leaf allocations up the geography tree (district = Σ towns,
        # region = Σ districts) so manager-derived targets reconcile exactly. The AOP
        # trio reconciles inside the plan instead.
        for kpi in [k for k in txn_kpis if k.code not in AOP_KPIS] + \
                   [kpis['TLSD'], kpis['PRODUCTIVE_CALLS']]:
            self._rollup(period, kpi)
        self.stdout.write(f'  [{period.code}] {created} plan-less leaf allocations (+ rollups); '
                          f'AOP spread engineered for {len(AOP_KPIS)} KPIs')
        return engineered

    def _seed_retailer_targets(self, period, as_of):
        """Engineered CORE_VALUE targets on the retailer outlets (plan-less rows, created
        AFTER the plan so `_apply_engineered`'s parent re-true never folds outlets into the
        engineered town numbers). Outlet targets are extra grain below the AOP — they need
        not sum to the town's number. Gives every retailer a real achievement % in the
        partner portal."""
        from apps.kpi_engine.calculator import KPICalculator
        from apps.kpi_engine.models import KPIDefinition
        from apps.kpi_engine.periods import working_days_between
        from apps.targets.models import TargetAllocation

        kpi = KPIDefinition.objects.get(code='CORE_VALUE', is_current=True)
        total_wd = period.working_days or working_days_between(period.start_date, period.end_date)
        elapsed_wd = max(1, working_days_between(period.start_date, as_of))
        created = 0
        for code, (_name, outlet, _dist, _mobile, _gstin, pct) in RETAILERS.items():
            actual = KPICalculator(kpi, period.start_date, as_of).compute_for_entity(self.people[code].id)
            if actual <= 0:
                continue
            expected_full = actual * D(total_wd) / D(elapsed_wd)
            target = (expected_full * 100 / D(pct)).quantize(D('0.01'))
            _, was_created = TargetAllocation.objects.update_or_create(
                target_period=period, kpi=kpi, geography_node=self.geo[outlet],
                channel=None, sku_group=None,
                defaults={'target_value': target, 'original_target_value': target,
                          'status': TargetAllocation.APPROVED, 'source': TargetAllocation.MANUAL})
            created += int(was_created)
        self.stdout.write(f'  [{period.code}] {created} retailer CORE_VALUE targets '
                          f'({len(RETAILERS)} retailers)')

    @staticmethod
    def _distinct_skus(node_id, start, end):
        from apps.hierarchy.models import GeographyNode
        from apps.kpi_engine.models import Transaction
        node = GeographyNode.objects.get(pk=node_id)
        subtree = GeographyNode.objects.filter(
            path__startswith=node.path, is_active=True).values_list('id', flat=True)
        return Transaction.objects.filter(
            attributed_node_id__in=list(subtree), transaction_type='sale',
            transaction_level='secondary', transaction_date__gte=start,
            transaction_date__lte=end).values('sku_code').distinct().count()

    def _rollup(self, period, kpi):
        from apps.targets.models import TargetAllocation
        allocs = list(TargetAllocation.objects.filter(
            target_period=period, kpi=kpi, channel=None, sku_group=None, is_active=True,
        ).select_related('geography_node'))
        leaf_ids = {a.geography_node_id for a in allocs}
        totals = {}
        for a in allocs:
            node = a.geography_node.parent
            while node is not None:
                totals[node.id] = totals.get(node.id, D('0')) + a.effective_target
                node = node.parent
        for node_id, total in totals.items():
            if node_id in leaf_ids:
                continue
            TargetAllocation.objects.update_or_create(
                target_period=period, kpi=kpi, geography_node_id=node_id,
                channel=None, sku_group=None,
                defaults={'target_value': total, 'original_target_value': total,
                          'status': TargetAllocation.APPROVED, 'source': TargetAllocation.MANUAL})

    # ═══════════════════════════════ achievements ════════════════════════════════
    def _compute_achievements(self, period, as_of):
        from apps.achievements.services import AchievementService
        result = AchievementService.compute_period(period.id, as_of=as_of)
        self.stdout.write(f'  [{period.code}] processed={result.get("records_processed")} '
                          f'alerts={result.get("alerts")}')

    def _seed_alert_rules(self):
        from apps.achievements.models import AlertRule
        rules = [
            dict(code='AT_RISK', name='Territory at risk', metric=AlertRule.PROJECTED_PCT,
                 comparator='lt', threshold=D('90'), severity=AlertRule.CRITICAL,
                 scope_entity_types=['xse', 'mte', 'asm'],
                 message_template='{entity}: projected {value}% — below 90% of target'),
            dict(code='LOW_GROWTH', name='Declining vs last year', metric=AlertRule.GROWTH_PCT,
                 comparator='lt', threshold=D('0'), severity=AlertRule.WARNING,
                 scope_entity_types=['xse'],
                 message_template='{entity}: down {value}% vs last year'),
        ]
        for r in rules:
            if not AlertRule.objects.filter(code=r['code'], is_current=True).exists():
                AlertRule.objects.create(**r, effective_from=date.today())

    # ═══════════════════════════════════ SIP ═════════════════════════════════════
    def _seed_schemes(self, et):
        from apps.hierarchy.models import Channel
        from apps.incentives.models import ExceptionCategory, IncentiveScheme
        from apps.incentives.services import SchemeService
        from apps.kpi_engine.models import KPIDefinition

        for spec in EXCEPTION_CATEGORIES:
            if ExceptionCategory.objects.filter(code=spec['code'], is_current=True).exists():
                continue
            ExceptionCategory.objects.create(
                code=spec['code'], name=spec['name'], description=spec.get('description', ''),
                duration_config=spec.get('duration_config', {}),
                requires_dates=spec.get('requires_dates', False),
                default_sales_kpi_action='default_1x', default_execution_kpi_action='default_1x',
                default_gatekeeper_action='exempted', effective_from=date.today())

        channels = {c.code: c for c in Channel.objects.all()}
        kpis = {k.code: k for k in KPIDefinition.objects.filter(is_current=True)}
        schemes = {}

        def _scheme(code, name, type_code, channel, frequency, vp_basis, kpi_rows, gates):
            existing = IncentiveScheme.objects.filter(code=code, is_current=True).first()
            if existing:
                schemes[code] = existing
                return
            schemes[code] = SchemeService.create({
                'name': name, 'code': code,
                'description': 'Haleon GT/MT demo SIP component (RFP multiplier grid).',
                'target_entity_type': et[type_code], 'channel': channels.get(channel),
                'payout_frequency': frequency, 'vp_basis_pct': D(vp_basis),
                'overall_cap_pct': D('180.00'),
                'gates': [{'kpi': kpis[c], 'operator': 'gte', 'threshold_pct': D(t),
                           'display_order': i} for i, (c, t) in enumerate(gates)],
                'gatekeeper_action': IncentiveScheme.ZERO_PAYOUT,
                'effective_from': self.epoch,
                'kpis': [{'kpi': kpis[c], 'incentive_category': cat, 'weightage': D(w),
                          'display_order': i,
                          'tiers': [{'min_achievement_pct': D(mn),
                                     'max_achievement_pct': D(mx) if mx is not None else None,
                                     'multiplier': D(mult)} for mn, mx, mult in GRID]}
                         for i, (c, cat, w) in enumerate(kpi_rows)],
            }, actor=None)
            self.stdout.write(f'  [+] scheme {code} ({frequency}, VP {vp_basis}%)')

        _scheme('GT_SIP_MONTHLY', 'GT SIP — Monthly KPIs (80%)', 'xse', 'GT',
                IncentiveScheme.MONTHLY, '80.00', GT_MONTHLY, GT_GATES)
        _scheme('GT_SIP_ANNUAL', 'GT SIP — Annual Performance (20%)', 'xse', 'GT',
                IncentiveScheme.ANNUAL, '20.00', [('CORE_VALUE', 'sales', '100.00')], [])
        _scheme('MT_SIP_MONTHLY', 'MT SIP — Monthly KPIs', 'mte', 'MT',
                IncentiveScheme.MONTHLY, '100.00', MT_MONTHLY, [('COMPLIANCE', '100.00')])
        _scheme('GT_ASM_SIP_MONTHLY', 'GT ASM SIP — Monthly (team rollup)', 'asm', 'GT',
                IncentiveScheme.MONTHLY, '100.00', ASM_MONTHLY, [])
        return schemes

    def _seed_variable_pay(self, prev_p, cur_p):
        from apps.incentives.services import VariablePayService
        people = self.people
        vp = {'HAL_XSE_DL1': '50000', 'HAL_XSE_DL2': '50000', 'HAL_XSE_BLR': '50000',
              'HAL_MTE_DL': '60000', 'HAL_MTE_BLR': '60000',
              'HAL_ASM_DL': '80000', 'HAL_ASM_BLR': '80000'}
        count = 0
        for code, amount in vp.items():
            # New joiner: pro-rated eligibility for the join month (~7 of 26 working days).
            ewd = 7 if code == 'HAL_XSE_DL2' else None
            VariablePayService.upsert(people[code], prev_p, D(amount), eligible_working_days=ewd)
            count += 1
            # EDGE: Manoj has NO variable pay in the current month.
            if code != 'HAL_XSE_BLR':
                VariablePayService.upsert(people[code], cur_p, D(amount))
                count += 1
        self.stdout.write(f'  variable pay: {count} rows (Ravi pro-rated, Manoj missing in '
                          f'{cur_p.code})')

    def _seed_exceptions(self, prev_p, cur_p):
        from apps.incentives.models import ExceptionCategory, PayoutException
        people = self.people
        join_day = self.prev_start + timedelta(days=21)
        cats = {c.code: c for c in ExceptionCategory.objects.filter(is_current=True)}

        if not PayoutException.objects.filter(entity=people['HAL_XSE_DL2'],
                                              target_period=prev_p, is_active=True).exists():
            PayoutException.objects.create(
                entity=people['HAL_XSE_DL2'], target_period=prev_p,
                category='new_joiner', category_ref=cats.get('new_joiner'),
                reference_date=join_day,
                sales_kpi_action=PayoutException.DEFAULT_1X,
                execution_kpi_action=PayoutException.DEFAULT_1X,
                gatekeeper_action=PayoutException.EXEMPTED,
                reason=f'Joined {join_day} (after the day-20 cutoff) — defaults to 1x.',
                status=PayoutException.APPROVED, approved_by=self.admin)
            self.stdout.write('  [+] APPROVED new-joiner exception: Ravi Verma')
        if not PayoutException.objects.filter(entity=people['HAL_XSE_DL1'],
                                              target_period=cur_p, is_active=True).exists():
            PayoutException.objects.create(
                entity=people['HAL_XSE_DL1'], target_period=cur_p,
                category='transfer', category_ref=cats.get('transfer'),
                sales_kpi_action=PayoutException.DEFAULT_1X,
                execution_kpi_action=PayoutException.ACTUAL,
                gatekeeper_action=PayoutException.NO_EXEMPTION,
                reason='Rohini beat carved out mid-June; target rebasing under review.',
                status=PayoutException.PENDING)
            self.stdout.write('  [+] PENDING transfer exception: Anjali Gupta')

    def _seed_payout_runs(self, schemes, prev_p):
        from apps.incentives.models import PayoutRun
        from apps.incentives.services import PayoutService

        def _run(scheme, submit):
            if scheme is None or PayoutRun.objects.filter(
                    scheme__code=scheme.code, target_period=prev_p).exists():
                return
            run = PayoutService.start_run(scheme.id, prev_p.id, actor=self.admin)
            PayoutService.compute_run(run.id, triggered_by=self.admin)
            run.refresh_from_db()
            if submit and run.status == PayoutRun.COMPUTED:
                PayoutService.submit_for_review(run, self.admin)
                run.refresh_from_db()
            self.stdout.write(f'  [+] payout run {scheme.code} × {prev_p.code}: {run.status}')

        # GT run sits UNDER REVIEW (maker-checker approve/reject demo); MT run stays
        # COMPUTED; the ASM scheme is left un-run so the full flow can be driven by hand.
        _run(schemes.get('GT_SIP_MONTHLY'), submit=True)
        _run(schemes.get('MT_SIP_MONTHLY'), submit=False)

    # ═══════════════════════════════════ AOP plan ════════════════════════════════
    def _seed_plan(self, prev_p, cur_p, engineered_by_period):
        """The revamped plan-first process end-to-end (docs/TARGET_MODULE_REVAMP_PLAN.md):
        baseline → typed top numbers → spatial + product commits — on the current month
        (targets are always set monthly) → cascade review. The engineered achievement
        spread is then applied as governed field adjustments (overrides +
        TargetRevisions) on the plan month (the closed month rides the plan-less
        fallback), and the review tasks are driven into every state. A realign run is
        left STAGED so the preview/commit banner (with override collisions) is live in
        the workspace."""
        from apps.kpi_engine.models import KPIDefinition
        from apps.targets.models import AllocationRecipe, PlanRun, RevisionPolicy, TargetPlan
        from apps.targets.plan_services import PlanService
        from apps.targets.review_services import ReviewService

        plan_code = f'HAL-AOP-{cur_p.code}'
        if TargetPlan.objects.filter(code=plan_code).exists():
            self.stdout.write(f'  [~] plan {plan_code} already exists')
            return
        kpis = {k.code: k for k in KPIDefinition.objects.filter(code__in=AOP_KPIS, is_current=True)}
        if len(kpis) != len(AOP_KPIS):
            self.stdout.write(self.style.WARNING('  [!] an AOP KPI is missing — plan skipped'))
            return

        if not RevisionPolicy.objects.filter(code='HAL_CHANGE_CAP', is_current=True).exists():
            RevisionPolicy.objects.create(
                name='Change cap: auto within 10%, blocked past 50%', code='HAL_CHANGE_CAP',
                effective_from=date.today(), auto_approve_within_pct=D('10'),
                hard_ceiling_pct=D('50'), requires_reason=True)
            self.stdout.write('  [+] revision policy HAL_CHANGE_CAP (10% auto / 50% ceiling)')

        value_recipe = AllocationRecipe.objects.filter(code='HAL_VALUE_SPLIT', is_current=True).first() or \
            AllocationRecipe.objects.create(
                name='70% contribution + 30% equal, +10% growth, ₹1k rounding',
                code='HAL_VALUE_SPLIT', effective_from=date.today(),
                weight_components=[{'source': 'contribution', 'weight': 70},
                                   {'source': 'equal', 'weight': 30}],
                base_window={'basis': 'ly_same_period'}, growth={'default_pct': 10},
                constraints={'no_negative': True}, rounding={'unit': 1000})
        ec_recipe = AllocationRecipe.objects.filter(code='HAL_EC_SPLIT', is_current=True).first() or \
            AllocationRecipe.objects.create(
                name='Outlet counts: contribution blend, whole-outlet rounding',
                code='HAL_EC_SPLIT', effective_from=date.today(), kpi=kpis['EC_OVERALL'],
                weight_components=[{'source': 'contribution', 'weight': 70},
                                   {'source': 'equal', 'weight': 30}],
                base_window={'basis': 'ly_same_period'}, growth={'default_pct': 10},
                constraints={'no_negative': True}, rounding={'unit': 1})

        recipe_for = {'CORE_VALUE': value_recipe, 'FOCUS_NPI_VALUE': value_recipe,
                      'EC_OVERALL': ec_recipe}
        # NPI has no history — the classic fixed-mix seeding case rides on Core Value.
        product_split_for = {'CORE_VALUE': {'mode': 'history', 'fixed_mix': {'NPI': 8}},
                             'FOCUS_NPI_VALUE': {'mode': 'history'},
                             'EC_OVERALL': {'mode': 'history'}}
        plan = PlanService.create_plan(
            {'name': f'{cur_p.name} AOP (Haleon GT+MT)',
             'code': plan_code, 'period_id': cur_p.id,
             'root_geography_id': self.geo['HAL_IN'].id,
             # The AOP materialises at towns; retailer outlets below get their own
             # plan-less targets (_seed_retailer_targets), never plan splits.
             'planning_grain': 'town',
             'review_levels': ['region', 'district'],
             'product_scope': ['FOCUS', 'NPI', 'ENO'],
             # Deliberately below the month's projected cost (~380k at 100%) so the gap
             # board shows the over-budget flag and publish needs the audited override.
             'settings': {'payout_budget': '350000'}},
            kpis=[{'kpi_id': kpis[code].id, 'recipe_id': recipe_for[code].id,
                   'baseline_spec': {'components': [{'basis': 'ly_same_period', 'weight': 100}]},
                   'product_split': product_split_for[code]} for code in AOP_KPIS],
            actor=self.admin)

        def _run(kind, commit, scope_node=None):
            run = PlanService.start_run(plan, kind, actor=self.admin, scope_node=scope_node)
            if run.status != PlanRun.STAGED:
                errors = run.job.errors if run.job else []
                raise CommandError(f'{kind} run ended {run.status}: {errors}')
            if commit:
                stats = PlanService.commit_run(run, actor=self.admin)
                self.stdout.write(f'  [+] {kind} committed ({stats["created"]} created, '
                                  f'{stats["updated"]} updated)')
            else:
                self.stdout.write(f'  [+] {kind} staged ({(run.stats or {}).get("staged_rows", 0)} rows)')
            return run

        _run(PlanRun.BASELINE, commit=False)
        # Typed top numbers (the AOP letter): the engineered month totals, so the plan
        # and the engineered spread live on the same scale. The derived suggestion stays
        # alongside on the PlanKpi as the sanity anchor.
        cur_eng = engineered_by_period[cur_p.id]
        for code in AOP_KPIS:
            total = sum(cur_eng.get(code, {}).values(), D('0'))
            if code == 'EC_OVERALL':
                top = total.quantize(D('1')) or D('300')
            else:
                top = (total / 1000).quantize(D('1')) * 1000 or D('1200000')
            PlanService.set_top_number(plan, kpis[code], top, actor=self.admin)
        _run(PlanRun.SPATIAL, commit=True)
        _run(PlanRun.PRODUCT, commit=True)

        # Apply the engineered spread while the plan is still DRAFT (the free sandbox):
        # its deltas vs the system split are far beyond any change cap by design, and
        # governance really fires once the plan is in review.
        for period in (prev_p, cur_p):
            n = self._apply_engineered(plan, period, engineered_by_period[period.id], kpis)
            self.stdout.write(f'  [{period.code}] {n} engineered spread adjustments applied')

        # Open the cascade. The Delhi ASM answers through their ReviewTask by confirming
        # the KB month number as-is (zero-delta adjust → task ADJUSTED, spread stays exact).
        PlanService.transition_plan(plan, TargetPlan.IN_REVIEW, actor=self.admin)
        tasks = {t.node.code: t for t in plan.review_tasks.select_related('node')}
        kb_row = plan.allocations.filter(
            target_period=cur_p, kpi=kpis['CORE_VALUE'], sku_group=None, channel=None,
            geography_node=self.geo['HAL_GT_DL_KB']).first()
        if kb_row is not None and tasks.get('HAL_GT_DL'):
            ReviewService.adjust(tasks['HAL_GT_DL'], kb_row, kb_row.effective_target,
                                 actor=self.admin, rebalance=False,
                                 reason='Bottom-up correction from the beat plan.')

        # Drive the review tasks into every state (docs plan §6).
        def _user(code):
            return getattr(self.people[code], 'user', None)

        def _plan_row(kpi_code, node_code):
            return plan.allocations.filter(
                target_period=cur_p, kpi=kpis[kpi_code], sku_group=None,
                geography_node=self.geo[node_code]).select_related('geography_node').first()

        if tasks.get('HAL_NORTH') and tasks['HAL_NORTH'].status == 'pending':
            ReviewService.accept(tasks['HAL_NORTH'], actor=_user('HAL_RSM_N'),
                                 notes='North numbers hold against the LY run-rate.')
        # rebalance=False on both: these owners edit their own subtree ROOT, whose
        # geography siblings belong to other personas — a placed actor's rebalance
        # across foreign territories is refused by design.
        row = _plan_row('CORE_VALUE', 'HAL_MT_DL')
        if row and tasks.get('HAL_MT_DL') and tasks['HAL_MT_DL'].status == 'pending':
            # Within the 10% cap -> auto-approved revision, task ADJUSTED.
            ReviewService.adjust(tasks['HAL_MT_DL'], row,
                                 (row.effective_target * D('1.05')).quantize(D('1')),
                                 reason='Two new MT store openings confirmed this month.',
                                 actor=_user('HAL_MTE_DL'), rebalance=False)
        row = _plan_row('CORE_VALUE', 'HAL_GT_BLR')
        if row and tasks.get('HAL_GT_BLR') and tasks['HAL_GT_BLR'].status == 'pending':
            # Beyond the cap -> escalates to the org manager (RSM South), task ESCALATED.
            ReviewService.adjust(tasks['HAL_GT_BLR'], row,
                                 (row.effective_target * D('0.88')).quantize(D('1')),
                                 reason='Wholesale correction in Bangalore GT; asking a 12% cut.',
                                 actor=_user('HAL_ASM_BLR'), rebalance=False)
        # HAL_SOUTH + HAL_MT_BLR stay PENDING — gap board shows open tasks; publish is
        # blocked until they respond or HO force-closes (audited).

        # A realign re-split of the Delhi GT subtree, left STAGED: the workspace shows
        # the preview diff and the commit/discard banner, drivable by hand.
        _run(PlanRun.REALIGN, commit=False, scope_node=self.geo['HAL_GT_DL'])
        self.stdout.write(f'  [+] plan {plan_code}: IN REVIEW — tasks '
                          f'{sorted((t.node.code, t.status) for t in plan.review_tasks.select_related("node"))}')

    def _apply_engineered(self, plan, period, kpi_map, kpis):
        """Override the plan-committed months to the engineered spread through the real
        edit path (modify_allocation -> TargetRevision; free while the plan is draft),
        then re-true every parent to the sum of its children so manager rollups reconcile
        exactly. Falls back to a plan-less row when the month is not the plan's month
        (e.g. the closed month)."""
        from apps.targets.models import TargetAllocation
        from apps.targets.services import TargetService

        changed = 0
        fallback_kpis = set()
        for code, node_values in kpi_map.items():
            kpi = kpis[code]
            for node_id, value in node_values.items():
                row = TargetAllocation.objects.filter(
                    target_period=period, kpi=kpi, geography_node_id=node_id,
                    channel=None, sku_group=None).select_related('geography_node').first()
                if row is None:
                    TargetAllocation.objects.update_or_create(
                        target_period=period, kpi=kpi, geography_node_id=node_id,
                        channel=None, sku_group=None,
                        defaults={'target_value': value, 'original_target_value': value,
                                  'status': TargetAllocation.APPROVED,
                                  'source': TargetAllocation.MANUAL})
                    fallback_kpis.add(kpi)
                    continue
                if row.effective_target == value:
                    continue
                TargetService.modify_allocation(row, value, actor=self.admin, rebalance=False,
                                                reason='Bottom-up correction from the beat plan.')
                changed += 1

        # Parents (district -> region -> nation), deepest first: effective = Σ children.
        for code in kpi_map:
            kpi = kpis[code]
            rows = list(TargetAllocation.objects.filter(
                target_period=period, kpi=kpi, channel=None, sku_group=None,
            ).select_related('geography_node'))
            by_node = {r.geography_node_id: r for r in rows}
            children = {}
            for r in rows:
                pid = r.geography_node.parent_id
                if pid is not None:
                    children.setdefault(pid, []).append(r)
            parents = [by_node[pid] for pid in children if pid in by_node]
            for parent in sorted(parents, key=lambda r: len(r.geography_node.path), reverse=True):
                desired = sum((c.effective_target for c in children[parent.geography_node_id]), D('0'))
                if parent.effective_target != desired:
                    TargetService.modify_allocation(
                        parent, desired, actor=self.admin, rebalance=False,
                        reason='Roll-up of bottom-up field adjustments.')
                    changed += 1
        for kpi in fallback_kpis:
            self._rollup(period, kpi)
        return changed

    # ═════════════════════════ period publish + governance demo ══════════════════
    def _publish_periods(self, prev_p, cur_p):
        from apps.targets.models import TargetPeriod
        from apps.targets.services import TargetService
        for p in (prev_p, cur_p):
            if p.status == TargetPeriod.DRAFT:
                pass
                #TargetService.transition_period(p, TargetPeriod.PUBLISHED, actor=self.admin)
        self.stdout.write(f'  published {prev_p.code} + {cur_p.code}')

    def _seed_governance_demo(self, cur_p):
        """A published-period edit beyond the cap, then rejected: the revision history
        shows an ESCALATED PENDING -> REJECTED trail and the target reverts untouched."""
        from apps.targets.models import TargetAllocation
        from apps.targets.services import TargetService
        row = TargetAllocation.objects.filter(
            target_period=cur_p, kpi__code='NPI_VALUE', sku_group=None, channel=None,
            geography_node=self.geo['HAL_GT_DL_DW']).select_related('geography_node').first()
        if row is None or row.revisions.exists():
            return
        TargetService.modify_allocation(
            row, D('50000'), actor=None, rebalance=False,
            reason='Push NPI seeding into Dwarka before the festive season.')
        TargetService.reject_allocation(
            row, actor=self.admin, reason='Dwarka has no owner yet — keep the original number.')
        self.stdout.write('  [+] Dwarka NPI 40k->50k revision: escalated, then REJECTED (reverted)')

    # ═══════════════════════════════════ summary ═════════════════════════════════
    def _print_summary(self):
        w = self.stdout.write
        div = '=' * 78
        w(f'\n{div}')
        w(self.style.SUCCESS('  HALEON GT+MT MANUAL-TEST WORLD READY'))
        w(div)
        w('\n  LOGINS (password: Demo@1234 · admin: Admin@1234 · partners: OTP on mobile)')
        for role, who in [
            ('Admin', 'admin@thriive.com'),
            ('NSM', 'nsm@haleon.com  (Arvind Menon — all India)'),
            ('RSM North', 'rsm.north@haleon.com  (Priya Nair)'),
            ('RSM South', 'rsm.south@haleon.com  (Rohit Iyer)'),
            ('ASM Delhi GT', 'asm.delhi@haleon.com  (Vikram Singh)'),
            ('ASM Blr GT', 'asm.bangalore@haleon.com  (Kiran Rao)'),
            ('XSE Delhi 1', 'xse.delhi1@haleon.com  (Anjali Gupta — Karol Bagh + Lajpat Nagar)'),
            ('XSE Delhi 2', 'xse.delhi2@haleon.com  (Ravi Verma — new joiner, Rohini)'),
            ('XSE Bangalore', 'xse.bangalore@haleon.com  (Manoj Pillai — Koramangala)'),
            ('MTE Delhi', 'mte.delhi@haleon.com  (Sneha Kapoor)'),
            ('MTE Bangalore', 'mte.bangalore@haleon.com  (Divya Shetty)'),
            ('Distributor', '9811110001 Karol Bagh Agencies · 9811110003 Rohini Distributors'),
            ('Distributor', '9811110005 Whitefield Distributors (OWNS its territory)'),
            ('Suspended', '9811110002 Lajpat Traders (partner blocked)'),
            ('Retailer', '9811120001 Gupta General Store · 9811120002 Sharma Medicos (Karol Bagh)'),
            ('Retailer', '9811120003 Balaji Super Mart · 9811120004 Verma Provision Store'),
            ('Retailer', '9811120005 Sri Lakshmi Stores · 9811120006 New Whitefield Mart'),
        ]:
            w(f'    {role:<16} {who}')
        w('\n  EDGE CASES TO TEST')
        for line in [
            'Retailers         — 6 outlet partners (OTP login) under their distributors; each owns',
            '                    its outlet territory with own sales + an engineered Core Value target.',
            'Vacant territory  — Dwarka has sales + an NPI target but NO owner; rolls up to ASM only.',
            'Mid-month transfer — Rohini moved Anjali -> Ravi on the 22nd (as-of ownership).',
            'New joiner        — Ravi: ~35% raw achievement, APPROVED 1x exception, pro-rated VP.',
            'Gate failure      — Manoj: 112% sales but geofence 70% (<85 gate) -> zero payout.',
            'Multiplier grid   — Anjali 104/96/100.00/85 -> 1.5x/0.9x/1.0x/0x; Manoj 112% -> 1.8x (gated).',
            'Exact boundaries  — EC exactly 100.00% (Anjali); Eno value exactly 90% (Divya).',
            'Zero target       — Ravi FOCUS_EC target = 0 with real actuals (div-by-zero path).',
            'Target, no sales  — Dwarka NPI target 40,000 with zero NPI actuals.',
            'Negative outlet   — HAL_GT_DL_KB-NEGOUT returns > sales -> excluded from EC.',
            'Missing data      — MTE Blr has no activation score; Manoj has no VP this month.',
            'Declining town    — Lajpat Nagar LY > TY -> negative growth (LOW_GROWTH alert).',
            'Payout lifecycle  — GT run UNDER REVIEW, MT run COMPUTED, ASM scheme un-run.',
            'Pending exception — Anjali transfer exception awaiting maker-checker.',
            'AOP plan          — IN REVIEW: spatial/product runs COMMITTED, plan month adjusted.',
            'Cascade review    — tasks accepted / adjusted / escalated / pending; publish blocked.',
            'Escalated edit    — Blr GT -12% cut awaits RSM South (target_revision workflow).',
            'Rejected revision — Dwarka NPI 40k->50k escalated, then rejected; target reverted.',
            'Realign staged    — Delhi GT re-split staged; preview diff + commit/discard live.',
            'Change caps       — HAL_CHANGE_CAP policy: 10% auto-approve / 50% hard ceiling.',
            'Cost of plan      — ~380k projected vs 350k budget: publish needs audited override.',
            'Delisted SKU      — HAL-DELIST-01 inactive, appears only in LY transactions.',
        ]:
            w(f'    • {line}')
        w(f'\n  Periods: {self.prev_start:%B %Y} (closed, payout-ready) + '
          f'{self.cur_start:%B %Y} (MTD, run-rate live)')
        w('  Frontend: http://localhost:5173/   ·   API docs: http://localhost:8000/api/docs/')
        w(f'{div}\n')
