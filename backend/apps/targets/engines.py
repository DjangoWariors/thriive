"""Plan-run computation engines — pure, no ORM (docs/TARGET_MODULE_REVAMP_PLAN.md §4–§5).

The plan pipeline feeds these engines plain dicts (history, attributes, metric values fetched
by the service layer) and writes the results to staging. Everything is Decimal and
deterministic; explain payloads are JSON-safe so they can land in ``RunAllocation.explain``
unchanged — the RFP's "logics must be explained".

  blend_baselines    — Stage 1: blend per-basis history into one base per node
  resolve_weights    — Stage 3: blend a recipe's weight components into per-child weights
  apply_growth       — Stage 3: tilt weights by differential growth
  split_product_mix  — Stage 4: divide a node total across SKU groups (fixed % + local mix)

The splitting/clamping math lives in disaggregator.py (split_by_weights,
apply_constraints); these engines produce the inputs it consumes.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_HUNDRED = Decimal('100')


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, '') else Decimal('0')
    except (InvalidOperation, ValueError):
        return Decimal('0')


# ── Stage 1: baseline ─────────────────────────────────────────────────────────
def blend_baselines(components: list, per_basis: dict) -> dict:
    """Blend per-basis node values into one base per node.

    ``components`` = ``[{"basis": "ly_same_period", "weight": 60}, ...]`` (weights normalised,
    so 60/40 and 3/2 mean the same). ``per_basis`` = ``{basis: {node_key: value}}`` as fetched
    by the service — a node missing from a basis simply contributes 0 there (a territory with
    no LY history still gets its L3M share).

    Returns ``{node_key: Decimal}`` over the union of node keys.
    """
    if not components:
        raise ValueError('A baseline needs at least one component.')
    weights = [_dec(c.get('weight', 1)) for c in components]
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError('Baseline component weights must sum to a positive number.')

    keys = {k for c in components for k in per_basis.get(c.get('basis'), {})}
    result = {}
    for key in keys:
        value = Decimal('0')
        for c, w in zip(components, weights):
            value += _dec(per_basis.get(c.get('basis'), {}).get(key)) * w / total_w
        result[key] = value
    return result


# ── Stage 3: recipe weights ───────────────────────────────────────────────────
def resolve_weights(components: list, inputs: list, keys: list) -> tuple[dict, dict]:
    """Blend a recipe's weight components into one weight per child, with explain.

    ``components`` = ``AllocationRecipe.weight_components``; ``inputs`` is a parallel list of
    ``{child_key: raw_value}`` fetched by the service (history for ``contribution``, the
    attribute value for ``attribute``, the metric value for ``external_metric``; ignored for
    ``equal``). ``keys`` fixes the child set and its order.

    Each component's raw values are normalised to shares *within the siblings* before
    blending — so "70% contribution + 30% outlet count" mixes proportions, never raw ₹
    against raw counts. A component with no signal (all zeros) degrades to equal shares,
    flagged ``no_signal`` in the explain payload.

    Returns ``(weights, explain)``: ``weights`` = ``{child_key: Decimal}`` summing to 1;
    ``explain`` = ``{child_key: {"weight": str, "components": [...]}}`` — JSON-safe.
    """
    if not components:
        raise ValueError('A recipe needs at least one weight component.')
    if not keys:
        return {}, {}
    if len(inputs) != len(components):
        raise ValueError('resolve_weights needs one input map per component.')

    comp_weights = [_dec(c.get('weight', 1)) for c in components]
    total_cw = sum(comp_weights)
    if total_cw <= 0:
        raise ValueError('Recipe component weights must sum to a positive number.')

    n = Decimal(len(keys))
    weights = {k: Decimal('0') for k in keys}
    explain = {k: {'components': []} for k in keys}

    for component, raw_map, cw in zip(components, inputs, comp_weights):
        source = component.get('source', 'equal')
        raws = {k: (Decimal('1') if source == 'equal' else _dec((raw_map or {}).get(k))) for k in keys}
        raw_total = sum(raws.values())
        no_signal = raw_total <= 0
        cw_norm = cw / total_cw
        for k in keys:
            share = (Decimal('1') / n) if no_signal else raws[k] / raw_total
            weights[k] += cw_norm * share
            explain[k]['components'].append({
                'source': source,
                **({'key': component['key']} if component.get('key') else {}),
                'weight_pct': str((cw_norm * _HUNDRED).quantize(Decimal('0.01'))),
                'raw': str(raws[k]),
                'share_pct': str((share * _HUNDRED).quantize(Decimal('0.01'))),
                **({'no_signal': True} if no_signal else {}),
            })

    for k in keys:
        explain[k]['weight'] = str(weights[k])
    return weights, explain


def apply_growth(weights: dict, growth_pct: dict) -> dict:
    """Tilt weights by differential growth: ``weight × (1 + g/100)`` per key.

    Uniform growth cancels out when the tilted weights are re-normalised by the splitter —
    only *differential* growth changes the distribution, which is exactly the FMCG intent
    ("push North 3 points harder"). The caller resolves per-node growth (default +
    per-level overrides) into a flat ``{key: pct}``; a missing key means 0. A growth below
    -100% clamps the weight to 0 rather than going negative.
    """
    out = {}
    for key, weight in weights.items():
        factor = Decimal('1') + _dec(growth_pct.get(key)) / _HUNDRED
        out[key] = weight * factor if factor > 0 else Decimal('0')
    return out


# ── Stage 4: product split ────────────────────────────────────────────────────
def split_product_mix(total, groups: list, history: dict, fixed_mix: dict | None = None,
                      unit=None) -> dict:
    """Divide a node's total across SKU groups; the parts sum back exactly.

    ``fixed_mix`` (``{group: pct}``) takes its percentage off the top — the NPI-seeding case,
    where a new group has no history to earn a share from. The remainder splits across the
    other groups in proportion to ``history`` (``{group: value}``, the node's local product
    mix); if none of them has history, the remainder splits equally (the splitter's
    documented no-signal fallback).
    """
    from . import disaggregator

    if not groups:
        raise ValueError('split_product_mix needs at least one group.')
    total = _dec(total)
    fixed_mix = {g: _dec(p) for g, p in (fixed_mix or {}).items()}

    unknown = set(fixed_mix) - set(groups)
    if unknown:
        raise ValueError(f'fixed_mix names groups outside the plan scope: {sorted(unknown)}.')
    fixed_total_pct = sum(fixed_mix.values())
    if fixed_total_pct > _HUNDRED:
        raise ValueError(f'fixed_mix percentages sum to {fixed_total_pct}% — more than 100%.')

    quantum = disaggregator._quantum(unit) if unit is not None else None
    result, fixed_sum = {}, Decimal('0')
    fixed_groups = [g for g in groups if g in fixed_mix]
    for g in fixed_groups:
        amount = total * fixed_mix[g] / _HUNDRED
        if quantum is not None:
            amount = (amount / quantum).to_integral_value(rounding=ROUND_HALF_UP) * quantum
        result[g] = amount
        fixed_sum += amount

    rest = [g for g in groups if g not in fixed_mix]
    remainder = total - fixed_sum
    if rest:
        result.update(disaggregator.split_by_weights(
            remainder, [(g, history.get(g, 0)) for g in rest], unit=unit))
    elif fixed_groups:
        result[fixed_groups[-1]] += remainder  # 100% fixed → last group absorbs rounding
    return result
