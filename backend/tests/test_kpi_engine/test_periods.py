from datetime import date

import pytest

from apps.kpi_engine import periods


def test_last_year_same_period():
    base = periods.resolve_comparison_window(
        date(2026, 6, 1), date(2026, 6, 30), periods.LAST_YEAR_SAME_PERIOD,
    )
    assert base == (date(2025, 6, 1), date(2025, 6, 30))


def test_last_year_same_period_is_to_date_when_window_is_mtd():
    # A mid-month (MTD) window maps to the same MTD window last year.
    base = periods.resolve_comparison_window(
        date(2026, 6, 1), date(2026, 6, 12), periods.LAST_YEAR_SAME_PERIOD,
    )
    assert base == (date(2025, 6, 1), date(2025, 6, 12))


def test_previous_month_clamps_day():
    # Mar 31 − 1 month → Feb 28 (2026 is not a leap year).
    base = periods.resolve_comparison_window(
        date(2026, 3, 31), date(2026, 3, 31), periods.PREVIOUS_MONTH,
    )
    assert base == (date(2026, 2, 28), date(2026, 2, 28))


def test_previous_period_is_contiguous_prior_window():
    base = periods.resolve_comparison_window(
        date(2026, 6, 1), date(2026, 6, 30), periods.PREVIOUS_PERIOD,
    )
    # 30-day window immediately preceding June 1.
    assert base == (date(2026, 5, 2), date(2026, 5, 31))


def test_custom_offset_requires_value():
    with pytest.raises(ValueError):
        periods.resolve_comparison_window(
            date(2026, 6, 1), date(2026, 6, 30), periods.CUSTOM_MONTH_OFFSET,
        )


def test_custom_offset_shifts_months():
    base = periods.resolve_comparison_window(
        date(2026, 6, 30), date(2026, 6, 30), periods.CUSTOM_MONTH_OFFSET, offset=3,
    )
    assert base == (date(2026, 3, 30), date(2026, 3, 30))


def test_unknown_basis_raises():
    with pytest.raises(ValueError):
        periods.resolve_comparison_window(date(2026, 6, 1), date(2026, 6, 30), 'nonsense')
