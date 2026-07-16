"""Phase 2+3 — revision change-capping (RevisionPolicy) + the TargetRevision audit trail."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import RevisionPolicy, TargetAllocation, TargetPeriod, TargetRevision
from apps.targets.services import TargetService

JUN_START, JUN_END = date(2026, 6, 1), date(2026, 6, 30)


@pytest.fixture
def geo_type(db):
    return GeographyType.objects.create(name='Geo', code='geo', levels=['region', 'town'])


@pytest.fixture
def root(db, geo_type):
    return GeographyNode.objects.create(geography_type=geo_type, name='Region', code='REGION', level='region')


@pytest.fixture
def child_a(db, geo_type, root):
    return GeographyNode.objects.create(geography_type=geo_type, name='A', code='A1', level='town', parent=root)


@pytest.fixture
def child_b(db, geo_type, root):
    return GeographyNode.objects.create(geography_type=geo_type, name='B', code='B1', level='town', parent=root)


@pytest.fixture
def kpi(db):
    return KPIDefinition.objects.create(
        code='K', name='Secondary NSV', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        code='P1', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=JUN_START, end_date=JUN_END, status=TargetPeriod.DRAFT,
    )


def _alloc(period, kpi, node, value):
    """A standalone allocation (no siblings) with a known original value."""
    return TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=node,
        target_value=Decimal(value), original_target_value=Decimal(value),
        status=TargetAllocation.APPROVED,
    )


def _policy(**kw):
    kw.setdefault('name', 'pol')
    kw.setdefault('code', 'POL')
    kw.setdefault('effective_from', date.today())
    return RevisionPolicy.objects.create(**kw)


# ── plan-less rows are always governed (live from the moment they exist) ──────
def test_planless_edit_escalates_even_in_draft_period(period, kpi, root):
    """A draft month must not disable maker-checker: plan-less rows feed achievements
    immediately, so their edits always route for approval (or a policy band)."""
    a = _alloc(period, kpi, root, '1000')
    assert period.status == TargetPeriod.DRAFT
    TargetService.modify_allocation(a, Decimal('5000'), reason='plan')
    a.refresh_from_db()
    assert a.status == TargetAllocation.PENDING
    rev = a.revisions.get()
    assert rev.band == TargetRevision.ESCALATE and rev.status == TargetRevision.PENDING
    assert rev.old_value == Decimal('1000') and rev.new_value == Decimal('5000')


# ── no policy = default maker-checker ─────────────────────────────────────────
def test_planless_without_policy_escalates(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    TargetService.modify_allocation(a, Decimal('1050'), reason='nudge')
    a.refresh_from_db()
    assert a.status == TargetAllocation.PENDING
    assert a.revisions.get().band == TargetRevision.ESCALATE


# ── tolerance band ────────────────────────────────────────────────────────────
def test_within_band_auto_approves(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(auto_approve_within_pct=Decimal('10'))
    TargetService.modify_allocation(a, Decimal('1080'), reason='+8%')   # 8% ≤ 10%
    a.refresh_from_db()
    assert a.status == TargetAllocation.APPROVED
    assert a.revisions.get().band == TargetRevision.AUTO


def test_above_band_escalates(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(auto_approve_within_pct=Decimal('10'))
    TargetService.modify_allocation(a, Decimal('1200'), reason='+20%')  # 20% > 10%
    a.refresh_from_db()
    assert a.status == TargetAllocation.PENDING
    assert a.revisions.get().band == TargetRevision.ESCALATE


def test_above_ceiling_is_blocked(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(auto_approve_within_pct=Decimal('10'), hard_ceiling_pct=Decimal('25'))
    with pytest.raises(BusinessError, match='ceiling'):
        TargetService.modify_allocation(a, Decimal('1400'), reason='+40%')
    a.refresh_from_db()
    assert a.effective_target == Decimal('1000')          # unchanged
    assert a.revisions.count() == 0                        # nothing recorded for a blocked attempt


# ── delta measured against original (cumulative drift bounded) ────────────────
def test_delta_measured_against_original_not_last(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(auto_approve_within_pct=Decimal('10'), hard_ceiling_pct=Decimal('15'))
    TargetService.modify_allocation(a, Decimal('1080'), reason='step1')   # +8% vs original → auto
    a.refresh_from_db()
    # +8% again from 1080 would be small vs last, but vs ORIGINAL 1000 it is +25% → over ceiling
    with pytest.raises(BusinessError, match='ceiling'):
        TargetService.modify_allocation(a, Decimal('1250'), reason='step2')


# ── freeze window ─────────────────────────────────────────────────────────────
def test_freeze_after_blocks(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(freeze_after=date.today() - timedelta(days=1))
    with pytest.raises(BusinessError, match='frozen'):
        TargetService.modify_allocation(a, Decimal('1010'), reason='late')


# ── revision count cap ────────────────────────────────────────────────────────
def test_max_revisions_per_period(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(auto_approve_within_pct=Decimal('100'), max_revisions_per_period=2)
    TargetService.modify_allocation(a, Decimal('1100'), reason='r1')
    TargetService.modify_allocation(a, Decimal('1200'), reason='r2')
    with pytest.raises(BusinessError, match='revision limit'):
        TargetService.modify_allocation(a, Decimal('1300'), reason='r3')


# ── reason requirement ────────────────────────────────────────────────────────
def test_requires_reason(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(requires_reason=True)
    with pytest.raises(BusinessError, match='reason'):
        TargetService.modify_allocation(a, Decimal('1010'), reason='   ')


# ── policy specificity ────────────────────────────────────────────────────────
def test_period_scoped_policy_beats_global(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    _policy(code='GLOBAL', auto_approve_within_pct=Decimal('50'))                 # lax global
    _policy(code='SPECIFIC', target_period=period, auto_approve_within_pct=Decimal('5'))  # strict for this period
    TargetService.modify_allocation(a, Decimal('1200'), reason='+20%')  # 20% > 5% (specific) → escalate
    a.refresh_from_db()
    assert a.revisions.get().band == TargetRevision.ESCALATE


# ── base == 0 edge ────────────────────────────────────────────────────────────
def test_zero_base_escalates_never_blocks(period, kpi, root):
    a = _alloc(period, kpi, root, '0')
    _policy(auto_approve_within_pct=Decimal('10'), hard_ceiling_pct=Decimal('25'))
    TargetService.modify_allocation(a, Decimal('5000'), reason='first set')
    a.refresh_from_db()
    assert a.status == TargetAllocation.PENDING
    rev = a.revisions.get()
    assert rev.band == TargetRevision.ESCALATE and rev.delta_pct == Decimal('0')


# ── approve / reject lifecycle ────────────────────────────────────────────────
def test_approve_stamps_pending_revision(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    TargetService.modify_allocation(a, Decimal('2000'), reason='big')   # no policy → escalate
    TargetService.approve_allocation(a.__class__.objects.get(pk=a.pk))
    rev = a.revisions.get()
    assert rev.status == TargetRevision.APPROVED and rev.approved_at is not None


def test_reject_reverts_and_marks_rejected(period, kpi, root):
    a = _alloc(period, kpi, root, '1000')
    TargetService.modify_allocation(a, Decimal('2000'), reason='big')
    TargetService.reject_allocation(TargetAllocation.objects.get(pk=a.pk), reason='too high')
    a.refresh_from_db()
    assert a.effective_target == Decimal('1000')           # rolled back to pre-change
    assert a.revisions.get().status == TargetRevision.REJECTED


# ── rebalance writes revision rows for siblings ──────────────────────────────
def test_rebalance_records_sibling_revisions(period, kpi, root, child_a, child_b):
    # Siblings must be APPROVED (live): a PENDING sibling holds an optimistic override
    # awaiting a checker and is deliberately never rebalanced (see test_rebalance.py).
    a = TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node=child_a,
                                        target_value=Decimal('5000'), original_target_value=Decimal('5000'),
                                        status=TargetAllocation.APPROVED)
    TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node=child_b,
                                    target_value=Decimal('5000'), original_target_value=Decimal('5000'),
                                    status=TargetAllocation.APPROVED)
    TargetService.modify_allocation(a, Decimal('6000'), reason='push A', rebalance=True)
    b = TargetAllocation.objects.get(target_period=period, kpi=kpi, geography_node=child_b)
    assert b.effective_target == Decimal('4000')
    sib_rev = b.revisions.get()
    assert sib_rev.source == TargetRevision.REBALANCE and sib_rev.new_value == Decimal('4000')
