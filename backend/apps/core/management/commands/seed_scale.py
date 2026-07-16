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
"""
import math
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError

TODAY = date.today()
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

    def handle(self, *args, **opts):
        from apps.hierarchy.models import Channel, Node, NodeType

        types = {c: NodeType.objects.filter(code=c, is_current=True).first() for c in TYPE_CODES}
        missing = [c for c, v in types.items() if v is None]
        if missing:
            raise CommandError(
                f"Missing entity types {missing}. Run `python manage.py seed_demo` first."
            )
        channel = Channel.objects.filter(code='GT').first()

        prefix = opts['prefix']
        batch = opts['batch']

        if opts['purge']:
            from apps.assignments.models import Assignment
            from apps.hierarchy.models import GeographyNode

            # Assignment FKs are PROTECT — clear the bridge before either tree.
            a_deleted, _ = Assignment.objects.filter(
                scope__code__startswith=f'{prefix}-GEO-').delete()
            g_deleted, _ = GeographyNode.objects.filter(
                code__startswith=f'{prefix}-GEO-').delete()
            deleted, _ = Node.objects.filter(code__startswith=f'{prefix}-').delete()
            self.stdout.write(self.style.WARNING(
                f'  Purged {deleted} entities, {g_deleted} territories, '
                f'{a_deleted} assignments from a previous "{prefix}-*" batch.'
            ))

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
        geo_total = opts['geography'] or (opts['total'] if opts['assign'] else 0)
        if geo_total:
            self._seed_geography_and_assignments(
                prefix=prefix, batch=batch, geo_total=geo_total, assign=opts['assign'],
                org_levels={'nsm': [nsm], 'rsm': rsms, 'asm': asms, 'ase': ases, 'dist': dists},
                retailer_prefix=f'{prefix}-RET-',
            )

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

        if not assign:
            self.stdout.write(self.style.SUCCESS(
                f'  Geography done: {upper + made} nodes in {time.monotonic() - started:.1f}s.'))
            return

        # ── The bridge: managers own upper levels, retailers own outlets 1:1 ──
        def zip_assign(entities, scopes):
            return [
                Assignment(assignee=e, scope=s, role_in_scope='owner',
                           effective_from=TODAY, reason='seed_scale', is_active=True)
                for e, s in zip(entities, scopes)
            ]

        rows = [Assignment(assignee=org_levels['nsm'][0], scope=nation, role_in_scope='owner',
                           effective_from=TODAY, reason='seed_scale', is_active=True)]
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
