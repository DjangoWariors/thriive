"""Reviewer (placed, team-level) HTTP access — regression for the 403 wall.

Production field roles hold ``target_management: team`` / ``workflow_management: team``.
Targets objects carry no org-entity anchor, so base RBAC object checks used to deny every
detail route to placed users — an RSM could not even open the plan workspace, respond to
their review task, or approve an escalated revision from their inbox. These tests pin the
fixed contract: reviewers reach what their territory/task/inbox scoping grants — and
nothing beyond it.
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
from apps.targets.models import (
    ReviewTask, RevisionPolicy, TargetAllocation, TargetPeriod, TargetPlan, TargetRevision,
)
from apps.targets.plan_services import PlanService
from apps.targets.services import TargetService
from apps.workflows.services import WorkflowService

pytestmark = pytest.mark.django_db

BASE = '/api/v1/targets'
_FROM = date(2025, 1, 1)


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def _user(email, *, entity=None, perms):
    user = User.objects.create_user(email=email, password='pass', entity=entity)
    role = Role.objects.create(code=f'r-{email.split("@")[0]}', name=email, permissions=perms)
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO',
                                      levels=['nation', 'zone', 'district'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    za = GeographyNode.objects.create(geography_type=gt, name='ZoneA', code='ZA', level='zone', parent=nation)
    zb = GeographyNode.objects.create(geography_type=gt, name='ZoneB', code='ZB', level='zone', parent=nation)
    d1 = GeographyNode.objects.create(geography_type=gt, name='D1', code='D1', level='district', parent=za)
    d2 = GeographyNode.objects.create(geography_type=gt, name='D2', code='D2', level='district', parent=za)
    d3 = GeographyNode.objects.create(geography_type=gt, name='D3', code='D3', level='district', parent=zb)
    for node, amount in ((za, 3000), (zb, 1000)):
        Transaction.objects.create(
            attributed_node_id=node.id, transaction_date=date(2025, 6, 15),
            transaction_type=Transaction.SALE, transaction_level=Transaction.SECONDARY,
            net_amount=Decimal(str(amount)),
        )

    etype = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    mgr = Node.objects.create(entity_type=etype, name='MGR', code='MGR', effective_from=date.today())
    zoa = Node.objects.create(entity_type=etype, name='ZOA', code='ZOA', parent=mgr, effective_from=date.today())
    zob = Node.objects.create(entity_type=etype, name='ZOB', code='ZOB', parent=mgr, effective_from=date.today())
    # The ASM-depth persona: placed UNDER the zone owner, owning a grandchild of the plan root.
    asm = Node.objects.create(entity_type=etype, name='ASM', code='ASM', parent=zoa, effective_from=date.today())
    AssignmentService.create(assignee_id=zoa.id, scope_id=za.id, effective_from=_FROM)
    AssignmentService.create(assignee_id=zob.id, scope_id=zb.id, effective_from=_FROM)
    AssignmentService.create(assignee_id=asm.id, scope_id=d1.id, effective_from=_FROM)

    # Production-shaped grants: field users at TEAM level, HO admin unplaced FULL.
    team_perms = {'target_management': 'team', 'workflow_management': 'team'}
    admin = _user('admin@x.com', perms={'target_management': 'full', 'workflow_management': 'full'})
    zoa_user = _user('zoa@x.com', entity=zoa, perms=team_perms)
    zob_user = _user('zob@x.com', entity=zob, perms=team_perms)
    mgr_user = _user('mgr@x.com', entity=mgr, perms=team_perms)
    asm_user = _user('asm@x.com', entity=asm, perms=team_perms)

    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )
    period = TargetPeriod.objects.create(
        code='FY27-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    return {'nation': nation, 'za': za, 'zb': zb, 'd1': d1, 'd2': d2, 'd3': d3,
            'zoa': zoa, 'zob': zob, 'mgr': mgr, 'asm': asm,
            'admin': admin, 'zoa_user': zoa_user, 'zob_user': zob_user, 'mgr_user': mgr_user,
            'asm_user': asm_user, 'kpi': kpi, 'period': period}


@pytest.fixture
def plan(world):
    """A committed, in-review plan — the state a reviewer actually meets.
    review_levels=['zone'] on purpose: the district-owning ASM has NO review task."""
    plan = PlanService.create_plan(
        {'name': 'Jun Plan', 'code': 'PLAN-J', 'period_id': world['period'].id,
         'root_geography_id': world['nation'].id, 'review_levels': ['zone']},
        kpis=[{'kpi_id': world['kpi'].id, 'top_value': '10000'}],
    )
    for node, value in ((world['nation'], '10000'), (world['za'], '7500'), (world['zb'], '2500'),
                        (world['d1'], '4000'), (world['d2'], '3500'), (world['d3'], '2500')):
        TargetAllocation.objects.create(
            target_period=world['period'], plan=plan, kpi=world['kpi'], geography_node=node,
            target_value=Decimal(value), original_target_value=Decimal(value),
            status=TargetAllocation.APPROVED,
        )
    return PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)


def _alloc(world, node):
    return TargetAllocation.objects.get(geography_node=node, target_period=world['period'])


# ── the plan workspace opens for a team-level reviewer ─────────────────────────
def test_team_reviewer_can_open_the_plan_workspace(world, plan):
    zoa = _auth(world['zoa_user'])
    assert zoa.get(f'{BASE}/plans/{plan.id}/').status_code == 200
    assert zoa.get(f'{BASE}/periods/{world["period"].id}/tree/').status_code == 200
    assert zoa.get(f'{BASE}/plans/{plan.id}/gap-board/').status_code == 200

    grid = zoa.get(f'{BASE}/plans/{plan.id}/grid/', {'kpi': world['kpi'].id})
    assert grid.status_code == 200
    # Territory scoping still holds: only their zone, parent totals masked.
    assert {r['code'] for r in grid.data['rows']} == {'ZA'}
    assert grid.data['parent']['target'] is None


def test_team_reviewer_can_respond_to_their_task(world, plan):
    zoa = _auth(world['zoa_user'])
    task = ReviewTask.objects.get(plan=plan, node=world['za'])
    assert zoa.get(f'{BASE}/review-tasks/{task.id}/').status_code == 200
    assert zoa.post(f'{BASE}/review-tasks/{task.id}/accept/', {}, format='json').status_code == 200
    # A foreign task stays invisible.
    foreign = ReviewTask.objects.get(plan=plan, node=world['zb'])
    assert zoa.get(f'{BASE}/review-tasks/{foreign.id}/').status_code == 404
    assert zoa.post(f'{BASE}/review-tasks/{foreign.id}/accept/', {}, format='json').status_code == 404


def test_team_reviewer_allocation_access_is_territory_scoped(world, plan):
    zoa = _auth(world['zoa_user'])
    own = _alloc(world, world['za'])
    assert zoa.get(f'{BASE}/allocations/{own.id}/').status_code == 200
    assert zoa.get(f'{BASE}/allocations/{own.id}/revisions/').status_code == 200
    assert zoa.post(f'{BASE}/allocations/{own.id}/preflight/',
                    {'override_value': '8000'}, format='json').status_code == 200
    foreign = _alloc(world, world['zb'])
    assert zoa.get(f'{BASE}/allocations/{foreign.id}/').status_code == 404
    assert zoa.post(f'{BASE}/allocations/{foreign.id}/preflight/',
                    {'override_value': '1'}, format='json').status_code == 404


def test_checker_acts_stay_admin_only(world, plan):
    """A placed editor must never self-approve — escalations go to their manager."""
    own = _alloc(world, world['za'])
    TargetService.modify_allocation(own, Decimal('9000'), reason='push',
                                    actor=world['zoa_user'], rebalance=False)
    zoa = _auth(world['zoa_user'])
    assert zoa.post(f'{BASE}/allocations/{own.id}/approve/', {}, format='json').status_code == 422
    assert zoa.post(f'{BASE}/allocations/{own.id}/reject/', {}, format='json').status_code == 422
    admin = _auth(world['admin'])
    assert admin.post(f'{BASE}/allocations/{own.id}/approve/', {}, format='json').status_code == 200


# ── the approval inbox works for the placed manager ────────────────────────────
def test_manager_can_open_and_approve_the_escalated_revision(world, plan):
    from django.core.management import call_command
    call_command('seed_workflows')

    # An in-review beyond-cap edit escalates to the editor's org manager.
    own = _alloc(world, world['za'])
    RevisionPolicy.objects.create(name='Cap', code='CAP10', effective_from=date.today(),
                                  auto_approve_within_pct=Decimal('10'))
    TargetService.modify_allocation(own, Decimal('9000'), reason='push',
                                    actor=world['zoa_user'], rebalance=False)
    revision = TargetRevision.objects.get(allocation=own, status=TargetRevision.PENDING)
    inst = WorkflowService.for_subject('targets.TargetRevision', revision.pk)
    assert inst is not None

    mgr = _auth(world['mgr_user'])
    pending = mgr.get('/api/v1/workflows/pending/')
    assert pending.status_code == 200 and pending.data['count'] == 1
    assert mgr.get(f'/api/v1/workflows/{inst.pk}/').status_code == 200
    assert mgr.get(f'/api/v1/workflows/{inst.pk}/history/').status_code == 200
    resp = mgr.post(f'/api/v1/workflows/{inst.pk}/approve/', {'comments': 'ok'}, format='json')
    assert resp.status_code == 200
    own.refresh_from_db()
    assert own.effective_target == Decimal('9000')

    # An uninvolved placed user cannot even see the instance.
    zob = _auth(world['zob_user'])
    assert zob.get(f'/api/v1/workflows/{inst.pk}/').status_code == 404


# ── grid landing: every persona starts at THEIR subtree ─────────────────────────
def _grid(client, plan, world, **params):
    return client.get(f'{BASE}/plans/{plan.id}/grid/', {'kpi': world['kpi'].id, **params})


def test_grid_lands_on_the_users_subtree(world, plan):
    """A persona two levels below the plan root (the docs/asm_k.png dead end) lands on
    their zone as a masked parent with their own district visible and editable."""
    resp = _grid(_auth(world['asm_user']), plan, world)
    assert resp.status_code == 200
    assert resp.data['parent']['code'] == 'ZA'
    assert resp.data['parent']['target'] is None          # masked — ZA isn't theirs
    assert {r['code'] for r in resp.data['rows']} == {'D1'}
    assert resp.data['rows'][0]['target'] == '4000.0000'


def test_grid_shows_all_territories_of_a_multi_territory_owner(world, plan):
    AssignmentService.create(assignee_id=world['asm'].id, scope_id=world['d2'].id,
                             effective_from=_FROM)
    resp = _grid(_auth(world['asm_user']), plan, world)
    assert {r['code'] for r in resp.data['rows']} == {'D1', 'D2'}


def test_grid_lands_on_shallowest_branch_for_disjoint_owner(world, plan):
    # D1 under ZoneA + D3 under ZoneB: land on the first branch; the other one is
    # reachable via the territory jump (explicit parent param).
    AssignmentService.create(assignee_id=world['asm'].id, scope_id=world['d3'].id,
                             effective_from=_FROM)
    resp = _grid(_auth(world['asm_user']), plan, world)
    assert resp.data['parent']['code'] == 'ZA'
    assert {r['code'] for r in resp.data['rows']} == {'D1'}
    jumped = _grid(_auth(world['asm_user']), plan, world, parent=world['zb'].id)
    assert {r['code'] for r in jumped.data['rows']} == {'D3'}


def test_grid_root_covering_owner_is_unchanged(world, plan):
    AssignmentService.create(assignee_id=world['mgr'].id, scope_id=world['nation'].id,
                             effective_from=_FROM)
    resp = _grid(_auth(world['mgr_user']), plan, world)
    assert resp.data['parent']['code'] == 'IN'
    assert resp.data['parent']['target'] == '10000.0000'  # unmasked — they cover the root
    assert {r['code'] for r in resp.data['rows']} == {'ZA', 'ZB'}


def test_grid_empty_when_plan_does_not_cover_the_user(world, plan):
    gt = world['nation'].geography_type
    elsewhere = GeographyNode.objects.create(geography_type=gt, name='Elsewhere', code='ELSE',
                                             level='nation')
    outsider = Node.objects.create(entity_type=world['mgr'].entity_type, name='OUT', code='OUT',
                                   effective_from=date.today())
    AssignmentService.create(assignee_id=outsider.id, scope_id=elsewhere.id, effective_from=_FROM)
    out_user = _user('out@x.com', entity=outsider, perms={'target_management': 'team'})
    resp = _grid(_auth(out_user), plan, world)
    assert resp.status_code == 200
    assert resp.data['parent']['target'] is None and resp.data['total'] == 0


# ── published plans are read-only for the field; HO edits stay governed ──────────
@pytest.fixture
def published(world, plan):
    world['period'].status = TargetPeriod.PUBLISHED
    world['period'].save(update_fields=['status'])
    plan.status = TargetPlan.PUBLISHED
    plan.save(update_fields=['status'])
    return plan


def test_published_plan_is_readonly_for_field_users(world, published):
    asm = _auth(world['asm_user'])
    own = _alloc(world, world['d1'])
    # Even the user's own district refuses once the plan is published.
    r = asm.post(f'{BASE}/allocations/{own.id}/modify/',
                 {'override_value': '4200', 'reason': 'festive uplift', 'rebalance': False},
                 format='json')
    assert r.status_code == 422 and 'read-only for field users' in r.data['detail']
    own.refresh_from_db()
    assert own.effective_target == Decimal('4000')
    # A foreign district stays out of reach entirely (scoped queryset → 404, not 422).
    foreign = _alloc(world, world['d3'])
    r = asm.post(f'{BASE}/allocations/{foreign.id}/modify/',
                 {'override_value': '1', 'reason': 'x'}, format='json')
    assert r.status_code == 404


def test_ho_post_publish_edit_is_still_governed(world, published):
    RevisionPolicy.objects.create(
        name='Cap', code='CAP10', effective_from=date.today(),
        auto_approve_within_pct=Decimal('10'), requires_reason=True)
    admin = _auth(world['admin'])
    own = _alloc(world, world['d1'])
    # +5% (within cap) applies immediately.
    r = admin.post(f'{BASE}/allocations/{own.id}/modify/',
                   {'override_value': '4200', 'reason': 'festive uplift', 'rebalance': False},
                   format='json')
    assert r.status_code == 200
    own.refresh_from_db()
    assert own.effective_target == Decimal('4200')
    assert own.revisions.latest('created_at').band == TargetRevision.AUTO
    # -20% (beyond cap) escalates: value pending, not applied silently as approved.
    r = admin.post(f'{BASE}/allocations/{own.id}/modify/',
                   {'override_value': '3200', 'reason': 'wholesale correction', 'rebalance': False},
                   format='json')
    assert r.status_code == 200
    assert own.revisions.latest('created_at').status == TargetRevision.PENDING


def test_draft_plans_stay_ho_only(world, plan):
    plan.status = TargetPlan.DRAFT
    plan.save(update_fields=['status'])
    own = _alloc(world, world['d1'])
    r = _auth(world['asm_user']).post(f'{BASE}/allocations/{own.id}/modify/',
                                      {'override_value': '4200', 'rebalance': False}, format='json')
    assert r.status_code == 422 and 'planning team' in r.data['detail']
    r = _auth(world['admin']).post(f'{BASE}/allocations/{own.id}/modify/',
                                   {'override_value': '4200', 'rebalance': False}, format='json')
    assert r.status_code == 200  # draft is the HO sandbox


def test_rebalance_is_contained_to_the_owned_subtree(world, plan):
    asm = _auth(world['asm_user'])
    own = _alloc(world, world['d1'])
    # D2 (a sibling) isn't theirs → rebalance refused, edit not applied.
    r = asm.post(f'{BASE}/allocations/{own.id}/modify/',
                 {'override_value': '4100', 'reason': 'push', 'rebalance': True}, format='json')
    assert r.status_code == 422 and 'save without rebalance' in r.data['detail']
    own.refresh_from_db()
    assert own.effective_target == Decimal('4000')
    # Owning both districts, the sibling absorbs the delta.
    AssignmentService.create(assignee_id=world['asm'].id, scope_id=world['d2'].id,
                             effective_from=_FROM)
    r = asm.post(f'{BASE}/allocations/{own.id}/modify/',
                 {'override_value': '4100', 'reason': 'push', 'rebalance': True}, format='json')
    assert r.status_code == 200
    assert _alloc(world, world['d2']).effective_target == Decimal('3400.0000')


def test_service_level_containment(world, plan):
    from apps.core.exceptions import BusinessError
    from apps.targets.services import TargetService
    with pytest.raises(BusinessError, match='outside your area'):
        TargetService.modify_allocation(_alloc(world, world['d3']), Decimal('1'),
                                        reason='x', actor=world['asm_user'], rebalance=False)


def test_in_review_owner_without_a_task_uses_the_direct_path(world, plan):
    asm = _auth(world['asm_user'])
    own = _alloc(world, world['d1'])
    # No review task contains D1 for the ASM (review_levels=['zone']).
    r = asm.post(f'{BASE}/review-tasks/adjust/', {
        'plan_id': plan.id, 'allocation_id': own.id, 'override_value': '4100',
        'reason': 'push', 'rebalance': False}, format='json')
    assert r.status_code == 422
    # …but the governed direct path works during the review window.
    r = asm.post(f'{BASE}/allocations/{own.id}/modify/',
                 {'override_value': '4100', 'reason': 'push', 'rebalance': False}, format='json')
    assert r.status_code == 200
    own.refresh_from_db()
    assert own.effective_target == Decimal('4100')
