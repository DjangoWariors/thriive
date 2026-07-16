"""Pure payout computation — no ORM, no I/O.

``compute_entity`` turns one entity's inputs (variable pay, achievements by KPI code,
optional approved exception) and a scheme definition into a fully-explained
``PayoutResult``: per-KPI line results with the matched tier, the multiplier before and
after adjustments, and a treatment label for every deviation from "actual".

Money math is deterministic: line payouts are quantized to 2dp with ROUND_HALF_UP at the
line level and then summed exactly. ``weighted_multiplier`` (4dp) is display-only — money
is never re-derived from it.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

_Q2 = Decimal('0.01')
_Q4 = Decimal('0.0001')
_HUNDRED = Decimal('100')

# Treatment labels (mirror PayoutLineItem.TREATMENT_CHOICES)
TREATMENT_ACTUAL = 'actual'
TREATMENT_DEFAULT_1X = 'default_1x'
TREATMENT_ZERO = 'zero'
TREATMENT_BELOW_THRESHOLD = 'below_threshold'
TREATMENT_CAPPED = 'capped'

# Gatekeeper statuses (mirror Payout.GATEKEEPER_STATUS_CHOICES)
GK_NOT_APPLICABLE = 'not_applicable'
GK_PASSED = 'passed'
GK_FAILED = 'failed'
GK_EXEMPTED = 'exempted'

# Scheme gatekeeper actions / exception actions (mirror model choices)
ACTION_ZERO_PAYOUT = 'zero_payout'
ACTION_CAP_AT_1X = 'cap_at_1x'
KPI_ACTION_ACTUAL = 'actual_performance'
KPI_ACTION_DEFAULT_1X = 'default_1x'
KPI_ACTION_ZERO = 'zero'
GK_ACTION_EXEMPTED = 'exempted'


@dataclass(frozen=True)
class TierInput:
    min_pct: Decimal
    max_pct: Decimal | None  # None = unlimited (last tier only)
    multiplier: Decimal


@dataclass(frozen=True)
class SchemeKPIInput:
    kpi_code: str
    category: str  # 'sales' | 'execution'
    weightage: Decimal
    min_qualifying_pct: Decimal | None
    multiplier_cap: Decimal | None
    tiers: tuple[TierInput, ...]  # sorted by min_pct


@dataclass(frozen=True)
class GateInput:
    """One gate criterion; ALL gates must pass or ``gatekeeper_action`` applies."""
    kpi_code: str
    operator: str  # 'gte' | 'gt'
    threshold_pct: Decimal


@dataclass
class GateResult:
    kpi_code: str
    achievement_pct: Decimal
    operator: str
    threshold_pct: Decimal
    passed: bool


@dataclass(frozen=True)
class SchemeInput:
    code: str
    vp_basis_pct: Decimal
    overall_cap_pct: Decimal | None
    gates: tuple[GateInput, ...]
    gatekeeper_action: str  # 'zero_payout' | 'cap_at_1x' — applied when any gate fails
    kpis: tuple[SchemeKPIInput, ...]


@dataclass(frozen=True)
class AchievementInput:
    achievement_pct: Decimal
    target_value: Decimal
    achieved_value: Decimal


@dataclass(frozen=True)
class ExceptionInput:
    sales_kpi_action: str
    execution_kpi_action: str
    gatekeeper_action: str


@dataclass(frozen=True)
class NodeInput:
    entity_id: int
    variable_pay: Decimal
    eligible_working_days: int | None  # None = full period
    period_working_days: int
    achievements: dict[str, AchievementInput]  # by kpi_code
    exception: ExceptionInput | None  # approved exception only


@dataclass
class LineResult:
    kpi_code: str
    category: str
    achievement_pct: Decimal
    target_value: Decimal
    achieved_value: Decimal
    tier_min: Decimal | None
    tier_max: Decimal | None
    base_multiplier: Decimal
    applied_multiplier: Decimal
    weightage: Decimal
    weighted_multiplier: Decimal
    line_payout: Decimal
    treatment: str


@dataclass
class PayoutResult:
    entity_id: int
    proration_factor: Decimal
    eligible_vp: Decimal
    gatekeeper_status: str
    gate_results: list[GateResult]
    gross_payout: Decimal
    capped: bool
    total_payout: Decimal
    total_multiplier: Decimal
    lines: list[LineResult]
    warnings: list[str] = field(default_factory=list)


def match_tier(tiers: tuple[TierInput, ...], pct: Decimal) -> TierInput | None:
    """Min inclusive, max exclusive; max None = unlimited."""
    for tier in tiers:
        if pct >= tier.min_pct and (tier.max_pct is None or pct < tier.max_pct):
            return tier
    return None


def validate_tiers(tiers: list[TierInput] | tuple[TierInput, ...]) -> list[str]:
    """Structural validation shared by SchemeService and serializers.
    Tiers must be sorted, contiguous from 0, with exactly the last tier unbounded."""
    errors: list[str] = []
    if not tiers:
        return ['At least one tier is required.']
    if tiers[0].min_pct != 0:
        errors.append('First tier must start at 0%.')
    for i, tier in enumerate(tiers):
        is_last = i == len(tiers) - 1
        if tier.multiplier < 0:
            errors.append(f'Tier {i + 1}: multiplier cannot be negative.')
        if is_last:
            if tier.max_pct is not None:
                errors.append('Last tier must be unbounded (no max).')
            continue
        if tier.max_pct is None:
            errors.append(f'Tier {i + 1}: only the last tier may be unbounded.')
        elif tier.max_pct <= tier.min_pct:
            errors.append(f'Tier {i + 1}: max must be greater than min.')
        elif tiers[i + 1].min_pct != tier.max_pct:
            errors.append(
                f'Tier {i + 2}: must start at {tier.max_pct}% (tiers must be contiguous).'
            )
    return errors


def _category_action(exception: ExceptionInput | None, category: str) -> str:
    if exception is None:
        return KPI_ACTION_ACTUAL
    if category == 'sales':
        return exception.sales_kpi_action
    return exception.execution_kpi_action


def compute_entity(scheme: SchemeInput, e: NodeInput) -> PayoutResult:
    warnings: list[str] = []

    # 1-2. Proration and eligible VP
    if e.eligible_working_days is None:
        proration = Decimal('1.0000')
    else:
        proration = (
            Decimal(e.eligible_working_days) / Decimal(e.period_working_days)
        ).quantize(_Q4, rounding=ROUND_HALF_UP)
    eligible_vp = (
        e.variable_pay * scheme.vp_basis_pct / _HUNDRED * proration
    ).quantize(_Q2, rounding=ROUND_HALF_UP)

    # 3. Gate criteria — ALL must pass; one consequence (gatekeeper_action) on any failure.
    #    An approved exception with gatekeeper_action='exempted' waives all gates at once.
    gk_status = GK_NOT_APPLICABLE
    gate_results: list[GateResult] = []
    if scheme.gates:
        for gate in scheme.gates:
            achievement = e.achievements.get(gate.kpi_code)
            if achievement is None:
                pct = Decimal('0')
                warnings.append(f'No achievement for gate KPI {gate.kpi_code}.')
            else:
                pct = achievement.achievement_pct
            passed = pct > gate.threshold_pct if gate.operator == 'gt' else pct >= gate.threshold_pct
            gate_results.append(GateResult(
                kpi_code=gate.kpi_code, achievement_pct=pct,
                operator=gate.operator, threshold_pct=gate.threshold_pct, passed=passed,
            ))
        if all(g.passed for g in gate_results):
            gk_status = GK_PASSED
        elif e.exception is not None and e.exception.gatekeeper_action == GK_ACTION_EXEMPTED:
            gk_status = GK_EXEMPTED
        else:
            gk_status = GK_FAILED
    gk_caps_at_1x = gk_status == GK_FAILED and scheme.gatekeeper_action == ACTION_CAP_AT_1X

    # 4. Per-KPI lines
    lines: list[LineResult] = []
    for skpi in scheme.kpis:
        achievement = e.achievements.get(skpi.kpi_code)
        if achievement is None:
            achievement = AchievementInput(Decimal('0'), Decimal('0'), Decimal('0'))
            warnings.append(f'No achievement for KPI {skpi.kpi_code}; treated as 0%.')
        pct = achievement.achievement_pct

        action = _category_action(e.exception, skpi.category)
        tier_min: Decimal | None = None
        tier_max: Decimal | None = None
        base = Decimal('0')

        if action == KPI_ACTION_ZERO:
            applied = Decimal('0')
            treatment = TREATMENT_ZERO
        elif action == KPI_ACTION_DEFAULT_1X:
            applied = Decimal('1.000')
            treatment = TREATMENT_DEFAULT_1X
        else:
            tier = match_tier(skpi.tiers, pct)
            if tier is None:
                warnings.append(f'No tier matched {pct}% for KPI {skpi.kpi_code}.')
            else:
                tier_min, tier_max, base = tier.min_pct, tier.max_pct, tier.multiplier
            applied = base
            treatment = TREATMENT_ACTUAL
            if skpi.min_qualifying_pct is not None and pct < skpi.min_qualifying_pct:
                applied = Decimal('0')
                treatment = TREATMENT_BELOW_THRESHOLD

        if skpi.multiplier_cap is not None and applied > skpi.multiplier_cap:
            applied = skpi.multiplier_cap
            treatment = TREATMENT_CAPPED
        if gk_caps_at_1x and applied > 1:
            applied = Decimal('1.000')
            treatment = TREATMENT_CAPPED

        line_payout = (
            eligible_vp * applied * skpi.weightage / _HUNDRED
        ).quantize(_Q2, rounding=ROUND_HALF_UP)
        weighted = (applied * skpi.weightage / _HUNDRED).quantize(_Q4, rounding=ROUND_HALF_UP)

        lines.append(LineResult(
            kpi_code=skpi.kpi_code,
            category=skpi.category,
            achievement_pct=pct,
            target_value=achievement.target_value,
            achieved_value=achievement.achieved_value,
            tier_min=tier_min,
            tier_max=tier_max,
            base_multiplier=base,
            applied_multiplier=applied,
            weightage=skpi.weightage,
            weighted_multiplier=weighted,
            line_payout=line_payout,
            treatment=treatment,
        ))

    # 5-7. Totals, gatekeeper zeroing, overall cap
    gross = sum((line.line_payout for line in lines), Decimal('0.00'))
    total = gross
    capped = False
    if gk_status == GK_FAILED and scheme.gatekeeper_action == ACTION_ZERO_PAYOUT:
        total = Decimal('0.00')
    elif scheme.overall_cap_pct is not None:
        cap = (eligible_vp * scheme.overall_cap_pct / _HUNDRED).quantize(
            _Q2, rounding=ROUND_HALF_UP,
        )
        if total > cap:
            total = cap
            capped = True

    total_multiplier = sum((line.weighted_multiplier for line in lines), Decimal('0.0000'))

    return PayoutResult(
        entity_id=e.entity_id,
        proration_factor=proration,
        eligible_vp=eligible_vp,
        gatekeeper_status=gk_status,
        gate_results=gate_results,
        gross_payout=gross,
        capped=capped,
        total_payout=total,
        total_multiplier=total_multiplier,
        lines=lines,
        warnings=warnings,
    )
