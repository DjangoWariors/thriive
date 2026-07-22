"""Plan API (P5) — the full AOP flow over HTTP, plus the scoping guarantees.

Users: ``admin`` (unplaced, full target_management → plan admin), ``zoa_user`` (placed on
the ZOA entity that owns Zone A → reviewer, sees only their territory).
"""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.targets.models import ReviewTask, TargetAllocation, TargetPeriod, TargetPlan
from apps.targets.plan_services import PlanService

pytestmark = pytest.mark.django_db

BASE = '/api/v1/targets'
_FROM = date(2025, 1, 1)


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO', levels=['nation', 'zone', 'town'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    za = GeographyNode.objects.create(geography_type=gt, name='ZoneA', code='ZA', level='zone', parent=nation)
    zb = GeographyNode.objects.create(geography_type=gt, name='ZoneB', code='ZB', level='zone', parent=nation)
    a1 = GeographyNode.objects.create(geography_type=gt, name='A1', code='A1', level='town', parent=za)
    a2 = GeographyNode.objects.create(geography_type=gt, name='A2', code='A2', level='town', parent=za)
    for node, amount in ((a1, 1000), (a2, 3000), (zb, 4000)):
        Transaction.objects.create(
            attributed_node_id=node.id, transaction_date=date(2025, 6, 15),
            transaction_type=Transaction.SALE, transaction_level=Transaction.SECONDARY,
            net_amount=Decimal(str(amount)),
        )

    etype = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    zoa = Node.objects.create(entity_type=etype, name='ZOA', code='ZOA', effective_from=date.today())
    zob = Node.objects.create(entity_type=etype, name='ZOB', code='ZOB', effective_from=date.today())
    AssignmentService.create(assignee_id=zoa.id, scope_id=za.id, effective_from=_FROM)
    AssignmentService.create(assignee_id=zob.id, scope_id=zb.id, effective_from=_FROM)

    role = Role.objects.create(code='tgt_full', name='full', permissions={'target_management': 'full'})
    admin = User.objects.create_user(email='admin@x.com', password='pass')
    UserRole.objects.create(user=admin, role=role, effective_from=date.today())
    zoa_user = User.objects.create_user(email='zoa@x.com', password='pass', entity=zoa)
    UserRole.objects.create(user=zoa_user, role=role, effective_from=date.today())

    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )
    period = TargetPeriod.objects.create(
        code='FY27-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    return {'nation': nation, 'za': za, 'zb': zb, 'a1': a1, 'a2': a2, 'zoa': zoa, 'zob': zob,
            'admin': admin, 'zoa_user': zoa_user, 'kpi': kpi, 'period': period}


@pytest.fixture
def recipe_id(world):
    resp = _auth(world['admin']).post(f'{BASE}/recipes/', {
        'name': 'By contribution', 'code': 'CONTRIB',
        'weight_components': [{'source': 'contribution', 'weight': 100}],
        'base_window': {'basis': 'ly_same_period'}, 'rounding': {'unit': 1},
        'growth': {}, 'constraints': {},
    }, format='json')
    assert resp.status_code == 201, resp.data
    return resp.data['id']


@pytest.fixture
def plan_id(world, recipe_id):
    resp = _auth(world['admin']).post(f'{BASE}/plans/', {
        'name': 'FY27 AOP', 'code': 'AOP-FY27',
        'period_id': world['period'].id, 'root_geography_id': world['nation'].id,
        'review_levels': ['zone'],
        'kpis': [{'kpi_id': world['kpi'].id, 'recipe_id': recipe_id, 'top_value': '10000'}],
    }, format='json')
    assert resp.status_code == 201, resp.data
    return resp.data['id']


# ── the full flow over HTTP ───────────────────────────────────────────────────
def test_full_plan_flow_over_http(world, plan_id):
    admin = _auth(world['admin'])

    # 1. Spatial run → staged (runs inline in dev/eager mode)
    resp = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json')
    assert resp.status_code == 202
    run_id = resp.data['id']
    assert resp.data['status'] == 'staged'

    # 2. Preview shows the staged world before anything commits
    preview = admin.get(f'{BASE}/runs/{run_id}/preview/').data
    assert preview['new'] == 5  # nation + 2 zones + 2 towns (ZB has no children)
    assert preview['override_collision_count'] == 0

    # 3. Explain answers "why this number" (the RFP requirement)
    explain = admin.get(f'{BASE}/runs/{run_id}/explain/', {'node': world['za'].id}).data
    assert explain[0]['explain']['components'][0]['source'] == 'contribution'

    # 4. Commit → live targets
    stats = admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json').data
    assert stats['created'] == 5
    za = TargetAllocation.objects.get(geography_node=world['za'])
    assert za.target_value == Decimal('5000')  # 4000:4000 LY history

    # 5. Into review → tasks materialise for zone owners
    resp = admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'in_review'}, format='json')
    assert resp.status_code == 200
    assert resp.data['progress']['review'] == {'total': 2, 'open': 2}

    # 6. Zone A's owner sees exactly one task — their own
    zoa = _auth(world['zoa_user'])
    tasks = zoa.get(f'{BASE}/review-tasks/').data['results']
    assert len(tasks) == 1 and tasks[0]['node_code'] == 'ZA'

    # 7. They adjust within the default governance and the task closes
    resp = zoa.post(f"{BASE}/review-tasks/{tasks[0]['id']}/adjust/", {
        'allocation_id': za.id, 'override_value': '5200', 'reason': 'local push',
        'rebalance': False,
    }, format='json')
    assert resp.status_code == 200
    # No RevisionPolicy configured → an uncapped review cascade auto-approves adjustments.
    assert resp.data['status'] == 'adjusted'

    # 8. Gap board reflects the negotiation
    board = admin.get(f'{BASE}/plans/{plan_id}/gap-board/').data
    assert board['tasks_open'] == 1
    assert board['kpis'][0]['gap'] == '200.0000'

    # 9. Publish blocked → force-close (audited) → published
    resp = admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'published'}, format='json')
    assert resp.status_code == 422
    admin.post(f'{BASE}/plans/{plan_id}/force-close/', {'reason': 'AOP deadline'}, format='json')
    resp = admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'published'}, format='json')
    assert resp.status_code == 200 and resp.data['status'] == 'published'


def test_staged_rows_returns_full_generated_set(world, plan_id):
    """View staged rows: every generated row (all levels), not just what changed —
    the fix for a zero-change split having no visibility into its numbers."""
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']

    resp = admin.get(f'{BASE}/runs/{run_id}/staged-rows/')
    assert resp.status_code == 200
    assert resp.data['count'] == 5  # nation + 2 zones + 2 towns — the whole staged set
    rows = resp.data['results']
    assert {r['geography_node_code'] for r in rows} == {'IN', 'ZA', 'ZB', 'A1', 'A2'}
    # Root carries the top number; shape of a row is territory/level/kpi/value/base.
    root = next(r for r in rows if r['geography_node_code'] == 'IN')
    assert root['value'] == '10000.0000'
    assert set(root) >= {'geography_node', 'level', 'kpi', 'sku_group', 'value', 'base_value'}


# ── the lazy grid ─────────────────────────────────────────────────────────────
def test_grid_returns_one_level_with_context(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    grid = admin.get(f'{BASE}/plans/{plan_id}/grid/', {'kpi': world['kpi'].id}).data
    assert grid['parent']['code'] == 'IN'
    assert grid['parent']['target'] == '10000.0000'
    assert grid['parent']['bottom_up'] == '10000.0000'  # zones reconcile
    assert {r['code'] for r in grid['rows']} == {'ZA', 'ZB'}
    za_row = next(r for r in grid['rows'] if r['code'] == 'ZA')
    assert za_row['share_pct'] == '50.00'
    assert za_row['children_count'] == 2
    assert za_row['review_status'] is None  # cascade not opened yet

    # Lazy expand: one more call, one more level.
    level2 = admin.get(f'{BASE}/plans/{plan_id}/grid/',
                       {'kpi': world['kpi'].id, 'parent': world['za'].id}).data
    assert {r['code'] for r in level2['rows']} == {'A1', 'A2'}
    a2_row = next(r for r in level2['rows'] if r['code'] == 'A2')
    assert a2_row['target'] == '3750.0000'  # 1000:3000 within zone A
    assert a2_row['share_pct'] == '75.00'


def test_grid_shows_accountable_owner(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    grid = admin.get(f'{BASE}/plans/{plan_id}/grid/', {'kpi': world['kpi'].id}).data
    assert grid['parent']['owner'] is None  # nation: no owner anywhere up the chain
    za_row = next(r for r in grid['rows'] if r['code'] == 'ZA')
    assert za_row['owner']['code'] == 'ZOA' and za_row['owner']['inherited'] is False

    # Towns have no direct owner — accountability inherits from Zone A's owner.
    level2 = admin.get(f'{BASE}/plans/{plan_id}/grid/',
                       {'kpi': world['kpi'].id, 'parent': world['za'].id}).data
    assert level2['parent']['owner']['code'] == 'ZOA'
    a1_row = next(r for r in level2['rows'] if r['code'] == 'A1')
    assert a1_row['owner']['code'] == 'ZOA' and a1_row['owner']['inherited'] is True

    # A transfer flips the accountable person as of its effective date.
    AssignmentService.transfer(scope_id=world['za'].id, new_assignee_id=world['zob'].id,
                               effective_from=date.today())
    grid = admin.get(f'{BASE}/plans/{plan_id}/grid/', {'kpi': world['kpi'].id}).data
    za_row = next(r for r in grid['rows'] if r['code'] == 'ZA')
    assert za_row['owner']['code'] == 'ZOB'


def test_grid_is_territory_scoped(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    zoa = _auth(world['zoa_user'])
    # At the nation level, Zone A's owner sees only their zone…
    grid = zoa.get(f'{BASE}/plans/{plan_id}/grid/', {'kpi': world['kpi'].id}).data
    assert {r['code'] for r in grid['rows']} == {'ZA'}
    # …and inside their zone they see everything.
    level2 = zoa.get(f'{BASE}/plans/{plan_id}/grid/',
                     {'kpi': world['kpi'].id, 'parent': world['za'].id}).data
    assert {r['code'] for r in level2['rows']} == {'A1', 'A2'}


def test_grid_pagination(world, plan_id):
    admin = _auth(world['admin'])
    grid = admin.get(f'{BASE}/plans/{plan_id}/grid/',
                     {'kpi': world['kpi'].id, 'parent': world['za'].id, 'page_size': 1}).data
    assert grid['total'] == 2 and len(grid['rows']) == 1
    page2 = admin.get(f'{BASE}/plans/{plan_id}/grid/',
                      {'kpi': world['kpi'].id, 'parent': world['za'].id,
                       'page_size': 1, 'page': 2}).data
    assert len(page2['rows']) == 1
    assert grid['rows'][0]['code'] != page2['rows'][0]['code']


# ── RBAC guards ───────────────────────────────────────────────────────────────
def test_plan_mutations_are_admin_only(world, plan_id):
    zoa = _auth(world['zoa_user'])
    assert zoa.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'},
                    format='json').status_code == 422
    assert zoa.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'in_review'},
                    format='json').status_code == 422
    assert zoa.post(f'{BASE}/plans/', {'name': 'X', 'code': 'X', 'period_id': world['period'].id,
                                       'root_geography_id': world['nation'].id, 'kpis': []},
                    format='json').status_code == 422


def test_runs_hidden_from_scoped_users(world, plan_id):
    admin = _auth(world['admin'])
    admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json')
    zoa = _auth(world['zoa_user'])
    assert zoa.get(f'{BASE}/runs/').data['results'] == []


def test_cannot_touch_a_foreign_review_task(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')
    admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'in_review'}, format='json')

    zb_task = ReviewTask.objects.get(node=world['zb'])
    resp = _auth(world['zoa_user']).post(f'{BASE}/review-tasks/{zb_task.id}/accept/', {}, format='json')
    assert resp.status_code == 404  # not even visible, let alone actionable


def test_realign_endpoint(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    resp = admin.post(f'{BASE}/plans/{plan_id}/realign/',
                      {'scope_node_id': world['za'].id}, format='json')
    assert resp.status_code == 202
    assert resp.data['kind'] == 'realign' and resp.data['status'] == 'staged'
    assert resp.data['scope_node_code'] == 'ZA'


def test_plan_list_shows_progress(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')
    plans = admin.get(f'{BASE}/plans/').data['results']
    assert plans[0]['progress']['runs']['committed'] == 1
    assert plans[0]['progress']['committed_stages'] == ['spatial']
    assert plans[0]['kpis'][0]['kpi_code'] == 'CORE_VALUE'


# ── task-less adjust: the backend matches the edit to the caller's task ────────
def test_taskless_adjust_routes_to_the_right_task(world, plan_id):
    # ZOA owns two review territories — the old task-detail route couldn't handle this.
    gt = world['za'].geography_type
    zc = GeographyNode.objects.create(geography_type=gt, name='ZoneC', code='ZC',
                                      level='zone', parent=world['nation'])
    AssignmentService.create(assignee_id=world['zoa'].id, scope_id=zc.id, effective_from=_FROM)

    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')
    admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'in_review'}, format='json')

    zoa = _auth(world['zoa_user'])
    zc_alloc = TargetAllocation.objects.get(geography_node=zc)
    resp = zoa.post(f'{BASE}/review-tasks/adjust/', {
        'plan_id': plan_id, 'allocation_id': zc_alloc.id,
        'override_value': '100', 'reason': 'new zone ramp', 'rebalance': False,
    }, format='json')
    assert resp.status_code == 200
    assert resp.data['node_code'] == 'ZC'  # routed to the ZC task, not the first one

    # A territory outside their tasks is a clean error, not a mis-attribution.
    zb_alloc = TargetAllocation.objects.get(geography_node=world['zb'])
    resp = zoa.post(f'{BASE}/review-tasks/adjust/', {
        'plan_id': plan_id, 'allocation_id': zb_alloc.id,
        'override_value': '100', 'rebalance': False,
    }, format='json')
    assert resp.status_code == 422


# ── plan-scoped explain (works for reviewers, unlike /runs/) ────────────────────
def test_plan_explain_reachable_by_reviewer_and_territory_scoped(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    zoa = _auth(world['zoa_user'])
    resp = zoa.get(f'{BASE}/plans/{plan_id}/explain/', {'node': world['za'].id})
    assert resp.status_code == 200
    assert resp.data['run_id'] == run_id
    assert resp.data['rows'][0]['explain']['components'][0]['source'] == 'contribution'
    # Outside their territory → blocked.
    assert zoa.get(f'{BASE}/plans/{plan_id}/explain/',
                   {'node': world['zb'].id}).status_code == 422


def test_plan_explain_before_any_commit_is_empty_not_an_error(world, plan_id):
    resp = _auth(world['admin']).get(f'{BASE}/plans/{plan_id}/explain/', {'node': world['za'].id})
    assert resp.status_code == 200
    assert resp.data == {'run_id': None, 'kind': None, 'rows': []}


# ── grid parent masking for scoped users ────────────────────────────────────────
def test_grid_parent_totals_masked_outside_owned_territory(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')

    zoa = _auth(world['zoa_user'])
    # At nation level the parent's totals span Zone B too — masked for Zone A's owner.
    grid = zoa.get(f'{BASE}/plans/{plan_id}/grid/', {'kpi': world['kpi'].id}).data
    assert grid['parent']['target'] is None
    assert grid['parent']['bottom_up'] is None
    # Inside their own zone the parent row is fully visible.
    level2 = zoa.get(f'{BASE}/plans/{plan_id}/grid/',
                     {'kpi': world['kpi'].id, 'parent': world['za'].id}).data
    assert level2['parent']['target'] == '5000.0000'


# ── draft numbers stay out of downstream reads ──────────────────────────────────
def test_person_view_hides_draft_plan_numbers_unless_admin_asks(world, plan_id):
    admin = _auth(world['admin'])
    run_id = admin.post(f'{BASE}/plans/{plan_id}/runs/', {'kind': 'spatial'}, format='json').data['id']
    admin.post(f'{BASE}/runs/{run_id}/commit/', {}, format='json')  # plan still DRAFT

    params = {'period_id': world['period'].id, 'kpi_id': world['kpi'].id, 'entity_id': world['zoa'].id}
    assert Decimal(admin.get(f'{BASE}/allocations/person-view/', params).data['target']) == 0
    # Admin preview of the draft:
    resp = admin.get(f'{BASE}/allocations/person-view/', {**params, 'include_draft': 'true'})
    assert Decimal(resp.data['target']) == Decimal('5000')
    # A placed user cannot peek at drafts even with the flag:
    zoa = _auth(world['zoa_user'])
    resp = zoa.get(f'{BASE}/allocations/person-view/', {**params, 'include_draft': 'true'})
    assert Decimal(resp.data['target']) == 0

    # Publish → numbers go live for everyone.
    admin.post(f'{BASE}/plans/{plan_id}/transition/', {'status': 'published'}, format='json')
    assert Decimal(admin.get(f'{BASE}/allocations/person-view/', params).data['target']) == Decimal('5000')
