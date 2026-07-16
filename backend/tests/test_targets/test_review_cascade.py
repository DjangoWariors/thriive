"""Cascade review + publish gates (P4).

Two trees:
  Geography:     IN (nation) ─┬─ ZA (zone)      review level = zone
                              └─ ZB (zone)
  Organisation:  MGR ─ owns ─▶ IN
                   ├── ZOA ─ owns ─▶ ZA
                   └── ZOB ─ owns ─▶ ZB
Committed plan numbers: IN 10000, ZA 5000, ZB 5000. RevisionPolicy: ±10% auto-approves.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.services import AssignmentService
from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.incentives.models import IncentiveScheme, MultiplierTier, SchemeKPI, VariablePay
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import (
    ReviewTask,
    TargetAllocation,
    TargetPeriod,
    TargetPlan,
    TargetRevision,
    RevisionPolicy,
)
from apps.achievements.calculator import AchievementCalculator
from apps.targets.plan_services import PlanService
from apps.targets.review_services import ReviewService
from apps.targets.services import TargetService

pytestmark = pytest.mark.django_db

_FROM = date(2025, 1, 1)


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO', levels=['nation', 'zone'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    za = GeographyNode.objects.create(geography_type=gt, name='ZoneA', code='ZA', level='zone', parent=nation)
    zb = GeographyNode.objects.create(geography_type=gt, name='ZoneB', code='ZB', level='zone', parent=nation)

    etype = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    mgr = Node.objects.create(entity_type=etype, name='MGR', code='MGR', effective_from=date.today())
    zoa = Node.objects.create(entity_type=etype, name='ZOA', code='ZOA', parent=mgr, effective_from=date.today())
    zob = Node.objects.create(entity_type=etype, name='ZOB', code='ZOB', parent=mgr, effective_from=date.today())
    for entity, node in ((mgr, nation), (zoa, za), (zob, zb)):
        AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=_FROM)

    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    # Deliberately a DRAFT period (the real plan flow never publishes it): governance must
    # key off the PLAN's status, not the period's — regression for the inert-governance bug.
    period = TargetPeriod.objects.create(
        code='FY27-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    RevisionPolicy.objects.create(
        name='Std cap', code='CAP10', effective_from=date.today(),
        auto_approve_within_pct=Decimal('10'), requires_reason=True,
    )
    return {'nation': nation, 'za': za, 'zb': zb, 'etype': etype,
            'mgr': mgr, 'zoa': zoa, 'zob': zob, 'kpi': kpi, 'period': period}


@pytest.fixture
def plan(world):
    plan = PlanService.create_plan(
        {'name': 'FY27 AOP', 'code': 'AOP-FY27', 'period_id': world['period'].id,
         'root_geography_id': world['nation'].id, 'review_levels': ['zone']},
        kpis=[{'kpi_id': world['kpi'].id}],
    )
    for node, value in ((world['nation'], '10000'), (world['za'], '5000'), (world['zb'], '5000')):
        TargetAllocation.objects.create(
            target_period=world['period'], plan=plan, kpi=world['kpi'], geography_node=node,
            target_value=Decimal(value), original_target_value=Decimal(value),
            status=TargetAllocation.APPROVED,
        )
    return plan


@pytest.fixture
def in_review(plan):
    return PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)


def task_for(plan, node):
    return ReviewTask.objects.get(plan=plan, node=node)


def alloc_for(plan, node):
    return TargetAllocation.objects.get(plan=plan, geography_node=node)


# ── cascade opens with resolved owners ────────────────────────────────────────
def test_cascade_opens_one_task_per_review_node_with_owner(world, in_review):
    assert in_review.review_tasks.count() == 2
    assert task_for(in_review, world['za']).owner_node_id == world['zoa'].id
    assert task_for(in_review, world['zb']).owner_node_id == world['zob'].id
    assert task_for(in_review, world['za']).status == ReviewTask.PENDING


def test_back_to_draft_cancels_cascade(world, in_review):
    PlanService.transition_plan(in_review, TargetPlan.DRAFT)
    assert in_review.review_tasks.count() == 0


# ── owner responses ───────────────────────────────────────────────────────────
def test_accept(world, in_review):
    task = ReviewService.accept(task_for(in_review, world['za']), notes='numbers look right')
    assert task.status == ReviewTask.ACCEPTED
    assert task.submitted_at is not None


def test_adjust_within_cap_auto_approves(world, in_review):
    task = ReviewService.adjust(
        task_for(in_review, world['za']), alloc_for(in_review, world['za']),
        Decimal('5200'), reason='local push', rebalance=False)
    assert task.status == ReviewTask.ADJUSTED
    alloc = alloc_for(in_review, world['za'])
    assert alloc.effective_target == Decimal('5200')
    assert alloc.revisions.latest('created_at').status == TargetRevision.APPROVED


def test_adjust_beyond_cap_escalates_then_manager_decides(world, in_review):
    task = ReviewService.adjust(
        task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
        Decimal('7000'), reason='huge distributor win', rebalance=False)
    assert task.status == ReviewTask.ESCALATED
    alloc = alloc_for(in_review, world['zb'])
    assert alloc.revisions.latest('created_at').status == TargetRevision.PENDING

    # Manager approves (the workflow adapter calls exactly this):
    ReviewService.resolve_escalation(alloc, approved=True)
    assert task_for(in_review, world['zb']).status == ReviewTask.ADJUSTED


def test_rejected_escalation_reopens_the_task(world, in_review):
    ReviewService.adjust(
        task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
        Decimal('7000'), reason='push', rebalance=False)
    ReviewService.resolve_escalation(alloc_for(in_review, world['zb']), approved=False)
    assert task_for(in_review, world['zb']).status == ReviewTask.PENDING


def test_adjust_outside_territory_rejected(world, in_review):
    with pytest.raises(BusinessError, match='outside this review territory'):
        ReviewService.adjust(
            task_for(in_review, world['za']), alloc_for(in_review, world['zb']),
            Decimal('5200'), reason='x')


def test_responses_blocked_when_review_not_open(world, plan):
    ReviewTask.objects.create(plan=plan, node=world['za'])  # plan still draft
    with pytest.raises(BusinessError, match='review is not open'):
        ReviewService.accept(task_for(plan, world['za']))


def test_accept_blocked_after_adjust(world, in_review):
    ReviewService.adjust(task_for(in_review, world['za']), alloc_for(in_review, world['za']),
                         Decimal('5200'), reason='push', rebalance=False)
    with pytest.raises(BusinessError, match='already been adjusted'):
        ReviewService.accept(task_for(in_review, world['za']))


def test_readjust_allowed_while_review_open(world, in_review):
    ReviewService.adjust(task_for(in_review, world['za']), alloc_for(in_review, world['za']),
                         Decimal('5200'), reason='first pass', rebalance=False)
    task = ReviewService.adjust(task_for(in_review, world['za']), alloc_for(in_review, world['za']),
                                Decimal('5300'), reason='second pass', rebalance=False)
    assert task.status == ReviewTask.ADJUSTED
    assert alloc_for(in_review, world['za']).effective_target == Decimal('5300')


def test_adjust_after_accept_allowed(world, in_review):
    ReviewService.accept(task_for(in_review, world['za']))
    task = ReviewService.adjust(task_for(in_review, world['za']), alloc_for(in_review, world['za']),
                                Decimal('5200'), reason='changed my mind', rebalance=False)
    assert task.status == ReviewTask.ADJUSTED


def test_escalated_task_locked_until_manager_decides(world, in_review):
    ReviewService.adjust(task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
                         Decimal('7000'), reason='big win', rebalance=False)
    with pytest.raises(BusinessError, match='with your manager'):
        ReviewService.adjust(task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
                             Decimal('6000'), reason='retry', rebalance=False)
    with pytest.raises(BusinessError, match='with your manager'):
        ReviewService.accept(task_for(in_review, world['zb']))


def test_resolve_escalation_flips_only_the_deepest_matching_task(world, plan):
    """Nested review levels: a zone escalation must not also flip the nation task."""
    plan.review_levels = ['nation', 'zone']
    plan.save(update_fields=['review_levels'])
    in_review = PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)

    # Escalate the nation task (beyond the ±10% cap), then the ZB zone task.
    ReviewService.adjust(task_for(in_review, world['nation']), alloc_for(in_review, world['nation']),
                         Decimal('14000'), reason='HO stretch', rebalance=False)
    ReviewService.adjust(task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
                         Decimal('7000'), reason='big win', rebalance=False)
    assert task_for(in_review, world['nation']).status == ReviewTask.ESCALATED
    assert task_for(in_review, world['zb']).status == ReviewTask.ESCALATED

    ReviewService.resolve_escalation(alloc_for(in_review, world['zb']), approved=True)
    assert task_for(in_review, world['zb']).status == ReviewTask.ADJUSTED
    assert task_for(in_review, world['nation']).status == ReviewTask.ESCALATED  # untouched


def test_open_cascade_skips_unowned_territories(world, plan):
    GeographyNode.objects.create(geography_type=world['za'].geography_type, name='ZoneC', code='ZC',
                                 level='zone', parent=world['nation'])  # nobody owns it
    in_review = PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)
    assert in_review.review_tasks.count() == 2  # ZC produced no unanswerable task


def test_review_with_no_matching_territories_is_a_clean_error(world, plan):
    plan.review_levels = ['district']  # level that doesn't exist under the root
    plan.save(update_fields=['review_levels'])
    with pytest.raises(BusinessError, match='No owned territories'):
        PlanService.transition_plan(plan, TargetPlan.IN_REVIEW)
    plan.refresh_from_db()
    assert plan.status == TargetPlan.DRAFT  # transition rolled back


def test_post_publish_edit_needs_approval_by_default(world, plan):
    """No policy → published-plan edits land PENDING (default maker-checker), even though
    the underlying period is still draft."""
    plan.review_levels = []
    plan.save(update_fields=['review_levels'])
    RevisionPolicy.objects.all().delete()
    published = PlanService.transition_plan(plan, TargetPlan.PUBLISHED)

    alloc = alloc_for(published, world['za'])
    TargetService.modify_allocation(alloc, Decimal('5100'), reason='correction', rebalance=False)
    alloc.refresh_from_db()
    assert alloc.status == TargetAllocation.PENDING
    assert alloc.revisions.latest('created_at').status == TargetRevision.PENDING


def test_draft_plan_numbers_invisible_to_achievements_until_publish(world, plan):
    """The territory pass (and the person rollup) must not read a plan that isn't live."""
    calc = AchievementCalculator(world['period'])
    assert calc.compute_territory_for_kpi(world['kpi']) == []
    assert TargetService.derive_entity_targets(
        world['period'], world['kpi'], [world['zoa'].id]) == {world['zoa'].id: Decimal('0')}

    plan.review_levels = []
    plan.save(update_fields=['review_levels'])
    PlanService.transition_plan(plan, TargetPlan.PUBLISHED)
    rows = calc.compute_territory_for_kpi(world['kpi'])
    assert {r['node_id'] for r in rows} == {world['nation'].id, world['za'].id, world['zb'].id}
    derived = TargetService.derive_entity_targets(world['period'], world['kpi'], [world['zoa'].id])
    assert derived[world['zoa'].id] == Decimal('5000')


def test_open_task_for_resolves_by_territory_for_multi_task_owners(world, in_review):
    """A reviewer owning several review territories gets each edit routed to the right task."""
    zc = GeographyNode.objects.create(geography_type=world['za'].geography_type, name='ZoneC',
                                      code='ZC', level='zone', parent=world['nation'])
    AssignmentService.create(assignee_id=world['zoa'].id, scope_id=zc.id, effective_from=_FROM)
    ReviewService.open_cascade(in_review)  # tops up the new territory
    zc_alloc = TargetAllocation.objects.create(
        target_period=in_review.period, plan=in_review, kpi=world['kpi'], geography_node=zc,
        target_value=Decimal('4000'), original_target_value=Decimal('4000'),
        status=TargetAllocation.APPROVED)

    task = ReviewService.open_task_for(in_review, world['zoa'], zc_alloc)
    assert task.node_id == zc.id
    task = ReviewService.open_task_for(in_review, world['zoa'], alloc_for(in_review, world['za']))
    assert task.node_id == world['za'].id
    with pytest.raises(BusinessError, match='not in your open review tasks'):
        ReviewService.open_task_for(in_review, world['zoa'], alloc_for(in_review, world['zb']))


# ── publish gate 1: cascade completeness + force-close ────────────────────────
def test_publish_blocked_while_tasks_open(world, in_review):
    with pytest.raises(BusinessError, match='review task'):
        PlanService.transition_plan(in_review, TargetPlan.PUBLISHED)


def test_force_close_is_audited_and_unblocks_publish(world, in_review):
    ReviewService.accept(task_for(in_review, world['za']))
    with pytest.raises(BusinessError, match='needs a reason'):
        ReviewService.force_close(in_review)
    closed = ReviewService.force_close(in_review, reason='AOP deadline — CEO signoff')
    assert closed == 1
    assert task_for(in_review, world['zb']).status == ReviewTask.FORCE_CLOSED
    entry = AuditLog.objects.filter(entity_type='targets.ReviewTask', action='update').latest('id')
    assert entry.changes['force_closed'] == 1
    assert 'CEO signoff' in entry.changes['reason']

    plan = PlanService.transition_plan(in_review, TargetPlan.PUBLISHED)
    assert plan.status == TargetPlan.PUBLISHED


def test_publish_after_all_responses(world, in_review):
    ReviewService.accept(task_for(in_review, world['za']))
    ReviewService.adjust(task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
                         Decimal('5100'), reason='ok', rebalance=False)
    plan = PlanService.transition_plan(in_review, TargetPlan.PUBLISHED)
    assert plan.status == TargetPlan.PUBLISHED
    # Publishing the plan publishes its month (derived period status).
    plan.period.refresh_from_db()
    assert plan.period.status == TargetPeriod.PUBLISHED


def test_publish_approves_rows_committed_mid_review(world, in_review):
    """Rows committed past draft land pending; publish is the sign-off that approves them."""
    in_review.allocations.update(status=TargetAllocation.PENDING)
    for node in (world['za'], world['zb']):
        ReviewService.accept(task_for(in_review, node))
    PlanService.transition_plan(in_review, TargetPlan.PUBLISHED)
    statuses = set(in_review.allocations.values_list('status', flat=True))
    assert statuses == {TargetAllocation.APPROVED}


def test_publish_skips_rows_with_open_escalated_revision(world, in_review):
    """Publish must not blanket-approve past an open maker-checker revision."""
    in_review.allocations.update(status=TargetAllocation.PENDING)
    escalated = alloc_for(in_review, world['za'])
    TargetRevision.objects.create(
        allocation=escalated, old_value=Decimal('5000'), new_value=Decimal('6000'),
        delta=Decimal('1000'), delta_pct=Decimal('20'), band=TargetRevision.ESCALATE,
        status=TargetRevision.PENDING)
    for node in (world['za'], world['zb']):
        ReviewService.accept(task_for(in_review, node))
    PlanService.transition_plan(in_review, TargetPlan.PUBLISHED)
    assert alloc_for(in_review, world['za']).status == TargetAllocation.PENDING
    assert alloc_for(in_review, world['zb']).status == TargetAllocation.APPROVED


# ── gap board ─────────────────────────────────────────────────────────────────
def test_gap_board_shows_progress_and_gap(world, in_review):
    ReviewService.accept(task_for(in_review, world['za']))
    ReviewService.adjust(task_for(in_review, world['zb']), alloc_for(in_review, world['zb']),
                         Decimal('5400'), reason='distributor win', rebalance=False)
    board = ReviewService.gap_board(in_review)
    assert board['tasks_total'] == 2 and board['tasks_open'] == 0
    assert board['by_level']['zone']['accepted'] == 1
    assert board['by_level']['zone']['adjusted'] == 1
    kpi_row = board['kpis'][0]
    assert kpi_row['top_down'] == '10000.0000'   # ZA 5000 + ZB 5000 originals
    assert kpi_row['bottom_up'] == '10400.0000'  # ZB adjusted to 5400
    assert kpi_row['gap'] == '400.0000'
    assert board['top_movers'][0]['geography_node'] == 'ZB'


# ── publish gate 2: cost of plan vs budget ────────────────────────────────────
@pytest.fixture
def scheme_world(world, plan):
    scheme = IncentiveScheme.objects.create(
        name='FF Monthly', code='FF_M', target_entity_type=world['etype'],
        gatekeeper_action=IncentiveScheme.ZERO_PAYOUT, effective_from=date.today(),
    )
    skpi = SchemeKPI.objects.create(scheme=scheme, kpi=world['kpi'], weightage=Decimal('100'))
    MultiplierTier.objects.create(scheme_kpi=skpi, min_achievement_pct=0,
                                  max_achievement_pct=100, multiplier=Decimal('0.5'))
    MultiplierTier.objects.create(scheme_kpi=skpi, min_achievement_pct=100,
                                  max_achievement_pct=None, multiplier=Decimal('1.0'))
    VariablePay.objects.create(entity=world['zoa'], target_period=world['period'], amount=Decimal('10000'))
    VariablePay.objects.create(entity=world['zob'], target_period=world['period'], amount=Decimal('20000'))
    return scheme


def test_cost_preview_prices_scenarios_through_the_engine(world, plan, scheme_world):
    preview = PlanService.cost_preview(plan)
    assert preview['scenarios'] == {'95': '15000.00', '100': '30000.00', '105': '30000.00'}
    assert preview['per_scheme'][0]['scheme'] == 'FF_M'
    assert preview['per_scheme'][0]['entities'] == 2  # the two VP rows (zoa, zob)


def test_over_budget_publish_needs_audited_override(world, plan, scheme_world):
    plan.settings = {'payout_budget': '25000'}
    plan.save(update_fields=['settings'])
    plan.review_levels = []
    plan.save(update_fields=['review_levels'])

    with pytest.raises(BusinessError, match='exceeds the plan budget'):
        PlanService.transition_plan(plan, TargetPlan.PUBLISHED)

    published = PlanService.transition_plan(plan, TargetPlan.PUBLISHED, force_over_budget=True)
    assert published.status == TargetPlan.PUBLISHED
    entry = AuditLog.objects.filter(entity_type='targets.TargetPlan', action='update').latest('id')
    assert entry.changes.get('over_budget_override') is True


def test_within_budget_publish_passes(world, plan, scheme_world):
    plan.settings = {'payout_budget': '50000'}
    plan.review_levels = []
    plan.save(update_fields=['settings', 'review_levels'])
    assert PlanService.transition_plan(plan, TargetPlan.PUBLISHED).status == TargetPlan.PUBLISHED
