"""TargetService.generate_fiscal_year — one-click plan-year creation (annual container + 12 months).

Targets are always set monthly: the annual period exists only to group the months (and to
anchor annual SIP runs), never to carry targets — and no quarters are created at all.
"""
from datetime import date

import pytest

from apps.core.exceptions import BusinessError
from apps.targets.models import TargetPeriod
from apps.targets.services import TargetService


def test_generates_container_and_months_april_start(db):
    annual = TargetService.generate_fiscal_year('2026-27', start_month=4)

    assert TargetPeriod.objects.count() == 13  # 1 annual container + 12 months
    assert annual.code == 'FY2026'
    assert annual.period_type == TargetPeriod.ANNUAL
    assert annual.start_date == date(2026, 4, 1)
    assert annual.end_date == date(2027, 3, 31)
    assert annual.fiscal_year == '2026-27'

    months = TargetPeriod.objects.filter(period_type=TargetPeriod.MONTHLY)
    assert months.count() == 12
    assert all(m.parent_id == annual.id for m in months)  # months hang off the FY directly
    april = TargetPeriod.objects.get(code='FY2026-M04')
    assert april.start_date == date(2026, 4, 1)
    assert april.end_date == date(2026, 4, 30)
    assert april.path == '/FY2026/FY2026-M04/'
    assert april.working_days == 26
    # February of the next calendar year resolves correctly (28 days in 2027).
    feb = TargetPeriod.objects.get(code='FY2026-M02')
    assert feb.start_date == date(2027, 2, 1)
    assert feb.end_date == date(2027, 2, 28)


def test_idempotent_on_rerun(db):
    TargetService.generate_fiscal_year('2026-27')
    TargetService.generate_fiscal_year('2026-27')
    assert TargetPeriod.objects.count() == 13


def test_calendar_year_start(db):
    annual = TargetService.generate_fiscal_year('2026', start_month=1)
    assert annual.start_date == date(2026, 1, 1)
    assert annual.end_date == date(2026, 12, 31)
    jan = TargetPeriod.objects.get(code='FY2026-M01')
    dec = TargetPeriod.objects.get(code='FY2026-M12')
    assert jan.start_date == date(2026, 1, 1)
    assert dec.end_date == date(2026, 12, 31)
    # All twelve months stay within the one calendar year.
    assert all(m.start_date.year == 2026 for m in TargetPeriod.objects.filter(period_type=TargetPeriod.MONTHLY))


@pytest.mark.parametrize('fy,start_month', [('', 4), ('2026-27', 0), ('2026-27', 13), ('notayear', 4)])
def test_rejects_bad_input(db, fy, start_month):
    with pytest.raises(BusinessError):
        TargetService.generate_fiscal_year(fy, start_month=start_month)
