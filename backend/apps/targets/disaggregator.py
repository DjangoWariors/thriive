"""Disaggregation engines — pure computation, no ORM.

split_spatial divides a parent GEOGRAPHY node's target among its children by weight;
apply_constraints clamps each part to its growth floor/cap while still reconciling.

The one invariant: the parts sum back to the whole, exactly. A target that leaks a rupee
on the way down the tree is unusable, so the last part always absorbs the rounding
remainder. Everything is Decimal; the service supplies the weights (historical bases,
growth-adjusted bases, driver values, or all-equal).
"""
from decimal import ROUND_HALF_UP, Decimal


def _quantum(unit) -> Decimal:
    """Rounding step. unit=1 → whole numbers, 100 → nearest hundred, etc. Defaults to 0.0001."""
    try:
        u = Decimal(str(unit))
    except (ValueError, ArithmeticError):
        u = Decimal('0.0001')
    return u if u > 0 else Decimal('0.0001')


def split_by_weights(total, parts: list[tuple], unit=None) -> dict:
    """Split ``total`` across ``parts`` (a list of ``(key, weight)``) in proportion to weight.

    Returns ``{key: Decimal}`` that sums to exactly ``total``. Each part is rounded to ``unit``;
    the final part takes whatever remainder is left so nothing is gained or lost. If every weight
    is zero (no signal), the total is split equally.
    """
    total = Decimal(str(total))
    if not parts:
        return {}

    quantum = _quantum(unit) if unit is not None else None
    weights = [Decimal(str(w)) for _, w in parts]
    weight_sum = sum(weights)
    if weight_sum <= 0:  # no signal → equal split
        weights = [Decimal('1')] * len(parts)
        weight_sum = Decimal(len(parts))

    result: dict = {}
    running = Decimal('0')
    last = len(parts) - 1
    for i, (key, _) in enumerate(parts):
        if i == last:
            value = total - running  # remainder → exact reconciliation
        else:
            value = total * weights[i] / weight_sum
            if quantum is not None:
                # Round to the nearest multiple of the unit (unit=1 → whole, 100 → nearest 100).
                value = (value / quantum).to_integral_value(rounding=ROUND_HALF_UP) * quantum
            running += value
        result[key] = value
    return result


def split_spatial(parent_total, children: list[tuple], unit=None) -> dict:
    """Divide a parent node's target among children. ``children`` = ``[(node_id, weight)]``."""
    return split_by_weights(parent_total, children, unit=unit)


def apply_constraints(split: dict, order: list, bases: dict, constraints: dict | None, total, unit=None) -> dict:
    """Clamp each part of ``split`` to its growth floor/cap (relative to its base in ``bases``),
    an absolute floor, and/or no-negative — then redistribute the difference across the
    unclamped parts so the whole still reconciles exactly. ``order`` fixes which part absorbs
    the final remainder (the last one)."""
    if not constraints:
        return split
    total = Decimal(str(total))
    min_g = constraints.get('min_growth_pct')
    max_g = constraints.get('max_growth_pct')
    floor = constraints.get('floor_value')
    no_neg = constraints.get('no_negative')

    clamped, is_clamped = {}, {}
    for key in order:
        base = bases.get(key)
        lo, hi = None, None
        if no_neg:
            lo = Decimal('0')
        if floor is not None:
            lo = Decimal(str(floor)) if lo is None else max(lo, Decimal(str(floor)))
        if base is not None and min_g is not None:
            b = base * (1 + Decimal(str(min_g)) / 100)
            lo = b if lo is None else max(lo, b)
        if base is not None and max_g is not None:
            hi = base * (1 + Decimal(str(max_g)) / 100)
        value = split[key]
        new = value
        if lo is not None and new < lo:
            new = lo
        if hi is not None and new > hi:
            new = hi
        clamped[key] = new
        is_clamped[key] = new != value

    delta = total - sum(clamped.values(), Decimal('0'))
    if delta == 0:
        return clamped
    free = [k for k in order if not is_clamped[k]]
    if free:
        free_total = sum((split[k] for k in free), Decimal('0'))
        running = Decimal('0')
        quant = _quantum(unit) if unit else None
        for idx, k in enumerate(free):
            if idx == len(free) - 1:
                clamped[k] += delta - running  # last free part absorbs the remainder
            else:
                share = delta * (split[k] / free_total) if free_total > 0 else delta / len(free)
                if quant:
                    share = (share / quant).to_integral_value(rounding=ROUND_HALF_UP) * quant
                clamped[k] += share
                running += share
    else:
        clamped[order[-1]] += delta  # everything clamped → last part absorbs
    return clamped


