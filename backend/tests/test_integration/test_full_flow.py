"""Cross-app integration: entity types → entities → transactions → targets →
achievements → payouts.

Existing per-app tests assert the payout math from injected achievements; this suite proves
the apps actually connect — achievements are driven through the *real* KPICalculator over
Transactions, then payouts run off those achievements. A single VALUE KPI weighted 100% keeps
the expected payout exactly derivable from the transactions.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.achievements.models import Achievement
from apps.achievements.services import AchievementService
from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType
from apps.hierarchy.services import NodeService
from apps.incentives.models import (
    IncentiveScheme,
    MultiplierTier,
    Payout,
    SchemeKPI,
    VariablePay,
)
from apps.incentives.services import PayoutService
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.targets.models import TargetAllocation, TargetPeriod

GRID = [('0', '50', '0.000'), ('50', '80', '0.500'), ('80', '100', '0.800'),
        ('100', '120', '1.000'), ('120', None, '1.300')]


def _entity_type(name, code, order, **flags):
    return NodeType.objects.create(name=name, code=code, level_order=order,
                                     effective_from=date.today(), **flags)


def _txn(entity, amount, *, ttype=Transaction.SALE):
    a = Assignment.objects.filter(assignee_id=entity.id, role_in_scope='owner', is_active=True).first()
    node_id = a.scope_id if a else entity.id
    return Transaction.objects.create(
        attributed_node_id=node_id, transaction_date=date(2026, 6, 5),
        transaction_type=ttype, net_amount=D(str(amount)), channel_code='GT',
    )


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        name='June 2026', code='JUN26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


@pytest.fixture
def world(db, period):
    """ASE tree (NSM → ASM → ASE1, ASE2) + one VALUE KPI + single-KPI scheme + variable pay.
    Transactions: ASE1 sells 85,000 (→85%), ASE2 sells 128,000 (→128%) against a 100,000 target."""
    gt = Channel.objects.create(name='General Trade', code='GT')
    nsm_t = _entity_type('NSM', 'NSM', 1, is_loginable=True)
    asm_t = _entity_type('ASM', 'ASM', 2, is_loginable=True)
    ase_t = _entity_type('ASE', 'ASE', 3, incentive_eligible=True, is_loginable=True)

    nsm = Node.objects.create(entity_type=nsm_t, name='Nat', code='NSM', effective_from=date.today())
    asm = Node.objects.create(entity_type=asm_t, name='Area', code='ASM', parent=nsm,
                                effective_from=date.today())
    ase1 = Node.objects.create(entity_type=ase_t, name='Deepa', code='ASE1', parent=asm,
                                 channel=gt, effective_from=date.today())
    ase2 = Node.objects.create(entity_type=ase_t, name='Rahul', code='ASE2', parent=asm,
                                 channel=gt, effective_from=date.today())

    # Geography the ASEs own (sales attach here); ownership is independent of the org parent,
    # so an org move below does not change an ASE's own numbers.
    geo_t = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'area', 'town'])
    region = GeographyNode.objects.create(geography_type=geo_t, name='Region', code='REGION', level='region')
    area = GeographyNode.objects.create(geography_type=geo_t, name='Area', code='AREA', level='area', parent=region)
    town1 = GeographyNode.objects.create(geography_type=geo_t, name='Town1', code='TOWN1', level='town', parent=area)
    town2 = GeographyNode.objects.create(geography_type=geo_t, name='Town2', code='TOWN2', level='town', parent=area)
    for ent, node in ((nsm, region), (asm, area), (ase1, town1), (ase2, town2)):
        AssignmentService.create(assignee_id=ent.id, scope_id=node.id, effective_from=date(2025, 1, 1))

    kpi = KPIDefinition.objects.create(
        code='PRIMARY', name='Primary Sales', kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    for ent, amount in ((ase1, '85000'), (ase2, '128000')):
        _txn(ent, amount)
        # Targets are geography-anchored on the territory the ASE owns; the per-entity target
        # is derived from that ownership (via the Assignment bridge).
        owned = Assignment.objects.filter(assignee_id=ent.id, role_in_scope='owner', is_active=True).first()
        TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node_id=owned.scope_id,
                                        target_value=D('100000'))
        VariablePay.objects.create(entity=ent, target_period=period, amount=D('100000.00'))

    scheme = IncentiveScheme.objects.create(
        name='Field Force', code='FF', target_entity_type=ase_t, channel=None,
        vp_basis_pct=D('100.00'), effective_from=date.today(),
    )
    skpi = SchemeKPI.objects.create(scheme=scheme, kpi=kpi, incentive_category=SchemeKPI.SALES,
                                    weightage=D('100.00'), display_order=0)
    for mn, mx, m in GRID:
        MultiplierTier.objects.create(
            scheme_kpi=skpi, min_achievement_pct=D(mn),
            max_achievement_pct=D(mx) if mx is not None else None, multiplier=D(m),
        )
    return {'gt': gt, 'ase_t': ase_t, 'nsm': nsm, 'asm': asm, 'ase1': ase1, 'ase2': ase2,
            'kpi': kpi, 'scheme': scheme}


def _run_pipeline(world, period):
    AchievementService.compute_period(period.id)
    run = PayoutService.start_run(world['scheme'].pk, period.pk)
    PayoutService.compute_run(run.pk)
    run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestFullFlow:
    def test_pipeline_produces_expected_payouts(self, world, period):
        run = _run_pipeline(world, period)

        # Achievements derived from transactions vs targets.
        a1 = Achievement.objects.get(target_period=period, kpi=world['kpi'], entity=world['ase1'])
        a2 = Achievement.objects.get(target_period=period, kpi=world['kpi'], entity=world['ase2'])
        assert a1.achievement_pct == D('85.00')
        assert a2.achievement_pct == D('128.00')

        # Payouts: 85% → 0.8 tier → 0.8 × 100,000; 128% → 1.3 tier → 1.3 × 100,000.
        p1 = Payout.objects.get(run=run, entity=world['ase1'])
        p2 = Payout.objects.get(run=run, entity=world['ase2'])
        assert p1.total_payout == D('80000.00')
        assert p2.total_payout == D('130000.00')


@pytest.mark.django_db
class TestTransferIntegrity:
    def test_achievement_resolves_after_move(self, world, period):
        # New ASM under NSM, then move ASE1 to it.
        asm2 = Node.objects.create(entity_type=world['asm'].entity_type, name='Area2',
                                     code='ASM2', parent=world['nsm'], effective_from=date.today())
        NodeService.move_entity(world['ase1'].id, asm2.id, reason='realignment',
                                  effective_date=date.today(), user=None)

        run = _run_pipeline(world, period)
        # Sales attach to geography and ASE1 still owns its territory, so an org-parent move
        # must not change ASE1's own numbers.
        a1 = Achievement.objects.get(target_period=period, kpi=world['kpi'], entity=world['ase1'])
        assert a1.achievement_pct == D('85.00')
        assert Payout.objects.get(run=run, entity=world['ase1']).total_payout == D('80000.00')


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


def _user(email, *, entity=None, perms=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        role = Role.objects.create(code=email, name=email, permissions=perms)
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
    return u


@pytest.mark.django_db
class TestPayoutRbacTiers:
    def test_scoping_own_team_all(self, world, period):
        _run_pipeline(world, period)
        base = '/api/v1/incentives/payouts/'

        ase = _user('ase1@x.com', entity=world['ase1'], perms={'final_payout': 'own_only'})
        assert {r['entity_code'] for r in _client(ase).get(base, {'period': period.id}).data['results']} == {'ASE1'}

        # Payout confidentiality (RFP matrix): final_payout is never grantable at
        # team level — a hand-seeded 'team' grant is clamped to none → 403.
        asm = _user('asm@x.com', entity=world['asm'], perms={'final_payout': 'team'})
        assert _client(asm).get(base, {'period': period.id}).status_code == 403

        admin = _user('fin@x.com', perms={'final_payout': 'view_all'})
        assert {r['entity_code'] for r in _client(admin).get(base, {'period': period.id}).data['results']} == {'ASE1', 'ASE2'}


@pytest.mark.django_db
class TestBulkImport:
    def test_imports_100_entities_with_users(self, db):
        rep_t = _entity_type(
            'Rep', 'REP', 1, is_loginable=True,
            attribute_schema=[{'key': 'email', 'label': 'Email', 'type': 'email',
                               'required': True, 'unique': True}],
        )
        rows = [
            {'entity_type_code': 'REP', 'name': f'Rep {i}', 'code': f'REP{i:04d}',
             'attributes': {'email': f'rep{i}@x.com'}}
            for i in range(1, 101)
        ]
        result = NodeService.bulk_import(rows, 'json', user=None)
        assert result['status'] == 'success'
        assert result['created'] == 100
        assert result['users_created'] == 100
        assert Node.objects.filter(entity_type=rep_t, is_current=True).count() == 100
        assert User.objects.filter(entity__entity_type=rep_t).count() == 100
