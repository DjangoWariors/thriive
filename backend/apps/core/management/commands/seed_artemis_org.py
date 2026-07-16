"""Seed the Haleon "Project Artemis" ORG hierarchy — roles, people, geography, assignments.

The generic FMCG demo (`seed_demo`) gives NSM→RSM→ASM→ASE→Distributor→Retailer, which doesn't
match Haleon's channel personas (Expert, GT XSE/ASM, MT, Ecom). This seeds the Artemis org so the
KPI builder's "applies to which roles" picker and the preview "person/team" selector show Haleon
roles, and the seeded Artemis sales roll up to a real Haleon field rep.

Per-client isolation (one DB per client) means a Haleon deployment should *have* the Haleon org,
so `--reset` wipes the FMCG demo first. Without it the command is additive (and may collide on
shared role codes). Re-runnable. Pairs with `seed_artemis_kpis` (run that first for the KPIs).

Org modelled from the RFP SIP structures:

    NSM ─ RSM ─┬─ ASM (GT)  ─ XSE (GT)
               ├─ ESM (Expert) ─ ESE (Expert)
               ├─ MTE (Modern Trade)
               └─ ECE (E-commerce)
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

TODAY = date.today().isoformat()

# entity-type code → (name, level_order, parents, children, channel, leaf, role_code, icon, color)
ROLE_SPECS = [
    ('nsm', 'National Sales Manager', 1, [], ['rsm'], None, False, 'national_head', 'crown', '#1e40af'),
    ('rsm', 'Regional Sales Manager', 2, ['nsm'], ['asm', 'esm', 'mte', 'ece'], None, False, 'regional_manager', 'user-tie', '#7c3aed'),
    ('asm', 'Area Sales Manager (GT)', 3, ['rsm'], ['xse'], 'GT', False, 'area_manager', 'briefcase', '#059669'),
    ('xse', 'Xpress Sales Executive (GT)', 4, ['asm'], [], 'GT', True, 'sales_exec', 'user', '#d97706'),
    ('esm', 'Expert Sales Manager', 3, ['rsm'], ['ese'], 'EXPERT', False, 'area_manager', 'stethoscope', '#0891b2'),
    ('ese', 'Expert Sales Executive', 4, ['esm'], [], 'EXPERT', True, 'sales_exec', 'user-md', '#0d9488'),
    ('mte', 'Modern Trade Executive', 3, ['rsm'], [], 'MT', True, 'sales_exec', 'shopping-cart', '#c026d3'),
    ('ece', 'E-commerce Executive', 3, ['rsm'], [], 'ECOM', True, 'sales_exec', 'globe', '#ea580c'),
]

FF_SCHEMA = [
    {'key': 'employee_id', 'label': 'Employee ID', 'type': 'string', 'required': True, 'unique': True},
    {'key': 'joining_date', 'label': 'Date of Joining', 'type': 'date', 'required': False, 'unique': False},
]


class Command(BaseCommand):
    help = 'Seed the Haleon Artemis org hierarchy (roles, people, geography, assignments).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Wipe the existing org (entities, types, geography, non-staff users) first.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self._reset()
        call_command('seed_roles', verbosity=0)
        self._ensure_channels()
        et = self._seed_entity_types()
        geo = self._seed_geography()
        reps = self._seed_people(et, geo)
        self._seed_demo_sales(geo)
        self.stdout.write(self.style.SUCCESS(
            f'\nArtemis org ready — {len(et)} roles, {len(reps)} people. '
            f'Test KPIs against e.g. XSE "{reps["xse"].code}" or ESE "{reps["ese"].code}".'))

    # ── reset ────────────────────────────────────────────────────────────────
    def _reset(self):
        from apps.accounts.models import User
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import (
            Node, NodeRelationship, NodeType, GeographyNode, GeographyType,
        )
        from apps.kpi_engine.models import Transaction
        # Assignment has protected FKs to Node (assignee) and GeographyNode (scope) — clear first.
        Assignment.objects.all().delete()
        NodeRelationship.objects.all().delete()
        Node.objects.all().delete()
        NodeType.objects.all().delete()
        GeographyNode.objects.all().delete()
        GeographyType.objects.all().delete()
        User.objects.filter(is_superuser=False, is_staff=False).delete()
        # Drop demo sales whose attributed nodes are about to be recreated.
        Transaction.objects.filter(external_ref__startswith='ART-DEMO').delete()
        self.stdout.write(self.style.WARNING('  Reset: org + geography + demo sales cleared.'))

    # ── channels ─────────────────────────────────────────────────────────────
    def _ensure_channels(self):
        from apps.hierarchy.models import Channel
        for code, name in [('GT', 'General Trade'), ('MT', 'Modern Trade'),
                           ('ECOM', 'E-commerce'), ('EXPERT', 'Expert'), ('NHDD', 'NHDD')]:
            Channel.objects.get_or_create(code=code, defaults={'name': name})

    # ── entity types (roles) ─────────────────────────────────────────────────
    def _seed_entity_types(self):
        from apps.accounts.models import Role
        from apps.hierarchy.models import Channel, NodeType
        et = {}
        for code, name, lvl, parents, children, ch, leaf, role_code, icon, color in ROLE_SPECS:
            existing = NodeType.objects.filter(code=code, is_current=True).first()
            if existing:
                et[code] = existing
                self.stdout.write(f'  [~] role {code}: {name}')
                continue
            et[code] = NodeType.objects.create(
                name=name, code=code, level_order=lvl,
                allowed_parent_types=parents, allowed_child_types=children,
                attribute_schema=FF_SCHEMA,
                is_loginable=True, incentive_eligible=True, is_leaf=leaf,
                default_role=Role.objects.filter(code=role_code, is_active=True).first(),
                channel=Channel.objects.filter(code=ch).first() if ch else None,
                display_config={'color': color, 'portal_type': 'admin',
                                'login_method': 'password_and_otp', 'show_in_tree': True,
                                'icon': icon, 'card_fields': ['employee_id']},
                effective_from=date.today(), version=1, is_current=True,
            )
            self.stdout.write(self.style.SUCCESS(f'  [+] role {code}: {name}'))
        return et

    # ── geography ────────────────────────────────────────────────────────────
    def _seed_geography(self):
        from apps.hierarchy.config_services import GeographyNodeService, GeographyTypeService
        from apps.hierarchy.models import GeographyNode, GeographyType
        gt = GeographyType.objects.filter(code='sales_geo').first() or GeographyTypeService.create({
            'name': 'Sales Geography', 'code': 'sales_geo',
            'levels': ['nation', 'region', 'district', 'town'],
        })
        nodes = {}

        def _node(code, name, level, parent_code=None):
            existing = GeographyNode.objects.filter(code=code, is_active=True).first()
            nodes[code] = existing or GeographyNodeService.create({
                'geography_type': gt, 'name': name, 'code': code, 'level': level,
                'parent': nodes.get(parent_code) if parent_code else None,
            })
            return nodes[code]

        # Each channel field force owns its OWN geography subtree (one owner per node), so a
        # manager and its executive never collide on the same territory.
        _node('HAL_IN', 'India', 'nation')
        _node('HAL_NORTH', 'North', 'region', 'HAL_IN')
        for area, town, area_name in [
            ('HAL_GT_DL', 'HAL_GT_TOWN', 'Delhi GT'),
            ('HAL_EXP_DL', 'HAL_EXP_TOWN', 'Delhi Expert'),
            ('HAL_MT_DL', 'HAL_MT_TOWN', 'Delhi MT'),
            ('HAL_ECOM_DL', 'HAL_ECOM_TOWN', 'Delhi Ecom'),
        ]:
            _node(area, f'{area_name} Area', 'district', 'HAL_NORTH')
            _node(town, f'{area_name} Town', 'town', area)
        return nodes

    # ── people + owning assignments ──────────────────────────────────────────
    def _seed_people(self, et, geo):
        from apps.assignments.services import AssignmentService
        from apps.hierarchy.models import Node
        reps = {}

        def _person(code, name, type_code, emp, geo_code, parent=None, channel_code='GT'):
            from apps.hierarchy.models import Channel
            existing = Node.objects.filter(code=code, is_current=True).first()
            if existing:
                reps[type_code] = existing
                return existing
            from apps.hierarchy.services import NodeService
            data = {
                'entity_type_id': et[type_code].id, 'name': name, 'code': code,
                'attributes': {'employee_id': emp}, 'effective_from': TODAY,
                'channel_id': Channel.objects.get(code=channel_code).pk,
                'email': f'{code.lower()}@haleon.com',
            }
            if parent:
                data['parent_id'] = parent.id
            if AssignmentService.owner_of(geo[geo_code].pk, on=date.today()) is None:
                data['owned_scope_ids'] = [geo[geo_code].pk]
            node = NodeService.create_entity(data, user=None)
            reps[type_code] = node
            self.stdout.write(self.style.SUCCESS(f'  [+] {code}: {name} ({type_code})'))
            return node

        nsm = _person('HAL_NSM', 'Haleon NSM', 'nsm', 'HAL001', 'HAL_IN')
        rsm = _person('HAL_RSM_N', 'North RSM', 'rsm', 'HAL002', 'HAL_NORTH', parent=nsm)
        asm = _person('HAL_ASM_DL', 'Delhi ASM', 'asm', 'HAL003', 'HAL_GT_DL', parent=rsm)
        _person('HAL_XSE_DL', 'Delhi XSE', 'xse', 'HAL004', 'HAL_GT_TOWN', parent=asm, channel_code='GT')
        esm = _person('HAL_ESM_DL', 'Delhi Expert SM', 'esm', 'HAL005', 'HAL_EXP_DL', parent=rsm, channel_code='EXPERT')
        _person('HAL_ESE_DL', 'Delhi Expert SE', 'ese', 'HAL006', 'HAL_EXP_TOWN', parent=esm, channel_code='EXPERT')
        _person('HAL_MTE_DL', 'Delhi MT Exec', 'mte', 'HAL007', 'HAL_MT_TOWN', parent=rsm, channel_code='MT')
        _person('HAL_ECE_DL', 'Delhi Ecom Exec', 'ece', 'HAL008', 'HAL_ECOM_TOWN', parent=rsm, channel_code='ECOM')
        return reps

    # ── demo sales (per channel, onto the owning territory) ──────────────────
    def _seed_demo_sales(self, geo):
        from apps.kpi_engine.models import Transaction
        skus = ['ART-CORE', 'ART-FOCUS', 'ART-NPI', 'ART-ENO']
        today = date.today()
        rows = []

        def _sale(node_code, channel, i, sku, net):
            rows.append(Transaction(
                attributed_node_id=geo[node_code].pk, transaction_date=today - timedelta(days=i),
                transaction_type=Transaction.SALE, transaction_level=Transaction.SECONDARY,
                channel_code=channel, sku_code=sku, outlet_code=f'{node_code}-OUT{i % 4}',
                bill_ref=f'ART-DEMO-{node_code}-{i}', gross_amount=net + Decimal('100'),
                net_amount=net, quantity=Decimal('5'), uom='cases', source='manual_entry',
                external_ref=f'ART-DEMO-{node_code}-{i}',
            ))

        for i in range(8):  # GT secondary → XSE
            _sale('HAL_GT_TOWN', 'GT', i, skus[i % 4], Decimal('1000'))
        for i in range(4):  # Expert + NHDD → ESE
            _sale('HAL_EXP_TOWN', 'EXPERT' if i % 2 else 'NHDD', i, 'ART-ENO', Decimal('800'))
        for i in range(3):  # MT → MTE
            _sale('HAL_MT_TOWN', 'MT', i, skus[i % 4], Decimal('1500'))
        for i in range(3):  # Ecom → ECE
            _sale('HAL_ECOM_TOWN', 'ECOM', i, skus[i % 4], Decimal('1200'))
        Transaction.objects.bulk_create(rows, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(f'  Demo sales: {len(rows)} rows across GT/Expert/NHDD/MT/Ecom.'))
