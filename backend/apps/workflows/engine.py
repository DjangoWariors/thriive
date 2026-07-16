"""Pure workflow computation — no ORM, no I/O. Exact-result unit tested.

Three concerns:
  * ``evaluate_condition`` — does a step run, given the frozen context? (conditional/threshold routing)
  * ``step_satisfied``     — is a step decided, given its votes? (single / all / any)
  * ``sla_due_at``         — deadline for an activated step.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

_NUMERIC_OPS = frozenset(('gt', 'gte', 'lt', 'lte'))


def _to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def evaluate_condition(context: dict, condition: dict | None) -> bool:
    """True if the step should be included. No condition → always included.

    A condition is ``{"field": ..., "op": ..., "value": ...}``. Numeric ops coerce
    both sides to Decimal (so ``impact_amount`` strings compare correctly); a
    non-numeric or missing operand makes a numeric comparison False.
    """
    if not condition:
        return True
    field = condition.get('field')
    op = condition.get('op', 'eq')
    expected = condition.get('value')
    actual = (context or {}).get(field)

    if op in _NUMERIC_OPS:
        a, b = _to_decimal(actual), _to_decimal(expected)
        if a is None or b is None:
            return False
        if op == 'gt':
            return a > b
        if op == 'gte':
            return a >= b
        if op == 'lt':
            return a < b
        return a <= b
    if op == 'eq':
        return actual == expected
    if op == 'ne':
        return actual != expected
    if op == 'in':
        return actual in (expected or [])
    if op == 'not_in':
        return actual not in (expected or [])
    return True


def step_satisfied(mode: str, approvals: int, rejections: int, assignee_count: int) -> str:
    """Resolve a step from its votes → ``'approved'`` | ``'rejected'`` | ``'pending'``.

    Any rejection sinks the step (segregation rejects are decisive). Otherwise:
      * ``all`` — every assigned approver must approve.
      * ``single`` / ``any`` — the first approval carries.
    """
    if rejections > 0:
        return 'rejected'
    needed = max(assignee_count, 1) if mode == 'all' else 1
    return 'approved' if approvals >= needed else 'pending'


def sla_due_at(activated_at: datetime, sla_hours) -> datetime | None:
    """Deadline for a step activated at ``activated_at``. No SLA configured → None."""
    if not sla_hours:
        return None
    try:
        hours = float(sla_hours)
    except (ValueError, TypeError):
        return None
    return activated_at + timedelta(hours=hours)
