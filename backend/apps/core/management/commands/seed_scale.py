"""
Seed a large hierarchy (~200k entities) for load/scale testing.

Builds a realistic "mix of both" shape: a deep sales-force tree
(NSM → RSM → ASM → ASE → Distributor) with a wide partner network
(Retailers) hanging off the bottom — exactly the case the hierarchy
module was hardened for.

Uses bulk_create with manually computed materialized paths. It deliberately
does NOT go through NodeService.create_entity: that validates attributes and
auto-creates a User per loginable entity, which would be far too slow and would
spawn 200k user accounts. This seed targets the hierarchy read/move endpoints,
not auth — so the entities have no linked users.

Prerequisite: entity types nsm/rsm/asm/ase/distributor/retailer must exist.
Run `python manage.py seed_demo` first.

Examples:
    python manage.py seed_scale                       # ~200k, default shape
    python manage.py seed_scale --total 50000         # smaller run
    python manage.py seed_scale --purge               # drop a previous scale batch first
    python manage.py seed_scale --total 150000 --geography 150000 --assign
                                                      # + mirrored territory tree and
                                                      #   owner assignments (compute smoke)

The FULL capacity-proof world (200k outlets, ~9k workforce logins, 2M sales lines,
a published town-grain plan and SIP schemes with variable pay):

    python manage.py seed_scale --purge --total 210000 \
        --rsm 10 --asm-per 10 --ase-per 10 --dist-per 8 --assign \
        --users --transactions 2000000 --month 2026-06 --plan --schemes
"""
import calendar as _calendar
import math
import time
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

TODAY = date.today()
# Ownership must predate the plan/transaction month (achievements resolve owners as-of
# period end) — not "today", which can postdate the benchmarked month entirely.
ASSIGN_FROM = date(2025, 1, 1)
TYPE_CODES = ['nsm', 'rsm', 'asm', 'ase', 'distributor', 'retailer']
STORE_CLASSES = ['A', 'B', 'C', 'D']


class Command(BaseCommand):
    help = 'Seed a large hierarchy (~200k entities) for scale/load testing. Run seed_demo first.'

    def add_arguments(self, parser):
        parser.add_argument('--total', type=int, default=200_000,
                            help='Approximate total entities to create (default 200000).')
        parser.add_argument('--rsm', type=int, default=5, help='RSMs under the NSM.')
        parser.add_argument('--asm-per', type=int, default=8, help='ASMs per RSM.')
        parser.add_argument('--ase-per', type=int, default=10, help='ASEs per ASM.')
        parser.add_argument('--dist-per', type=int, default=5, help='Distributors per ASE.')
        parser.add_argument('--prefix', default='SCALE',
                            help='Code prefix namespacing this batch (enables --purge).')
        parser.add_argument('--purge', action='store_true',
                            help='Delete entities whose code starts with the prefix, then seed.')
        parser.add_argument('--batch', type=int, default=5000, help='bulk_create batch size.')
        parser.add_argument('--geography', type=int, default=0, metavar='N',
                            help='Also build a territory tree with ~N nodes '
                                 '(nation→region→district→town→beat→outlet, mirrored shape).')
        parser.add_argument('--assign', action='store_true',
                            help='Open owner Assignments linking the org tree to the territory '
                                 'tree (managers→upper levels, retailers→outlets 1:1). '
                                 'Implies --geography when N not given.')
        parser.add_argument('--users', action='store_true',
                            help='Create login Users (+ a team-level field role) for every '
                                 'management-tree entity (NSM…Distributor).')
        parser.add_argument('--transactions', type=int, default=0, metavar='N',
                            help='Seed N sale lines in --month across the outlets, plus N/10 '
                                 'lines in the same month last year (baseline history). '
                                 'Needs --assign/--geography.')
        parser.add_argument('--month', default='2026-06', metavar='YYYY-MM',
                            help='The plan/transaction month (default 2026-06).')
        parser.add_argument('--plan', action='store_true',
                            help='Create a KPI + recipe + town-grain plan rooted at the seeded '
                                 'nation, run + commit the territory split, and publish it.')
        parser.add_argument('--schemes', action='store_true',
                            help='Create monthly SIP schemes (ASE + Distributor) with tiers and '
                                 'VariablePay rows for the plan month. Needs --plan.')

    def handle(self, *args, **opts):
        from apps.hierarchy.models import Channel, Node, NodeType

        types = {c: NodeType.objects.filter(code=c, is_current=True).first() for c in TYPE_CODES}
        for order, code in enumerate(TYPE_CODES, start=1):
            if types[code] is None:  # self-sufficient on a fresh DB — no seed_demo needed
                types[code] = NodeType.objects.create(
                    name=code.upper(), code=code, level_order=order, effective_from=TODAY,
                    is_loginable=code != 'retailer',
                    incentive_eligible=code in ('ase', 'distributor'),
                )
                self.stdout.write(f'  [+] entity type {code} created')
        channel = Channel.objects.filter(code='GT').first()

        prefix = opts['prefix']
        batch = opts['batch']

        if opts['purge']:
            self._purge(prefix)

        n_rsm = opts['rsm']
        n_asm = n_rsm * opts['asm_per']
        n_ase = n_asm * opts['ase_per']
        n_dist = n_ase * opts['dist_per']
        mgmt_total = 1 + n_rsm + n_asm + n_ase + n_dist
        if n_dist == 0:
            raise CommandError('Tree shape yields zero distributors; raise --rsm/--asm-per/etc.')

        remaining = max(0, opts['total'] - mgmt_total)
        ret_per = math.ceil(remaining / n_dist)

        self.stdout.write(
            f'\n  Shape: 1 NSM -> {n_rsm} RSM -> {n_asm} ASM -> {n_ase} ASE -> '
            f'{n_dist} Distributor -> ~{remaining} Retailer (~{ret_per}/dist)'
        )
        self.stdout.write(f'  Target total ~ {mgmt_total + remaining}\n')

        started = time.monotonic()

        def make(et, code, name, parent):
            ppath = f'{parent.path}{code}/' if parent else f'/{code}/'
            return Node(
                entity_type=et, name=name, code=code, parent=parent,
                attributes={}, channel=channel,
                path=ppath, depth=(parent.depth + 1) if parent else 0,
                status='active', version=1, is_current=True,
                effective_from=TODAY, is_active=True,
            )

        def create_level(label, parents, et, per, code_tag):
            """Create `per` children under each parent; return the new rows."""
            out = []
            buf = []
            seq = 0
            for parent in parents:
                for _ in range(per):
                    seq += 1
                    code = f'{prefix}-{code_tag}-{seq:07d}'
                    buf.append(make(et, code, f'{label} {seq}', parent))
                    if len(buf) >= batch:
                        out.extend(Node.objects.bulk_create(buf, batch_size=batch))
                        buf = []
            if buf:
                out.extend(Node.objects.bulk_create(buf, batch_size=batch))
            self.stdout.write(self.style.SUCCESS(f'  [+] {label:<12} {len(out):>8}'))
            return out

        # ── Management tree (kept in memory; small) ───────────────────────────
        nsm = Node.objects.bulk_create([make(types['nsm'], f'{prefix}-NSM-0000001', 'NSM 1', None)])[0]
        rsms = create_level('RSM', [nsm], types['rsm'], opts['rsm'], 'RSM')
        asms = create_level('ASM', rsms, types['asm'], opts['asm_per'], 'ASM')
        ases = create_level('ASE', asms, types['ase'], opts['ase_per'], 'ASE')
        dists = create_level('Distributor', ases, types['distributor'], opts['dist_per'], 'DIST')

        # ── Retailers (the wide tail; streamed, capped at `remaining`) ────────
        made = 0
        seq = 0
        buf = []
        for d in dists:
            if made >= remaining:
                break
            for _ in range(ret_per):
                if made >= remaining:
                    break
                seq += 1
                made += 1
                code = f'{prefix}-RET-{seq:07d}'
                e = make(types['retailer'], code, f'Retailer {seq}', d)
                e.attributes = {'store_class': STORE_CLASSES[seq % 4]}
                buf.append(e)
                if len(buf) >= batch:
                    Node.objects.bulk_create(buf, batch_size=batch)
                    buf = []
        if buf:
            Node.objects.bulk_create(buf, batch_size=batch)
        self.stdout.write(self.style.SUCCESS(f'  [+] {"Retailer":<12} {made:>8}'))

        total = 1 + len(rsms) + len(asms) + len(ases) + len(dists) + made
        elapsed = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(
            f'\n  Done: {total} entities in {elapsed:.1f}s. Root = {nsm.code} (id={nsm.id}).'
        ))
        self.stdout.write(
            '  Try:  GET /api/v1/entities/{}/subtree/   (paginated)\n'
            '        POST /api/v1/entities/{}/move/      (set-based, constant queries)\n'.format(nsm.id, dists[0].id)
        )

        # ── Optional: mirrored territory tree + the ownership bridge ──────────
        org_levels = {'nsm': [nsm], 'rsm': rsms, 'asm': asms, 'ase': ases, 'dist': dists}
        geo_total = opts['geography'] or (opts['total'] if opts['assign'] else 0)
        geo = None
        if geo_total:
            geo = self._seed_geography_and_assignments(
                prefix=prefix, batch=batch, geo_total=geo_total, assign=opts['assign'],
                org_levels=org_levels, retailer_prefix=f'{prefix}-RET-',
            )

        # ── Optional workload: users, a month of sales, a published plan, SIP ─
        if opts['users']:
            self._seed_users(prefix=prefix, batch=batch, org_levels=org_levels)
        if opts['transactions']:
            if geo is None:
                raise CommandError('--transactions needs --assign/--geography (sales attach to outlets).')
            self._seed_transactions(prefix=prefix, batch=batch, n=opts['transactions'],
                                    month=opts['month'], outlet_ids=geo['outlet_ids'])
        if opts['plan']:
            if geo is None:
                raise CommandError('--plan needs --assign/--geography (the plan roots at the seeded nation).')
            plan, kpi = self._seed_plan(prefix=prefix, month=opts['month'], nation=geo['nation'])
            if opts['schemes']:
                self._seed_schemes(prefix=prefix, batch=batch, period=plan.period, kpi=kpi,
                                   org_levels=org_levels, types=types)
        elif opts['schemes']:
            raise CommandError('--schemes needs --plan (variable pay anchors to the plan month).')

    def _seed_geography_and_assignments(self, *, prefix, batch, geo_total, assign,
                                        org_levels, retailer_prefix):
        """Territory tree mirroring the org fan-out, then 1:1 owner assignments.

        Exercises the geography indexes, the set-based geo move, and (via
        retailer→outlet ownership) the batched achievement resolver — the exact
        150k hot paths this seed exists to smoke-test.
        """
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import GeographyNode, GeographyType, Node

        started = time.monotonic()
        geo_type, _ = GeographyType.objects.get_or_create(
            code='scale_geo',
            defaults={'name': 'Scale Geography',
                      'levels': ['nation', 'region', 'district', 'town', 'beat', 'outlet']},
        )

        def gmake(name, code, level, parent):
            return GeographyNode(
                geography_type=geo_type, name=name, code=code, level=level, parent=parent,
                path=f'{parent.path}{code}/' if parent else f'/{code}/',
                depth=(parent.depth + 1) if parent else 0,
                attributes={}, is_active=True,
            )

        def gcreate(label, parents, level, per, tag):
            out, buf, seq = [], [], 0
            for parent in parents:
                for _ in range(per):
                    seq += 1
                    code = f'{prefix}-GEO-{tag}-{seq:07d}'
                    buf.append(gmake(f'{label} {seq}', code, level, parent))
                    if len(buf) >= batch:
                        out.extend(GeographyNode.objects.bulk_create(buf, batch_size=batch))
                        buf = []
            if buf:
                out.extend(GeographyNode.objects.bulk_create(buf, batch_size=batch))
            self.stdout.write(self.style.SUCCESS(f'  [+] geo {label:<9} {len(out):>8}'))
            return out

        # Mirror the org fan-out one-to-one so --assign can zip levels together.
        nation = GeographyNode.objects.bulk_create(
            [gmake('Nation 1', f'{prefix}-GEO-NAT-0000001', 'nation', None)])[0]
        regions = gcreate('Region', [nation], 'region', len(org_levels['rsm']), 'REG')
        districts = gcreate('District', regions, 'district',
                            max(1, len(org_levels['asm']) // max(1, len(regions))), 'DST')
        towns = gcreate('Town', districts, 'town',
                        max(1, len(org_levels['ase']) // max(1, len(districts))), 'TWN')
        beats = gcreate('Beat', towns, 'beat',
                        max(1, len(org_levels['dist']) // max(1, len(towns))), 'BEA')

        upper = 1 + len(regions) + len(districts) + len(towns) + len(beats)
        n_outlets = max(0, geo_total - upper)
        per_beat = math.ceil(n_outlets / max(1, len(beats)))
        made, seq, buf = 0, 0, []
        outlet_ids: list[int] = []
        for b in beats:
            if made >= n_outlets:
                break
            for _ in range(per_beat):
                if made >= n_outlets:
                    break
                seq += 1
                made += 1
                buf.append(gmake(f'Outlet {seq}', f'{prefix}-GEO-OUT-{seq:07d}', 'outlet', b))
                if len(buf) >= batch:
                    outlet_ids.extend(o.pk for o in GeographyNode.objects.bulk_create(buf, batch_size=batch))
                    buf = []
        if buf:
            outlet_ids.extend(o.pk for o in GeographyNode.objects.bulk_create(buf, batch_size=batch))
        self.stdout.write(self.style.SUCCESS(f'  [+] geo {"Outlet":<9} {made:>8}'))

        result = {'nation': nation, 'outlet_ids': outlet_ids}
        if not assign:
            self.stdout.write(self.style.SUCCESS(
                f'  Geography done: {upper + made} nodes in {time.monotonic() - started:.1f}s.'))
            return result

        # ── The bridge: managers own upper levels, retailers own outlets 1:1 ──
        def zip_assign(entities, scopes):
            return [
                Assignment(assignee=e, scope=s, role_in_scope='owner',
                           effective_from=ASSIGN_FROM, reason='seed_scale', is_active=True)
                for e, s in zip(entities, scopes)
            ]

        rows = [Assignment(assignee=org_levels['nsm'][0], scope=nation, role_in_scope='owner',
                           effective_from=ASSIGN_FROM, reason='seed_scale', is_active=True)]
        rows += zip_assign(org_levels['rsm'], regions)
        rows += zip_assign(org_levels['asm'], districts)
        rows += zip_assign(org_levels['ase'], towns)
        rows += zip_assign(org_levels['dist'], beats)
        Assignment.objects.bulk_create(rows, batch_size=batch)

        retailer_ids = list(
            Node.objects.filter(code__startswith=retailer_prefix, is_current=True)
            .order_by('code').values_list('id', flat=True)
        )
        n_pairs = min(len(retailer_ids), len(outlet_ids))
        buf = []
        assigned = len(rows)
        for i in range(n_pairs):
            buf.append(Assignment(assignee_id=retailer_ids[i], scope_id=outlet_ids[i],
                                  role_in_scope='owner', effective_from=TODAY,
                                  reason='seed_scale', is_active=True))
            if len(buf) >= batch:
                Assignment.objects.bulk_create(buf, batch_size=batch)
                assigned += len(buf)
                buf = []
        if buf:
            Assignment.objects.bulk_create(buf, batch_size=batch)
            assigned += len(buf)

        self.stdout.write(self.style.SUCCESS(
            f'  Assignments done: {assigned} owners in {time.monotonic() - started:.1f}s '
            f'({n_pairs} retailer→outlet pairs).'
        ))
        return result

    # ── workload: users / transactions / plan / schemes ───────────────────────
    def _seed_users(self, *, prefix, batch, org_levels):
        """One login per management-tree entity, all sharing one team-level field role.
        The hash is computed once and reused — hashing 10k passwords would dominate."""
        from django.contrib.auth.hashers import make_password

        from apps.accounts.models import Role, User, UserRole

        started = time.monotonic()
        password = make_password('Scale@1234')
        role, _ = Role.objects.get_or_create(
            code='scale_field',
            defaults={'name': 'Scale Field', 'permissions': {
                'target_management': 'team', 'achievement_view': 'team',
                'workflow_management': 'team', 'final_payout': 'own_only',
            }},
        )
        users = []
        for nodes in org_levels.values():
            for node in nodes:
                users.append(User(email=f'{node.code.lower()}@scale.test',
                                  password=password, entity=node, is_active=True))
        created = []
        for i in range(0, len(users), batch):
            created.extend(User.objects.bulk_create(users[i:i + batch], batch_size=batch))
        UserRole.objects.bulk_create(
            [UserRole(user=u, role=role, effective_from=TODAY) for u in created],
            batch_size=batch,
        )
        self.stdout.write(self.style.SUCCESS(
            f'  Users done: {len(created)} workforce logins (password Scale@1234) '
            f'in {time.monotonic() - started:.1f}s.'
        ))

    def _seed_transactions(self, *, prefix, batch, n, month, outlet_ids):
        """N sale lines in the plan month + N/10 in the same month last year (the recipe's
        LY-contribution signal). Deterministic amounts — reruns produce identical totals."""
        from apps.kpi_engine.models import Transaction

        year, mon = self._parse_month(month)
        ndays = _calendar.monthrange(year, mon)[1]
        started = time.monotonic()

        def burst(count, y, tag):
            buf, made = [], 0
            while made < count:
                amount = Decimal(500 + (made * 37) % 4500)
                buf.append(Transaction(
                    attributed_node_id=outlet_ids[made % len(outlet_ids)],
                    transaction_date=date(y, mon, (made % ndays) + 1),
                    transaction_type=Transaction.SALE, transaction_level=Transaction.SECONDARY,
                    sku_code=f'SKU-{made % 50:03d}', channel_code='GT', source='scale_seed',
                    external_ref=f'{prefix}-TXN-{tag}-{made + 1:08d}',
                    gross_amount=amount, net_amount=amount, quantity=Decimal((made % 20) + 1),
                ))
                made += 1
                if len(buf) >= batch:
                    Transaction.objects.bulk_create(buf, batch_size=batch)
                    buf = []
            if buf:
                Transaction.objects.bulk_create(buf, batch_size=batch)
            return made

        cur = burst(n, year, 'CUR')
        ly = burst(max(1, n // 10), year - 1, 'LY')
        elapsed = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(
            f'  Transactions done: {cur} in {month} + {ly} LY history '
            f'in {elapsed:.1f}s ({(cur + ly) / max(elapsed, 0.001):,.0f} rows/s bulk path).'
        ))

    def _seed_plan(self, *, prefix, month, nation):
        """KPI + recipe + a town-grain plan over the seeded nation, driven all the way to
        published: territory split run → commit → publish. The printed timings are the
        first capacity numbers for the planning pipeline."""
        from django.db.models import Sum

        from apps.kpi_engine.models import KPIDefinition, Transaction
        from apps.targets.models import AllocationRecipe, PlanRun, TargetPeriod, TargetPlan
        from apps.targets.plan_services import PlanService
        from apps.targets.services import TargetService

        year, mon = self._parse_month(month)
        fy_start = year if mon >= 4 else year - 1
        TargetService.generate_fiscal_year(f'{fy_start}-{str(fy_start + 1)[2:]}')
        period = TargetPeriod.objects.get(code=f'FY{fy_start}-M{mon:02d}')

        kpi, _ = KPIDefinition.objects.get_or_create(
            code=f'{prefix}_NSV', is_current=True,
            defaults=dict(name='Scale Secondary NSV', kpi_type=KPIDefinition.VALUE,
                          effective_from=TODAY,
                          measure_config={'measure_field': 'net_amount', 'aggregation': 'sum',
                                          'net_logic': 'sales_minus_returns'}),
        )
        recipe, _ = AllocationRecipe.objects.get_or_create(
            code=f'{prefix}-CONTRIB', is_current=True,
            defaults=dict(name='Scale contribution split', effective_from=TODAY,
                          weight_components=[{'source': 'contribution', 'weight': 100}],
                          base_window={'basis': 'ly_same_period'}, rounding={'unit': 1}),
        )

        existing = TargetPlan.objects.filter(code=f'{prefix}-PLAN-{month}').first()
        if existing:
            self.stdout.write(f'  Plan {existing.code} already exists — skipping.')
            return existing, kpi

        ly_total = Transaction.objects.filter(
            external_ref__startswith=f'{prefix}-TXN-LY-').aggregate(s=Sum('net_amount'))['s']
        top = ((ly_total or Decimal('1000000')) * Decimal('1.10')).quantize(Decimal('1'))

        plan = PlanService.create_plan(
            {'name': f'Scale plan {month}', 'code': f'{prefix}-PLAN-{month}',
             'period_id': period.id, 'root_geography_id': nation.id, 'planning_grain': 'town'},
            kpis=[{'kpi_id': kpi.id, 'recipe_id': recipe.id, 'top_value': str(top)}],
        )
        t0 = time.monotonic()
        run = PlanService.start_run(plan, PlanRun.SPATIAL)
        run.refresh_from_db()
        if run.status != PlanRun.STAGED:
            raise CommandError(f'Territory split ended {run.status}: '
                               f'{run.job.errors if run.job else "no job errors"}')
        t_run = time.monotonic() - t0
        t0 = time.monotonic()
        stats = PlanService.commit_run(run)
        PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
        self.stdout.write(self.style.SUCCESS(
            f'  Plan done: {plan.code} published at town grain — split {t_run:.1f}s, '
            f'commit+publish {time.monotonic() - t0:.1f}s '
            f'({stats["created"]} created, {stats["updated"]} updated; top {top:,}).'
        ))
        return plan, kpi

    def _seed_schemes(self, *, prefix, batch, period, kpi, org_levels, types):
        """Monthly SIP schemes for the two payee populations (ASEs + Distributors) with a
        standard tier grid, and a VariablePay row per payee for the plan month."""
        from apps.incentives.models import (
            IncentiveScheme, MultiplierTier, SchemeKPI, VariablePay,
        )

        started = time.monotonic()
        tiers = [('0', '50', '0'), ('50', '100', '0.5'), ('100', '120', '1'), ('120', None, '1.5')]
        for et_code, vp_amount in (('ase', '30000'), ('distributor', '15000')):
            scheme, created = IncentiveScheme.objects.get_or_create(
                code=f'{prefix}-SIP-{et_code.upper()}', is_current=True,
                defaults=dict(name=f'Scale SIP — {et_code}', target_entity_type=types[et_code],
                              effective_from=TODAY, payout_frequency=IncentiveScheme.MONTHLY),
            )
            if created:
                scheme_kpi = SchemeKPI.objects.create(scheme=scheme, kpi=kpi, weightage=Decimal('100'))
                MultiplierTier.objects.bulk_create([
                    MultiplierTier(scheme_kpi=scheme_kpi, min_achievement_pct=Decimal(lo),
                                   max_achievement_pct=Decimal(hi) if hi else None,
                                   multiplier=Decimal(mult))
                    for lo, hi, mult in tiers
                ])

        payees = [(n, Decimal('30000')) for n in org_levels['ase']] + \
                 [(n, Decimal('15000')) for n in org_levels['dist']]
        rows = [VariablePay(entity=n, target_period=period, amount=amount,
                            source=VariablePay.BULK_IMPORT) for n, amount in payees]
        for i in range(0, len(rows), batch):
            VariablePay.objects.bulk_create(rows[i:i + batch], batch_size=batch,
                                            ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(
            f'  Schemes done: 2 SIP schemes, {len(rows)} variable-pay rows '
            f'in {time.monotonic() - started:.1f}s.'
        ))

    @staticmethod
    def _parse_month(raw):
        try:
            y, m = raw.split('-')
            year, mon = int(y), int(m)
            assert 1 <= mon <= 12
            return year, mon
        except (ValueError, AssertionError):
            raise CommandError(f'--month must be YYYY-MM, got "{raw}".')

    def _purge(self, prefix):
        """Tear down a previous batch in dependency order (workload first, trees last)."""
        from apps.accounts.models import User
        from apps.achievements.models import Achievement, TerritoryAchievement
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import GeographyNode, Node
        from apps.incentives.models import IncentiveScheme, VariablePay
        from apps.kpi_engine.models import KPIDefinition, Transaction
        from apps.targets.models import AllocationRecipe, TargetAllocation, TargetPlan

        t_deleted, _ = Transaction.objects.filter(
            external_ref__startswith=f'{prefix}-TXN-').delete()
        u_deleted, _ = User.objects.filter(entity__code__startswith=f'{prefix}-').delete()
        VariablePay.objects.filter(entity__code__startswith=f'{prefix}-').delete()
        IncentiveScheme.objects.filter(code__startswith=f'{prefix}-SIP-').delete()
        Achievement.objects.filter(kpi__code__startswith=f'{prefix}_').delete()
        TerritoryAchievement.objects.filter(kpi__code__startswith=f'{prefix}_').delete()
        TargetAllocation.objects.filter(kpi__code__startswith=f'{prefix}_').delete()
        TargetPlan.objects.filter(code__startswith=f'{prefix}-PLAN-').delete()
        AllocationRecipe.objects.filter(code__startswith=f'{prefix}-CONTRIB').delete()
        KPIDefinition.objects.filter(code__startswith=f'{prefix}_').delete()
        # Assignment FKs are PROTECT — clear the bridge before either tree.
        a_deleted, _ = Assignment.objects.filter(
            scope__code__startswith=f'{prefix}-GEO-').delete()
        g_deleted, _ = GeographyNode.objects.filter(
            code__startswith=f'{prefix}-GEO-').delete()
        deleted, _ = Node.objects.filter(code__startswith=f'{prefix}-').delete()
        self.stdout.write(self.style.WARNING(
            f'  Purged {deleted} entities, {g_deleted} territories, {a_deleted} assignments, '
            f'{t_deleted} transactions, {u_deleted} users from a previous "{prefix}-*" batch.'
        ))
