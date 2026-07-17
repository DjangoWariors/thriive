"""
bench_scale — capacity benchmarks over the seed_scale world (Phase 2 of the scale plan).

Runs the platform's hot paths against the SCALE world (see seed_scale's full-profile
example) and reports timings against pass/fail budgets:

    achievements   full compute_period (territory + person pass)      budget 30 min
    payouts        estimate run per SIP scheme (~9k payees)           budget 15 min total
    api            p95 of the hot GET endpoints (admin + placed ASE)  budget 500 ms

Examples:
    python manage.py bench_scale                    # everything
    python manage.py bench_scale --section api      # one section
"""
import statistics
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError

PREFIX = 'SCALE'
BUDGETS = {'achievements': 1800.0, 'payouts': 900.0, 'api_p95': 0.5}
API_REPS = 15


class Command(BaseCommand):
    help = 'Benchmark the hot paths against the seed_scale world with pass/fail budgets.'

    def add_arguments(self, parser):
        parser.add_argument('--section', choices=['achievements', 'payouts', 'api', 'all'],
                            default='all')

    def handle(self, *args, **opts):
        from apps.targets.models import TargetPlan

        plan = TargetPlan.objects.filter(code__startswith=f'{PREFIX}-PLAN-').first()
        if plan is None:
            raise CommandError('No SCALE world found — run the seed_scale full profile first.')
        self.plan, self.period = plan, plan.period
        self.failures = []

        section = opts['section']
        if section in ('achievements', 'all'):
            self._bench_achievements()
        if section in ('payouts', 'all'):
            self._bench_payouts()
        if section in ('api', 'all'):
            self._bench_api()

        if self.failures:
            raise CommandError('Over budget: ' + ', '.join(self.failures))
        self.stdout.write(self.style.SUCCESS('\n  All benchmarks within budget.'))

    def _check(self, name, seconds, budget):
        verdict = 'PASS' if seconds <= budget else 'FAIL'
        style = self.style.SUCCESS if verdict == 'PASS' else self.style.ERROR
        self.stdout.write(style(f'  [{verdict}] {name}: {seconds:.1f}s (budget {budget:g}s)'))
        if verdict == 'FAIL':
            self.failures.append(f'{name} {seconds:.1f}s > {budget:.0f}s')

    # ── nightly achievement compute ────────────────────────────────────────────
    def _bench_achievements(self):
        from apps.achievements.services import AchievementService

        self.stdout.write('\n== Achievements: full compute_period (territory + person) ==')
        t0 = time.perf_counter()
        result = AchievementService.compute_period(self.period.id, as_of=self.period.end_date)
        elapsed = time.perf_counter() - t0
        self.stdout.write(f'  result: {result}')
        self._check('achievement compute', elapsed, BUDGETS['achievements'])

    # ── payout estimate runs ───────────────────────────────────────────────────
    def _bench_payouts(self):
        from apps.incentives.models import IncentiveScheme, PayoutRun
        from apps.incentives.services import PayoutService

        self.stdout.write('\n== Payouts: estimate run per SIP scheme ==')
        total = 0.0
        for scheme in IncentiveScheme.objects.filter(
                code__startswith=f'{PREFIX}-SIP-', is_current=True):
            t0 = time.perf_counter()
            run = PayoutService.start_run(scheme.id, self.period.id, kind=PayoutRun.ESTIMATE)
            stats = PayoutService.compute_run(run.id)
            elapsed = time.perf_counter() - t0
            total += elapsed
            self.stdout.write(f'  {scheme.code}: {elapsed:.1f}s — {stats}')
        self._check('payout estimate runs (all schemes)', total, BUDGETS['payouts'])

    # ── hot API endpoints ──────────────────────────────────────────────────────
    def _bench_api(self):
        from rest_framework.test import APIClient
        from rest_framework.throttling import SimpleRateThrottle

        from apps.accounts.models import User
        from apps.hierarchy.models import GeographyNode
        from apps.kpi_engine.models import KPIDefinition

        from django.conf import settings

        # The benchmark hammers each endpoint API_REPS times — rate limits would measure
        # the throttle, not the endpoint.
        SimpleRateThrottle.allow_request = lambda self, request, view: True
        if 'testserver' not in settings.ALLOWED_HOSTS:  # APIClient's synthetic host
            settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, 'testserver']

        admin = User.objects.filter(email='bench@scale.test').first()
        if admin is None:
            admin = User.objects.create_superuser(email='bench@scale.test', password='Bench@1234')
        ase = User.objects.filter(email=f'{PREFIX.lower()}-ase-0000001@scale.test').first()
        kpi = KPIDefinition.objects.get(code=f'{PREFIX}_NSV', is_current=True)
        nation = GeographyNode.objects.get(code=f'{PREFIX}-GEO-NAT-0000001')

        def client_for(user):
            c = APIClient()
            c.force_authenticate(user=user)
            return c

        cases = [
            ('plan grid (admin, root level)', client_for(admin),
             f'/api/v1/targets/plans/{self.plan.id}/grid/', {'kpi': kpi.id, 'page_size': 50}),
            ('territory actuals (admin, nation level)', client_for(admin),
             '/api/v1/achievements/territory/', {'kpi': kpi.id, 'period': self.period.id,
                                                 'parent': nation.id}),
            ('people grid (admin, page 1)', client_for(admin),
             '/api/v1/entities/', {'page_size': 50}),
            ('people search (trgm over 210k)', client_for(admin),
             '/api/v1/entities/search/', {'q': 'Retailer 19999'}),
            ('allocations list (admin)', client_for(admin),
             '/api/v1/targets/allocations/', {'target_period': self.period.id, 'page_size': 50}),
            ('payout register (admin, page 1)', client_for(admin),
             '/api/v1/incentives/payouts/', {'page_size': 50}),
        ]
        if ase is not None:
            cases.append(('plan grid (placed ASE, subtree landing)', client_for(ase),
                          f'/api/v1/targets/plans/{self.plan.id}/grid/',
                          {'kpi': kpi.id, 'page_size': 50}))

        self.stdout.write(f'\n== API: {API_REPS} reps per endpoint ==')
        worst = 0.0
        for name, client, url, params in cases:
            resp = client.get(url, params)  # warm-up + correctness gate
            if resp.status_code != 200:
                self.failures.append(f'{name} -> HTTP {resp.status_code}')
                self.stdout.write(self.style.ERROR(f'  [FAIL] {name}: HTTP {resp.status_code}'))
                continue
            samples = []
            for _ in range(API_REPS):
                t0 = time.perf_counter()
                client.get(url, params)
                samples.append(time.perf_counter() - t0)
            samples.sort()
            p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
            self.stdout.write(
                f'  {name}: median {statistics.median(samples) * 1000:.0f}ms · '
                f'p95 {p95 * 1000:.0f}ms · max {samples[-1] * 1000:.0f}ms'
            )
            worst = max(worst, p95)
        self._check('worst endpoint p95', worst, BUDGETS['api_p95'])
