"""Comparison-window resolution for growth KPIs. Pure date math — no ORM.

Most FMCG targets are expressed as growth over a base period ("10% over LYSM").
A growth KPI computes its measure over the current window AND over a base window;
this module derives that base window from the current one and a ``basis``.

Because the caller passes the *actual* current window, "to-date" comparison is
automatic: if you compute on the 12th with a window of (month-1st … 12th), the
LYSM basis yields last-year (month-1st … 12th) — i.e. MTD vs MTD.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

LAST_YEAR_SAME_PERIOD = 'last_year_same_period'
PREVIOUS_PERIOD = 'previous_period'
PREVIOUS_MONTH = 'previous_month'
CUSTOM_MONTH_OFFSET = 'custom_month_offset'

BASIS_CHOICES = (
    LAST_YEAR_SAME_PERIOD,
    PREVIOUS_PERIOD,
    PREVIOUS_MONTH,
    CUSTOM_MONTH_OFFSET,
)


def _shift_months(d: date, months: int) -> date:
    """Shift a date back/forward by whole months, clamping the day to the target
    month's length (e.g. Mar 31 − 1 month → Feb 28/29)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def resolve_comparison_window(start: date, end: date, basis: str, offset: int | None = None):
    """Return ``(base_start, base_end)`` for the given current window and basis.

    Raises ValueError on an unknown basis or a missing custom offset.
    """
    if basis == LAST_YEAR_SAME_PERIOD:
        return _shift_months(start, -12), _shift_months(end, -12)

    if basis == PREVIOUS_MONTH:
        return _shift_months(start, -1), _shift_months(end, -1)

    if basis == CUSTOM_MONTH_OFFSET:
        if not offset:
            raise ValueError('custom_month_offset basis requires a non-zero offset.')
        return _shift_months(start, -offset), _shift_months(end, -offset)

    if basis == PREVIOUS_PERIOD:
        window_len = (end - start).days + 1
        base_end = start - timedelta(days=1)
        base_start = base_end - timedelta(days=window_len - 1)
        return base_start, base_end

    raise ValueError(f'Unknown comparison basis: {basis!r}')


# ── run-rate / MTD projection ────────────────────────────────────────────────
def working_days_between(start: date, end: date, week_off=(6,)) -> int:
    """Count working days in [start, end] inclusive, excluding the weekly off-days
    (default: Sunday=6). A pragmatic FMCG default until a holiday calendar is configured."""
    if end < start:
        return 0
    count = 0
    d = start
    for _ in range((end - start).days + 1):
        if d.weekday() not in week_off:
            count += 1
        d += timedelta(days=1)
    return count


def project_full_period(value, elapsed_working_days: int, total_working_days: int) -> Decimal:
    """Project a month-to-date value to the full period at the current run-rate:
    ``value × total ÷ elapsed``. Returns ``value`` unchanged if nothing has elapsed."""
    value = Decimal(str(value))
    if elapsed_working_days <= 0:
        return value
    return value * Decimal(total_working_days) / Decimal(elapsed_working_days)
