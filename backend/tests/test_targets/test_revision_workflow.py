"""Target-modification approval workflow (RFP: edit → immediate-manager approval).

A published-period edit beyond the auto-approve band escalates; the revision routes to the
editor's org manager (Entity.parent chain) even though the target is geography-anchored.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod, TargetRevision
from apps.targets.services import TargetService
from apps.workflows.services import WorkflowService

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded_wf(db):
    from django.core.management import call_command
    call_command('seed_workflows')


@pytest.fixture
def world(db):
    et = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    mgr = Node.objects.create(entity_type=et, name='Mgr', code='MGR', effective_from=date.today())
    editor = Node.objects.create(entity_type=et, name='Editor', code='ED', parent=mgr, effective_from=date.today())
    mgr_user = User.objects.create_user(email='mgr@x.com', password='p', entity=mgr)
    ed_user = User.objects.create_user(email='ed@x.com', password='p', entity=editor)

    gt = GeographyType.objects.create(name='Geo', code='geo', levels=['town'])
    town = GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN', level='town')
    AssignmentService.create(assignee_id=editor.id, scope_id=town.id, effective_from=date(2025, 1, 1))

    kpi = KPIDefinition.objects.create(
        code='K', name='K', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    period = TargetPeriod.objects.create(
        code='P', name='P', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), status=TargetPeriod.PUBLISHED,
    )
    alloc = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=town,
        target_value=Decimal('1000'), original_target_value=Decimal('1000'),
        status=TargetAllocation.APPROVED,
    )
    return {'mgr_user': mgr_user, 'ed_user': ed_user, 'alloc': alloc}


def _instance(revision):
    return WorkflowService.for_subject('targets.TargetRevision', revision.pk)


def test_escalated_edit_routes_to_editor_manager(world, seeded_wf):
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    assert alloc.status == TargetAllocation.PENDING  # awaiting approval
    revision = TargetRevision.objects.get(allocation=alloc)
    inst = _instance(revision)
    assert inst is not None
    step = inst.steps.order_by('order').first()
    assert step.assignee_user == world['mgr_user']  # editor's immediate manager


def test_manager_approval_applies_the_override(world, seeded_wf):
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    revision = TargetRevision.objects.get(allocation=alloc)
    WorkflowService.approve(_instance(revision), world['mgr_user'], 'ok')
    alloc.refresh_from_db()
    revision.refresh_from_db()
    assert revision.status == TargetRevision.APPROVED
    assert alloc.status == TargetAllocation.APPROVED
    assert alloc.effective_target == Decimal('2000')


def test_manager_rejection_reverts_the_target(world, seeded_wf):
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    revision = TargetRevision.objects.get(allocation=alloc)
    WorkflowService.reject(_instance(revision), world['mgr_user'], 'too high')
    alloc.refresh_from_db()
    revision.refresh_from_db()
    assert revision.status == TargetRevision.REJECTED
    assert alloc.effective_target == Decimal('1000')  # reverted to the original
    assert alloc.override_value is None


def test_auto_band_edit_skips_the_workflow(world, seeded_wf):
    # An edit inside a policy's auto-approve band needs no approval — no workflow,
    # no manager routing.
    from apps.targets.models import RevisionPolicy

    RevisionPolicy.objects.create(name='pol', code='POL', effective_from=date.today(),
                                  auto_approve_within_pct=Decimal('10'))
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('1080'), reason='+8%',
                                            actor=world['ed_user'])
    revision = TargetRevision.objects.get(allocation=alloc)
    assert revision.band == TargetRevision.AUTO
    assert _instance(revision) is None
    assert alloc.status == TargetAllocation.APPROVED


def test_draft_period_no_longer_disables_governance(world, seeded_wf):
    # Plan-less rows are live downstream from day one, so a draft month must not
    # turn maker-checker off — the edit escalates exactly as on a published month.
    world['alloc'].target_period.status = TargetPeriod.DRAFT
    world['alloc'].target_period.save(update_fields=['status'])
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    assert alloc.status == TargetAllocation.PENDING
    revision = TargetRevision.objects.get(allocation=alloc)
    assert revision.band == TargetRevision.ESCALATE
    assert _instance(revision) is not None


def test_period_lock_voids_pending_revision_and_workflow(world, seeded_wf):
    # The cycle finalizing freezes the base exactly as computed: an in-flight escalation
    # is void (workflow cancelled, revision closed) and the applied value stays put.
    from apps.workflows.models import WorkflowInstance

    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    revision = TargetRevision.objects.get(allocation=alloc)
    inst = _instance(revision)
    TargetService.advance_period(alloc.target_period, TargetPeriod.LOCKED)
    alloc.refresh_from_db(); revision.refresh_from_db(); inst.refresh_from_db()
    assert revision.status == TargetRevision.REJECTED
    assert 'period locked' in revision.reason
    assert inst.status == WorkflowInstance.CANCELLED
    assert alloc.status == TargetAllocation.LOCKED
    assert alloc.effective_target == Decimal('2000')  # the paid base is untouched


def test_late_decision_on_locked_allocation_noops(world, seeded_wf):
    # Race window: the allocation freezes between the manager opening and deciding.
    # The callback must not move a frozen, already-paid number.
    alloc = TargetService.modify_allocation(world['alloc'], Decimal('2000'), reason='push',
                                            actor=world['ed_user'])
    revision = TargetRevision.objects.get(allocation=alloc)
    inst = _instance(revision)
    TargetAllocation.objects.filter(pk=alloc.pk).update(status=TargetAllocation.LOCKED)
    WorkflowService.reject(inst, world['mgr_user'], 'late')
    alloc.refresh_from_db()
    assert alloc.status == TargetAllocation.LOCKED
    assert alloc.effective_target == Decimal('2000')  # no revert


def test_rejection_reverts_rebalanced_siblings(world, seeded_wf):
    # A beyond-cap edit rebalances its sibling optimistically; the manager's rejection
    # must take the sibling back too, or the parent total stays broken for good.
    gt2 = GeographyType.objects.create(name='G2', code='G2', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt2, name='Region', code='REG', level='region')
    t1 = GeographyNode.objects.create(geography_type=gt2, name='T1', code='T1', level='town', parent=region)
    t2 = GeographyNode.objects.create(geography_type=gt2, name='T2', code='T2', level='town', parent=region)
    AssignmentService.create(assignee_id=world['ed_user'].entity_id, scope_id=region.id,
                             effective_from=date(2025, 1, 1))
    period = world['alloc'].target_period
    kpi = world['alloc'].kpi
    a1 = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=t1, target_value=Decimal('5000'),
        original_target_value=Decimal('5000'), status=TargetAllocation.APPROVED)
    a2 = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=t2, target_value=Decimal('5000'),
        original_target_value=Decimal('5000'), status=TargetAllocation.APPROVED)

    TargetService.modify_allocation(a1, Decimal('6000'), reason='push', actor=world['ed_user'],
                                    rebalance=True)
    a2.refresh_from_db()
    assert a2.effective_target == Decimal('4000')  # absorbed optimistically
    revision = TargetRevision.objects.get(allocation=a1, source=TargetRevision.MANUAL)
    side = TargetRevision.objects.get(allocation=a2, source=TargetRevision.REBALANCE)
    assert side.triggered_by_id == revision.id

    WorkflowService.reject(_instance(revision), world['mgr_user'], 'no')
    a1.refresh_from_db(); a2.refresh_from_db(); side.refresh_from_db()
    assert a1.effective_target == Decimal('5000')
    assert a2.effective_target == Decimal('5000')  # sibling restored with the edit
    assert side.status == TargetRevision.REJECTED
    assert a1.effective_target + a2.effective_target == Decimal('10000')  # parent sum intact


def test_editor_with_no_manager_stays_pending(world, seeded_wf):
    # Root-of-tree editor: no approver reachable. The edit must NOT sail through an
    # empty workflow chain — it stays pending for the manual approve queue.
    lone = Node.objects.create(entity_type=world['ed_user'].entity.entity_type,
                               name='Lone', code='LONE', effective_from=date.today())
    lone_user = User.objects.create_user(email='lone@x.com', password='p', entity=lone)
    gt = world['alloc'].geography_node.geography_type
    town2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town')
    AssignmentService.create(assignee_id=lone.id, scope_id=town2.id, effective_from=date(2025, 1, 1))
    alloc = TargetAllocation.objects.create(
        target_period=world['alloc'].target_period, kpi=world['alloc'].kpi, geography_node=town2,
        target_value=Decimal('1000'), original_target_value=Decimal('1000'),
        status=TargetAllocation.APPROVED)

    alloc = TargetService.modify_allocation(alloc, Decimal('2000'), reason='push', actor=lone_user)
    revision = TargetRevision.objects.get(allocation=alloc)
    assert alloc.status == TargetAllocation.PENDING
    assert revision.status == TargetRevision.PENDING  # not auto-approved
    assert _instance(revision) is None  # no unactionable/empty workflow created
