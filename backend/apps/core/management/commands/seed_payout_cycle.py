"""Seed a full incentive month-close so the payout-cycle workspace can be demoed end-to-end.

Self-contained (does not depend on other seeds): builds a small payout-ready world — a GT
channel, an NSM→ASM→ASE org tree over a matching geography tree with owning assignments, a
canonical 3-KPI SIP scheme, variable pay, and June achievements — then drives the whole
month-close through ``PayoutCycleService``:

    open → nightly estimate → finalize (freeze) → compute finals → submit → approve → disburse → close

Finally it restates one ASE's June number (simulating a DMS backfill), opens the July cycle,
raises an **adjustment** run for the delta, and rides it through July's approval/disbursement.

Idempotent via ``--reset`` (rebuilds the ``PC_`` demo namespace). Prints a cheat sheet.
Run:  python manage.py seed_payout_cycle --reset
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.achievements.models import Achievement
from apps.audit.models import ComputationLog
from apps.hierarchy.models import Channel, GeographyNode, GeographyType, Node, NodeType
from apps.incentives.models import (
    IncentiveScheme, MultiplierTier, Payout, PayoutCycle, PayoutRun, SchemeKPI, VariablePay,
)
from apps.incentives.services import PayoutCycleService
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetPeriod

D = Decimal

GRID = [('0', '50', '0.000'), ('50', '80', '0.500'), ('80', '100', '0.800'),
        ('100', '120', '1.000'), ('120', None, '1.300')]
KPIS = [('PC_PRIMARY', 'Primary Sales', 'sales', '50.00'),
        ('PC_ECO', 'Effective Coverage', 'execution', '30.00'),
        ('PC_MSL', 'Must-Sell Lines', 'execution', '20.00')]
# ASE code → per-KPI June achievement % (drives the tier spread on the demo)
JUNE = {'PC_ASE1': {'PC_PRIMARY': '85', 'PC_ECO': '60', 'PC_MSL': '90'},
        'PC_ASE2': {'PC_PRIMARY': '128', 'PC_ECO': '105', 'PC_MSL': '110'}}


class Command(BaseCommand):
    help = 'Seed a full closed payout month + a following-month adjustment (PC_ demo namespace).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete and rebuild the PC_ demo namespace.')

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['reset']:
            self._reset()
        elif TargetPeriod.objects.filter(code='PC_JUN26').exists():
            self.stdout.write(self.style.WARNING(
                'PC_ demo already seeded. Re-run with --reset to rebuild.'))
            return

        maker = self._user('pc_maker@demo.thriive', 'Maya', 'Maker')
        checker = self._user('pc_checker@demo.thriive', 'Charan', 'Checker')
        finance = self._user('pc_finance@demo.thriive', 'Fiza', 'Finance')

        june = self._period('PC_JUN26', 'June 2026', date(2026, 6, 1), date(2026, 6, 30))
        july = self._period('PC_JUL26', 'July 2026', date(2026, 7, 1), date(2026, 7, 31))
        ases = self._world()
        scheme = self._scheme()
        for period in (june, july):
            for node in ases:
                VariablePay.objects.create(entity=node, target_period=period,
                                           amount=D('100000.00'))
        self._achievements(june, ases)

        june_cycle, june_run = self._close_month(june, maker, checker, finance)
        july_cycle, adj = self._adjust_month(june, july, june_run, ases, maker, checker, finance)

        self._cheatsheet(june_cycle, june_run, july_cycle, adj)

    # ── build steps ───────────────────────────────────────────────────────────
    def _world(self):
        """NSM → ASM → ASE1/ASE2 org tree over region→area→town geography, with owning
        assignments so a payout has a responsible person. Returns the two ASE nodes."""
        from apps.assignments.services import AssignmentService

        gt = Channel.objects.get_or_create(code='PC_GT', defaults={'name': 'Demo GT'})[0]
        types = {}
        for code, name, order in [('PC_NSM', 'Demo NSM', 1), ('PC_ASM', 'Demo ASM', 2),
                                  ('PC_ASE', 'Demo ASE', 3)]:
            types[code] = NodeType.objects.create(
                name=name, code=code, level_order=order, incentive_eligible=True,
                effective_from=date(2025, 1, 1))
        nsm = Node.objects.create(entity_type=types['PC_NSM'], name='National', code='PC_NSM1',
                                  effective_from=date(2025, 1, 1))
        asm = Node.objects.create(entity_type=types['PC_ASM'], name='Area Mgr', code='PC_ASM1',
                                  parent=nsm, effective_from=date(2025, 1, 1))
        ase1 = Node.objects.create(entity_type=types['PC_ASE'], name='Deepa', code='PC_ASE1',
                                   parent=asm, channel=gt, effective_from=date(2025, 1, 1))
        ase2 = Node.objects.create(entity_type=types['PC_ASE'], name='Rahul', code='PC_ASE2',
                                   parent=asm, channel=gt, effective_from=date(2025, 1, 1))

        geo = GeographyType.objects.create(name='Demo Geo', code='pc_geo',
                                           levels=['region', 'area', 'town'])
        region = GeographyNode.objects.create(geography_type=geo, name='Region', code='PC_REGION',
                                              level='region')
        area = GeographyNode.objects.create(geography_type=geo, name='Area', code='PC_AREA',
                                            level='area', parent=region)
        town1 = GeographyNode.objects.create(geography_type=geo, name='Town 1', code='PC_TOWN1',
                                             level='town', parent=area)
        town2 = GeographyNode.objects.create(geography_type=geo, name='Town 2', code='PC_TOWN2',
                                             level='town', parent=area)
        for node, scope in ((nsm, region), (asm, area), (ase1, town1), (ase2, town2)):
            AssignmentService.create(assignee_id=node.id, scope_id=scope.id,
                                     effective_from=date(2025, 1, 1))
        return [ase1, ase2]

    def _scheme(self):
        kpi_by_code = {}
        for code, name, _cat, _w in KPIS:
            kpi_by_code[code] = KPIDefinition.objects.create(
                code=code, name=name, kpi_type=KPIDefinition.VALUE,
                applicable_entity_types=['PC_ASE'], effective_from=date(2025, 1, 1),
                measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'})
        scheme = IncentiveScheme.objects.create(
            name='Demo Field Force SIP', code='PC_SCHEME',
            target_entity_type=NodeType.objects.get(code='PC_ASE'),
            vp_basis_pct=D('100'), effective_from=date(2025, 1, 1))
        for order, (code, _name, cat, weight) in enumerate(KPIS):
            sk = SchemeKPI.objects.create(scheme=scheme, kpi=kpi_by_code[code],
                                          incentive_category=cat, weightage=D(weight),
                                          display_order=order)
            for lo, hi, mult in GRID:
                MultiplierTier.objects.create(scheme_kpi=sk, min_achievement_pct=D(lo),
                                              max_achievement_pct=D(hi) if hi else None,
                                              multiplier=D(mult))
        return scheme

    def _achievements(self, period, ases):
        for node in ases:
            for code, pct in JUNE[node.code].items():
                kpi = KPIDefinition.objects.get(code=code, is_current=True)
                target = D('100000')
                Achievement.objects.create(
                    target_period=period, kpi=kpi, entity=node,
                    target_value=target, achieved_value=target * D(pct) / 100,
                    achievement_pct=D(pct), computed_at=timezone.now())

    # ── drive the month-close ───────────────────────────────────────────────────
    def _close_month(self, june, maker, checker, finance):
        cycle = PayoutCycleService.open_cycle(june, actor=maker)
        PayoutCycleService.compute_estimates(cycle, actor=maker)   # nightly estimate
        # Green on a clean DB; on a shared dev DB other schemes' entities lack VP for this
        # brand-new demo period, so the period-wide check is red and we override (audited).
        ready = PayoutCycleService.readiness(cycle)['is_ready']
        PayoutCycleService.finalize(
            cycle, actor=maker, override=not ready,
            override_reason='' if ready else
            'Demo DB: entities of unrelated schemes have no variable pay for this new period.')
        PayoutCycleService.compute(cycle, actor=maker)             # final runs
        cycle.refresh_from_db()
        PayoutCycleService.submit_cycle(cycle, actor=maker)
        PayoutCycleService.approve_cycle(cycle, actor=checker)     # maker ≠ checker
        PayoutCycleService.disburse_cycle(cycle, actor=finance, payment_ref='NEFT-JUN-2026')
        PayoutCycleService.close_cycle(cycle, actor=finance)
        cycle.refresh_from_db()
        # compute fans out to every active monthly scheme of the period; the demo tracks its own.
        run = PayoutRun.objects.get(cycle=cycle, kind=PayoutRun.FINAL, scheme__code='PC_SCHEME')
        return cycle, run

    def _adjust_month(self, june, july, june_run, ases, maker, checker, finance):
        # Late data: ASE1 actually hit 120% on PRIMARY (was 85%). Restate + fresh compute log.
        primary = KPIDefinition.objects.get(code='PC_PRIMARY', is_current=True)
        a = Achievement.objects.get(target_period=june, kpi=primary, entity=ases[0])
        a.achievement_pct = D('120')
        a.achieved_value = a.target_value * D('120') / 100
        a.save(update_fields=['achievement_pct', 'achieved_value'])
        ComputationLog.objects.create(computation_type='achievement', entity_id=0,
                                      period_id=june.id, config_snapshot={}, result_snapshot={})

        july_cycle = PayoutCycleService.open_cycle(july, actor=maker)
        result = PayoutCycleService.create_adjustment(june_run, july_cycle, actor=maker)
        # Ride July's close (no July targets → override the readiness for the demo).
        Achievement.objects.filter(target_period=july).update(computed_at=timezone.now())
        PayoutCycleService.finalize(july_cycle, actor=maker, override=True,
                                    override_reason='Demo: July targets not yet planned.')
        PayoutCycleService.compute(july_cycle, actor=maker)
        july_cycle.refresh_from_db()
        PayoutCycleService.submit_cycle(july_cycle, actor=maker)
        PayoutCycleService.approve_cycle(july_cycle, actor=checker)
        PayoutCycleService.disburse_cycle(july_cycle, actor=finance, payment_ref='NEFT-JUL-2026')
        july_cycle.refresh_from_db()
        return july_cycle, result

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _period(self, code, name, start, end):
        return TargetPeriod.objects.create(
            name=name, code=code, period_type=TargetPeriod.MONTHLY,
            start_date=start, end_date=end, working_days=26, status=TargetPeriod.PUBLISHED)

    def _user(self, email, first, last):
        return User.objects.get_or_create(
            email=email, defaults={'first_name': first, 'last_name': last, 'is_staff': True})[0]

    def _reset(self):
        periods = TargetPeriod.objects.filter(code__in=['PC_JUN26', 'PC_JUL26'])
        Payout.objects.filter(target_period__in=periods).delete()
        PayoutRun.objects.filter(target_period__in=periods).delete()
        PayoutCycle.objects.filter(target_period__in=periods).delete()
        periods.delete()  # cascades achievements + variable pay
        IncentiveScheme.objects.filter(code='PC_SCHEME').delete()
        KPIDefinition.objects.filter(code__startswith='PC_').delete()
        from apps.assignments.models import Assignment
        Assignment.objects.filter(assignee__code__startswith='PC_').delete()
        Node.objects.filter(code__startswith='PC_').delete()
        NodeType.objects.filter(code__startswith='PC_').delete()
        GeographyNode.objects.filter(code__startswith='PC_').delete()
        GeographyType.objects.filter(code='pc_geo').delete()
        Channel.objects.filter(code='PC_GT').delete()

    def _cheatsheet(self, june_cycle, june_run, july_cycle, adj):
        reg = PayoutCycleService.register(july_cycle)
        w = self.stdout.write
        w(self.style.SUCCESS('\n[OK] Payout-cycle demo seeded (PC_ namespace).'))
        w('\n  JUNE - a fully closed month:')
        w(f'    cycle #{june_cycle.id}  status={june_cycle.status}  '
          f'paid total {june_cycle.total_payout}  ref {june_cycle.register_ref}')
        w(f'    final run #{june_run.id}  {june_run.entities_processed} payees  '
          f'total {june_run.total_payout}')
        w('\n  JULY - carries an adjustment for June\'s restated ASE1:')
        w(f'    cycle #{july_cycle.id}  status={july_cycle.status}  '
          f'paid total {july_cycle.total_payout}')
        w(f'    adjustment run #{adj["run_id"]}  net delta {adj["net_delta"]}  '
          f'({adj["entities_processed"]} payee row(s))')
        adj_rows = [r for r in reg['rows'] if r['kind'] == 'adjustment']
        for r in adj_rows:
            w(f'      - {r["entity_name"]} ({r["entity_code"]}): {r["total_payout"]} '
              f'arrears for {r["adjustment_for"]}')
        w('\n  Open /incentives/cycles in the app to walk the workspace. '
          'Maker=pc_maker, Checker=pc_checker, Finance=pc_finance (@demo.thriive).\n')
