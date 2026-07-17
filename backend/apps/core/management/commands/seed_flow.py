"""Seed the Haleon manual-testing ORG + MASTER DATA world — GT + MT channels only.

Trimmed scope: this seed only builds the foundational configuration and org data —
no transactions, targets, plans, achievements, SIP schemes, or payouts.

Builds: channels → product master (SKUs, SKU groups, UOM conversions) → role types
(NodeTypes) → geography (territories) → org tree + users (with geography ownership
assignments) → KPI definitions.

    python manage.py seed_haleon --reset      # wipe business data, build the world
    python manage.py seed_haleon              # additive / top-up (idempotent)

Illustrative *configuration + data*, not platform logic — a real deployment loads its
own via the UI, bulk import, or the push APIs.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
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

# ── geography / territories (each channel force owns its own subtree) ─────────
# code, name, level, parent
GEO_SPEC = [
    ('HAL_IN', 'India', 'nation', None),
    ('HAL_NORTH', 'North', 'region', 'HAL_IN'),
    ('HAL_SOUTH', 'South', 'region', 'HAL_IN'),
    ('HAL_GT_DL', 'Delhi GT Area', 'district', 'HAL_NORTH'),
    ('HAL_GT_DL_KB', 'Karol Bagh', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_LN', 'Lajpat Nagar', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_RH', 'Rohini', 'town', 'HAL_GT_DL'),
    ('HAL_GT_DL_DW', 'Dwarka', 'town', 'HAL_GT_DL'),          # vacant — no owner
    ('HAL_MT_DL', 'Delhi MT Area', 'district', 'HAL_NORTH'),   # MT works at district grain
    ('HAL_GT_BLR', 'Bangalore GT Area', 'district', 'HAL_SOUTH'),
    ('HAL_GT_BLR_KM', 'Koramangala', 'town', 'HAL_GT_BLR'),
    ('HAL_GT_BLR_WF', 'Whitefield', 'town', 'HAL_GT_BLR'),     # owned by a DISTRIBUTOR
    ('HAL_MT_BLR', 'Bangalore MT Area', 'district', 'HAL_SOUTH'),
    # Retail outlets under their towns.
    ('HAL_GT_DL_KB-OUT1', 'Gupta General Store', 'outlet', 'HAL_GT_DL_KB'),
    ('HAL_GT_DL_KB-OUT2', 'Sharma Medicos', 'outlet', 'HAL_GT_DL_KB'),
    ('HAL_GT_DL_LN-OUT1', 'Balaji Super Mart', 'outlet', 'HAL_GT_DL_LN'),
    ('HAL_GT_DL_RH-OUT1', 'Verma Provision Store', 'outlet', 'HAL_GT_DL_RH'),
    ('HAL_GT_BLR_KM-OUT1', 'Sri Lakshmi Stores', 'outlet', 'HAL_GT_BLR_KM'),
    ('HAL_GT_BLR_WF-OUT1', 'New Whitefield Mart', 'outlet', 'HAL_GT_BLR_WF'),
]

# Retailer partners (OTP login, partner portal), one per outlet above.
# code → (name, outlet geo code, distributor parent code, mobile, gstin)
RETAILERS = {
    'HAL_RET_KB1': ('Gupta General Store', 'HAL_GT_DL_KB-OUT1', 'HAL_DIST_KB', '9811120001', '07AAHRG6666F1Z6'),
    'HAL_RET_KB2': ('Sharma Medicos', 'HAL_GT_DL_KB-OUT2', 'HAL_DIST_KB', '9811120002', '07AAHRS7777G1Z7'),
    'HAL_RET_LN1': ('Balaji Super Mart', 'HAL_GT_DL_LN-OUT1', 'HAL_DIST_LN', '9811120003', '07AAHRB8888H1Z8'),
    'HAL_RET_RH1': ('Verma Provision Store', 'HAL_GT_DL_RH-OUT1', 'HAL_DIST_RH', '9811120004', '07AAHRV9999J1Z9'),
    'HAL_RET_KM1': ('Sri Lakshmi Stores', 'HAL_GT_BLR_KM-OUT1', 'HAL_DIST_KM', '9811120005', '29AAHRL1010K1Z0'),
    'HAL_RET_WF1': ('New Whitefield Mart', 'HAL_GT_BLR_WF-OUT1', 'HAL_DIST_WF', '9811120006', '29AAHRN2020L1Z1'),
}

# ── KPIs (RFP set, minus anything needing the excluded channels) ───────────────
APPLIES = ['nsm', 'rsm', 'asm', 'xse', 'mte', 'dist', 'ret']


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


class Command(BaseCommand):
    help = ('Seed the Haleon GT+MT org + master-data world (channels, products, roles, '
            'territories, users, KPIs). --reset wipes first.')

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Wipe org/master business data before seeding.')

    def handle(self, *args, **options):
        self._seed(options)
        self._print_summary()

    @transaction.atomic
    def _seed(self, options):
        today = date.today()
        self.today = today
        self.prev_start = today.replace(day=1) - timedelta(days=1)
        self.prev_start = self.prev_start.replace(day=1)
        # Assignments open at the LY fiscal start so every "as of" date in the demo resolves.
        self.epoch = date(self.prev_start.year - 1, 4, 1)

        if options['reset']:
            self._reset()

        self._h('Infra seeds (roles, settings)')
        for cmd in ('seed_roles', 'seed_settings'):
            call_command(cmd, verbosity=0)
        self.stdout.write('  ok')
        self._ensure_admin()

        self._h('Channels + product master')
        self._seed_channels()
        self._seed_master_data()

        self._h('Role types + territories + users')
        et = self._seed_entity_types()
        geo = self._seed_geography()
        self.geo = geo
        people = self._seed_people(et, geo)
        self.people = people

        self._h('KPIs')
        self._seed_kpis()

    def _h(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n--- {title} ---'))

    # ═══════════════════════════════════════ reset ═══════════════════════════════
    def _reset(self):
        """Complete reset — wipes ALL business data (not just what this trimmed seed
        creates), so --reset always leaves a fully clean slate even if the database
        was previously populated by a fuller version of this seed (transactions,
        targets, plans, achievements, SIP schemes, payouts, workflows, etc.)."""
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

        self._h('Reset (wiping ALL business data)')
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
        # Delisted SKU — inactive master, kept for historic-data testing.
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
        self.stdout.write(f'  SKUs: {SKU.objects.count()}, groups: FOCUS/NPI/ENO/FOCUS_NPI, '
                          f'UOM conversions: {len(UOM_CONVERSIONS)}')

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
        self.stdout.write(f'  territories: {len(nodes)} nodes incl. {len(RETAILERS)} retail outlets '
                          '(Dwarka left VACANT)')
        return nodes

    def _seed_people(self, et, geo):
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
        # tree, each OWNING its outlet territory.
        for code, (name, outlet, dist_code, mobile, gstin) in RETAILERS.items():
            _person(code, name, 'ret', '', [outlet], parent=people[dist_code],
                    mobile=mobile, attrs={'gstin': gstin})

        # Suspended partner — appears in the tree, blocked from the portal.
        if dist_ln.status != 'suspended':
            dist_ln.status = 'suspended'
            dist_ln.save(update_fields=['status', 'updated_at'])

        # Backdate every owner assignment to the LY fiscal start so as-of resolution
        # works — EXCEPT the new joiner's (kept at his join date via the transfer below).
        from apps.assignments.models import Assignment
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
        self.stdout.write(f'  KPIs: {created} created ({len(KPIS)} total)')

    # ═══════════════════════════════════ summary ═════════════════════════════════
    def _print_summary(self):
        w = self.stdout.write
        div = '=' * 78
        w(f'\n{div}')
        w(self.style.SUCCESS('  HALEON GT+MT ORG + MASTER DATA WORLD READY'))
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
            'Retailers         — 6 outlet partners (OTP login) under their distributors.',
            'Vacant territory  — Dwarka has no owner; rolls up to ASM only.',
            'Mid-month transfer — Rohini moved Anjali -> Ravi on the 22nd (as-of ownership).',
            'New joiner        — Ravi joined after the day-20 cutoff.',
            'Multi-territory   — Anjali owns two towns (Karol Bagh + Lajpat Nagar).',
            'Distributor-owned — Whitefield Distributors owns its own territory.',
            'Suspended partner — Lajpat Traders is blocked from the portal.',
            'Delisted SKU      — HAL-DELIST-01 is inactive in the product master.',
        ]:
            w(f'    • {line}')
        w('  Frontend: http://localhost:5173/   ·   API docs: http://localhost:8000/api/docs/')
        w(f'{div}\n')