"""Alert evaluation — pure rule matching over computed achievements.

Returns breach dicts; the service persists/resolves ``Alert`` rows. Generic: a rule reads one
metric off an Achievement (or the derived ``no_sale_days``) and compares it to a threshold.
"""
from datetime import date
from decimal import Decimal

from apps.hierarchy.models import Node
from apps.kpi_engine.models import Transaction

from .models import AlertRule

_OPS = {
    'lt': lambda a, b: a < b,
    'lte': lambda a, b: a <= b,
    'gt': lambda a, b: a > b,
    'gte': lambda a, b: a >= b,
    'eq': lambda a, b: a == b,
}

_ACHIEVEMENT_METRICS = {
    AlertRule.ACHIEVEMENT_PCT: 'achievement_pct',
    AlertRule.PROJECTED_PCT: 'projected_pct',
    AlertRule.GAP_TO_TARGET: 'gap_to_target',
    AlertRule.REQUIRED_RUN_RATE: 'required_run_rate',
    AlertRule.GROWTH_PCT: 'growth_pct',
}


def evaluate(target_period, achievements_qs, as_of: date | None = None) -> list[dict]:
    """Evaluate all enabled rules against the period's achievements. Returns breach dicts:
    {rule, entity_id, kpi_id, metric_value, severity, message}."""
    as_of = as_of or date.today()
    rules = list(AlertRule.objects.filter(is_current=True, is_active=True, is_enabled=True))
    if not rules:
        return []

    achievements = list(
        achievements_qs.select_related('entity__entity_type', 'channel', 'kpi')
    )
    breaches: list[dict] = []
    no_sale_cache: dict[int, int] = {}

    for rule in rules:
        op = _OPS.get(rule.comparator)
        if op is None:
            continue

        if rule.metric == AlertRule.NO_SALE_DAYS:
            breaches += _eval_no_sale(rule, achievements, as_of, no_sale_cache, op)
            continue

        field = _ACHIEVEMENT_METRICS.get(rule.metric)
        if not field:
            continue
        for ach in achievements:
            if not _in_scope(rule, ach):
                continue
            value = getattr(ach, field)
            if value is None:  # e.g. growth_pct with no base data
                continue
            value = Decimal(str(value))
            if op(value, rule.threshold):
                breaches.append(_breach(rule, ach.entity, ach.kpi_id, value, ach.kpi.code))
    return breaches


def _eval_no_sale(rule, achievements, as_of, cache, op) -> list[dict]:
    """Days since the entity's subtree last billed. One breach per in-scope entity."""
    seen: set[int] = set()
    out = []
    for ach in achievements:
        entity = ach.entity
        if entity.id in seen or not _in_scope(rule, ach):
            continue
        seen.add(entity.id)
        if entity.id not in cache:
            cache[entity.id] = _days_since_last_sale(entity, as_of)
        days = Decimal(cache[entity.id])
        if op(days, rule.threshold):
            out.append(_breach(rule, entity, None, days))
    return out


def _days_since_last_sale(entity, as_of) -> int:
    # Sales attach to geography: look at the territories this entity owns (via assignments).
    from apps.assignments.services import AssignmentService
    node_ids = AssignmentService.scope_node_ids_for_entity(entity.id, on=as_of)
    last = (
        Transaction.objects.filter(attributed_node_id__in=node_ids, is_active=True)
        .order_by('-transaction_date')
        .values_list('transaction_date', flat=True)
        .first()
    )
    if last is None:
        return 9999  # never billed — large sentinel so any "≥ N days" rule fires
    return (as_of - last).days


def _in_scope(rule, achievement) -> bool:
    if rule.kpi_id and rule.kpi_id != achievement.kpi_id:
        return False
    if rule.scope_entity_types:
        etype = achievement.entity.entity_type
        if not etype or etype.code not in rule.scope_entity_types:
            return False
    if rule.scope_channels:
        chan = achievement.channel
        if not chan or chan.code not in rule.scope_channels:
            return False
    return True


def _breach(rule, entity, kpi_id, value, kpi_code='') -> dict:
    try:
        message = rule.message_template.format(
            entity=entity.name, metric=rule.get_metric_display(), value=value, kpi=kpi_code,
        )
    except (KeyError, IndexError):
        message = f'{entity.name}: {rule.get_metric_display()} is {value}'
    return {
        'rule': rule,
        'entity_id': entity.id,
        'kpi_id': kpi_id,
        'metric_value': value,
        'severity': rule.severity,
        'message': message[:255],
    }
