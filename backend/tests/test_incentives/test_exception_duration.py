"""Multi-month exception duration + channel-scoped categories.

RFP new-joiner rule: joined on/before day X → default 1x for the join month + 1;
after day X → join month + 2. Approving once materializes approved children in the
following monthly periods, so later payout runs apply the treatment automatically.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.incentives.models import ExceptionCategory, PayoutException
from apps.incentives.services import ExceptionService
from apps.targets.models import TargetPeriod

from .conftest import mk_scheme, mk_vp, mk_achievement


def _monthly(code, year, month):
    from calendar import monthrange
    return TargetPeriod.objects.create(
        name=code, code=code, period_type=TargetPeriod.MONTHLY,
        start_date=date(year, month, 1),
        end_date=date(year, month, monthrange(year, month)[1]),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


@pytest.fixture
def months(db):
    return {
        'jun': _monthly('JUN26X', 2026, 6),
        'jul': _monthly('JUL26X', 2026, 7),
        'aug': _monthly('AUG26X', 2026, 8),
        'sep': _monthly('SEP26X', 2026, 9),
    }


@pytest.fixture
def new_joiner_cat(db):
    return ExceptionCategory.objects.create(
        code='new_joiner', name='New joiner', effective_from=date.today(),
        duration_config={'type': 'join_day_cutoff', 'cutoff_day': 20,
                         'months_on_or_before': 2, 'months_after': 3},
        default_sales_kpi_action=PayoutException.DEFAULT_1X,
        default_execution_kpi_action=PayoutException.DEFAULT_1X,
        default_gatekeeper_action=PayoutException.EXEMPTED,
    )


@pytest.fixture
def maternity_cat(db):
    return ExceptionCategory.objects.create(
        code='maternity_leave', name='Maternity leave', effective_from=date.today(),
        duration_config={'type': 'fixed', 'effect_months': 3},
        default_sales_kpi_action=PayoutException.DEFAULT_1X,
        default_execution_kpi_action=PayoutException.DEFAULT_1X,
        default_gatekeeper_action=PayoutException.EXEMPTED,
        requires_dates=True,
    )


# ── effect_months (pure config interpretation) ───────────────────────────────
def test_effect_months_defaults_to_single_period():
    assert ExceptionService.effect_months({}) == 1
    assert ExceptionService.effect_months({'type': 'fixed', 'effect_months': 6}) == 6


def test_effect_months_join_day_cutoff_both_sides():
    cfg = {'type': 'join_day_cutoff', 'cutoff_day': 20,
           'months_on_or_before': 2, 'months_after': 3}
    assert ExceptionService.effect_months(cfg, date(2026, 6, 20)) == 2  # on the cutoff
    assert ExceptionService.effect_months(cfg, date(2026, 6, 21)) == 3  # after it


def test_join_day_cutoff_requires_reference_date():
    with pytest.raises(BusinessError, match='reference date'):
        ExceptionService.effect_months({'type': 'join_day_cutoff'}, None)


# ── materialization on approval ──────────────────────────────────────────────
def _raise_exc(tree, period, cat, *, reference_date=None, actor=None):
    return ExceptionService.create({
        'entity': tree['ase1'], 'target_period': period, 'scheme': None,
        'category': cat.code, 'reason': 'test', 'reference_date': reference_date,
    }, actor=actor)


@pytest.mark.django_db
def test_approval_materializes_children(tree, months, new_joiner_cat):
    exc = _raise_exc(tree, months['jun'], new_joiner_cat, reference_date=date(2026, 6, 25))
    assert PayoutException.objects.count() == 1  # nothing before approval

    ExceptionService.approve(exc, actor=None)
    children = list(exc.children.order_by('target_period__start_date'))
    assert [c.target_period.code for c in children] == ['JUL26X', 'AUG26X']  # +2 months
    assert all(c.status == PayoutException.APPROVED for c in children)
    assert all(c.sales_kpi_action == PayoutException.DEFAULT_1X for c in children)


@pytest.mark.django_db
def test_on_or_before_cutoff_covers_one_extra_month(tree, months, new_joiner_cat):
    exc = _raise_exc(tree, months['jun'], new_joiner_cat, reference_date=date(2026, 6, 10))
    ExceptionService.approve(exc, actor=None)
    assert [c.target_period.code for c in exc.children.all()] == ['JUL26X']


@pytest.mark.django_db
def test_missing_future_periods_block_create(tree, months, maternity_cat):
    # Fixed 3 months from September needs Oct + Nov — neither exists.
    with pytest.raises(BusinessError, match='no monthly period starting 2026-10-01'):
        _raise_exc(tree, months['sep'], maternity_cat, reference_date=date(2026, 9, 1))


@pytest.mark.django_db
def test_child_exception_drives_next_months_payout_run(
    tree, months, maternity_cat, ase_type, kpis,
):
    """The RFP behaviour end-to-end: approve once in June → July's run applies default 1x."""
    from apps.incentives.services import PayoutService

    scheme = mk_scheme(ase_type, kpis)
    exc = _raise_exc(tree, months['jun'], maternity_cat, reference_date=date(2026, 6, 1))
    ExceptionService.approve(exc, actor=None)

    jul = months['jul']
    mk_vp(tree['ase1'], jul, amount='100000.00')
    for code in ('PRIMARY', 'ECO', 'MSL'):
        mk_achievement(jul, kpis[code], tree['ase1'], '40')  # poor month — would pay 0

    run = PayoutService.start_run(scheme.pk, jul.pk)
    PayoutService.compute_run(run.pk)
    payout = run.payouts.get(entity=tree['ase1'])
    assert payout.exception is not None and payout.exception.parent_id == exc.pk
    # default_1x on every KPI: 100000 × 1.0 × (50+30+20)%/100 = 100000
    assert payout.total_payout == Decimal('100000.00')
    assert all(li.treatment == 'default_1x' for li in payout.line_items.all())


@pytest.mark.django_db
def test_withdraw_parent_deactivates_children(tree, months, new_joiner_cat):
    exc = _raise_exc(tree, months['jun'], new_joiner_cat, reference_date=date(2026, 6, 25))
    ExceptionService.approve(exc, actor=None)
    assert exc.children.filter(is_active=True).count() == 2
    ExceptionService.withdraw(exc)
    assert exc.children.filter(is_active=True).count() == 0


@pytest.mark.django_db
def test_existing_exception_in_covered_month_wins(tree, months, new_joiner_cat):
    # An explicit July exception exists; materialization must not clash with it.
    explicit = ExceptionService.create({
        'entity': tree['ase1'], 'target_period': months['jul'], 'scheme': None,
        'category': '', 'reason': 'explicit', 'reference_date': None,
    })
    exc = _raise_exc(tree, months['jun'], new_joiner_cat, reference_date=date(2026, 6, 25))
    ExceptionService.approve(exc, actor=None)
    codes = [c.target_period.code for c in exc.children.all()]
    assert codes == ['AUG26X']  # July skipped — the explicit row wins
    assert PayoutException.objects.get(pk=explicit.pk).parent_id is None


# ── channel-scoped categories (G4) ───────────────────────────────────────────
@pytest.mark.django_db
def test_channel_scoped_category_rejects_other_channel(tree, months, db):
    from apps.hierarchy.models import Channel
    expert = Channel.objects.create(name='Expert', code='EXPERT')
    cat = ExceptionCategory.objects.create(
        code='ipad_issue', name='iPad not working', effective_from=date.today(),
        channel=expert,
    )
    # tree entities carry channel GT (or none) — not EXPERT.
    with pytest.raises(BusinessError, match='EXPERT channel only'):
        _raise_exc(tree, months['jun'], cat)
