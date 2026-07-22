// Types matching apps/incentives serializers exactly. All decimals are strings.

export type IncentiveCategory = 'sales' | 'execution';
export type GatekeeperAction = 'zero_payout' | 'cap_at_1x';
export type GatekeeperStatus = 'not_applicable' | 'passed' | 'failed' | 'exempted';
export type KpiExceptionAction = 'actual_performance' | 'default_1x' | 'zero';
export type ExceptionGatekeeperAction = 'no_exemption' | 'exempted';
export type ExceptionStatus = 'pending' | 'approved' | 'rejected';
export type LineTreatment = 'actual' | 'default_1x' | 'zero' | 'below_threshold' | 'capped';

export type PayoutFrequency = 'monthly' | 'annual';

export type PayoutRunStatus =
  | 'computing'
  | 'computed'
  | 'failed'
  | 'under_review'
  | 'approved'
  | 'paid'
  | 'superseded';

export type PayoutRunKind = 'estimate' | 'final' | 'adjustment';

// ── scheme config ───────────────────────────────────────────────────────────

export interface MultiplierTier {
  min_achievement_pct: string;
  max_achievement_pct: string | null; // null = unlimited (last tier)
  multiplier: string;
}

export interface SchemeKPI {
  id: number;
  kpi: number;
  kpi_code: string;
  kpi_name: string;
  incentive_category: IncentiveCategory;
  weightage: string;
  min_qualifying_pct: string | null;
  multiplier_cap: string | null;
  display_order: number;
  tiers: MultiplierTier[];
}

export interface IncentiveSchemeListItem {
  id: number;
  code: string;
  name: string;
  description: string;
  entity_type_code: string;
  entity_type_name: string;
  channel_code: string | null;
  payout_frequency: PayoutFrequency;
  vp_basis_pct: string;
  overall_cap_pct: string | null;
  has_gatekeeper: boolean;
  kpi_count: number;
  version: number;
  is_current: boolean;
  is_active: boolean;
  effective_from: string;
  updated_at: string;
}

export interface IncentiveScheme {
  id: number;
  code: string;
  name: string;
  description: string;
  target_entity_type: number;
  entity_type_code: string;
  entity_type_name: string;
  channel: number | null;
  channel_code: string | null;
  payout_frequency: PayoutFrequency;
  vp_basis_pct: string;
  overall_cap_pct: string | null;
  gates: SchemeGate[];
  gatekeeper_action: GatekeeperAction;
  kpis: SchemeKPI[];
  version: number;
  is_current: boolean;
  is_active: boolean;
  effective_from: string;
  effective_to: string | null;
  updated_at: string;
}

export type GateOperator = 'gte' | 'gt';

/** One gate criterion — ALL gates must pass or the scheme's gatekeeper_action applies. */
export interface SchemeGate {
  id: number;
  kpi: number;
  kpi_code: string;
  kpi_name: string;
  operator: GateOperator;
  threshold_pct: string;
  display_order: number;
}

export interface SchemeGatePayload {
  kpi: number;
  operator?: GateOperator;
  threshold_pct: string;
  display_order?: number;
}

export interface GateResult {
  kpi_code: string;
  achievement_pct: string;
  operator: GateOperator;
  threshold_pct: string;
  passed: boolean;
}

export interface SchemeKPIPayload {
  kpi: number;
  incentive_category: IncentiveCategory;
  weightage: string;
  min_qualifying_pct?: string | null;
  multiplier_cap?: string | null;
  display_order?: number;
  tiers: MultiplierTier[];
}

export interface SchemePayload {
  name: string;
  code: string;
  description?: string;
  target_entity_type: number;
  channel?: number | null;
  payout_frequency?: PayoutFrequency;
  vp_basis_pct?: string;
  overall_cap_pct?: string | null;
  gates?: SchemeGatePayload[];
  gatekeeper_action?: GatekeeperAction;
  effective_from?: string;
  kpis: SchemeKPIPayload[];
}

export interface SchemeValidateResult {
  valid: boolean;
  errors: string[];
}

// ── variable pay ────────────────────────────────────────────────────────────

export interface VariablePay {
  id: number;
  entity: number;
  entity_name: string;
  entity_code: string;
  target_period: number;
  period_code: string;
  amount: string;
  eligible_working_days: number | null;
  source: 'manual' | 'bulk_import';
  updated_at: string;
}

export interface VariablePayBulkResult {
  created: number;
  updated: number;
  errors: Array<{ row: number; errors: string[] }>;
}

// ── payout runs ─────────────────────────────────────────────────────────────

export interface PayoutRun {
  id: number;
  scheme: number;
  scheme_code: string;
  scheme_name: string;
  scheme_version: number;
  target_period: number;
  period_code: string;
  kind: PayoutRunKind;
  cycle: number | null;
  reference_run: number | null;
  status: PayoutRunStatus;
  computation_log_id: number | null;
  submitted_by: number | null;
  submitted_by_name: string | null;
  submitted_at: string | null;
  approved_by: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  rejection_reason: string;
  paid_at: string | null;
  payment_ref: string;
  entities_processed: number;
  error_count: number;
  total_payout: string;
  errors: Array<{ entity_id: number; entity_name?: string; code: string; error: string }>;
  created_at: string;
  updated_at: string;
}

// ── payouts ─────────────────────────────────────────────────────────────────

export interface PayoutLineItem {
  id: number;
  kpi_code: string;
  kpi_name: string;
  kpi_id: number;
  incentive_category: IncentiveCategory;
  target_value: string;
  achieved_value: string;
  achievement_pct: string;
  tier_min: string | null;
  tier_max: string | null;
  base_multiplier: string;
  applied_multiplier: string;
  weightage: string;
  weighted_multiplier: string;
  line_payout: string;
  treatment: LineTreatment;
}

export interface PayoutListItem {
  id: number;
  run: number;
  run_status: PayoutRunStatus;
  scheme: number;
  scheme_code: string;
  target_period: number;
  entity: number;
  entity_name: string;
  entity_code: string;
  entity_type_code: string;
  variable_pay_amount: string;
  proration_factor: string;
  eligible_vp: string;
  gatekeeper_status: GatekeeperStatus;
  has_exception: boolean;
  gross_payout: string;
  capped: boolean;
  total_payout: string;
  total_multiplier: string;
  hold_status: HoldStatus;
  hold_reason: string;
  adjustment_amount: string;
}

export interface PayoutException {
  id: number;
  entity: number;
  entity_name: string;
  entity_code: string;
  target_period: number;
  period_code: string;
  scheme: number | null;
  scheme_code: string | null;
  category: string;
  category_ref: number | null;
  category_name: string | null;
  sales_kpi_action: KpiExceptionAction;
  execution_kpi_action: KpiExceptionAction;
  gatekeeper_action: ExceptionGatekeeperAction;
  reason: string;
  reference_date: string | null;
  /** Set on auto-materialized children of a multi-month exception. */
  parent: number | null;
  children_count: number;
  status: ExceptionStatus;
  requested_by: number | null;
  requested_by_name: string | null;
  approved_by: number | null;
  approved_at: string | null;
  rejection_reason: string;
  impact_amount: string | null;
  workflow_id: number | null;
  workflow_status: string | null;
  current_step_name: string | null;
  created_at: string;
}

export interface ExceptionDurationConfig {
  type?: 'fixed' | 'join_day_cutoff';
  effect_months?: number;
  cutoff_day?: number;
  months_on_or_before?: number;
  months_after?: number;
}

export interface ExceptionCategory {
  id: number;
  code: string;
  name: string;
  description: string;
  /** Null = all channels. */
  channel: number | null;
  channel_code: string | null;
  duration_config: ExceptionDurationConfig;
  default_sales_kpi_action: KpiExceptionAction;
  default_execution_kpi_action: KpiExceptionAction;
  default_gatekeeper_action: ExceptionGatekeeperAction;
  requires_dates: boolean;
  workflow_definition_code: string;
}

export interface PayoutDetail {
  id: number;
  run: number;
  run_status: PayoutRunStatus;
  scheme: number;
  scheme_code: string;
  scheme_name: string;
  scheme_version: number;
  target_period: number;
  period_code: string;
  period_name: string;
  entity: number;
  entity_name: string;
  entity_code: string;
  variable_pay_amount: string;
  proration_factor: string;
  eligible_vp: string;
  gatekeeper_status: GatekeeperStatus;
  gate_results: GateResult[];
  exception: PayoutException | null;
  gross_payout: string;
  capped: boolean;
  total_payout: string;
  total_multiplier: string;
  hold_status: HoldStatus;
  hold_reason: string;
  can_hold: boolean;
  can_release: boolean;
  adjustment_amount: string;
  computation_id: number | null;
  computed_at: string;
  line_items: PayoutLineItem[];
}

export interface PayoutSummary {
  total_payout: string;
  entities: number;
  capped_count: number;
  gatekeeper_failed_count: number;
  exception_count: number;
}

// ── list params ─────────────────────────────────────────────────────────────

export interface PayoutListParams {
  period?: number;
  scheme?: number;
  run?: number;
  run_status?: PayoutRunStatus;
  entity_type?: string;
  page?: number;
  page_size?: number;
}

export interface RunListParams {
  period?: number;
  scheme?: number;
  status?: PayoutRunStatus;
}

// ── payout cycles (month-close) ───────────────────────────────────────────────

export type HoldStatus = 'none' | 'held' | 'released';

export type CycleStatus =
  | 'open'
  | 'finalizing'
  | 'computing'
  | 'under_review'
  | 'approved'
  | 'disbursed'
  | 'closed';

export type ReadinessStatus = 'green' | 'warning' | 'red';

export interface ReadinessCheck {
  key: string;
  label: string;
  status: ReadinessStatus;
  count: number;
  detail: string;
}

export interface CycleReadiness {
  is_ready: boolean;
  checks: ReadinessCheck[];
  computed_at: string;
}

export interface PayoutCycle {
  id: number;
  target_period: number;
  period_code: string;
  period_name: string;
  period_type: string;
  status: CycleStatus;
  readiness: CycleReadiness | Record<string, never>;
  is_ready: boolean | null;
  readiness_overridden: boolean;
  override_reason: string;
  finalized_at: string | null;
  finalized_by: number | null;
  finalized_by_name: string | null;
  achievement_computation_id: number | null;
  submitted_by: number | null;
  submitted_by_name: string | null;
  submitted_at: string | null;
  approved_by: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  disbursed_by: number | null;
  disbursed_by_name: string | null;
  disbursed_at: string | null;
  register_ref: string;
  total_payout: string;
  created_at: string;
  updated_at: string;
}

export interface CycleReviewRow {
  scheme_code: string;
  scheme_name: string;
  total: string;
  payees: number;
}

export interface MoverRow {
  entity_code: string;
  entity_name: string;
  current: string;
  prior: string;
  delta: string;
}

export interface OutlierRow {
  payout_id: number;
  entity_code: string;
  entity_name: string;
  total_payout: string;
}

export interface CycleReview {
  cycle_id: number;
  period_code: string;
  status: CycleStatus;
  stats: {
    total_payout: string;
    payees: number;
    held: number;
    capped: number;
    gated: number;
    exceptions: number;
    adjustments: number;
    adjustments_net: string;
    grand_total: string;
  };
  adjustments: {
    payout_id: number;
    entity_code: string;
    entity_name: string;
    adjustment_amount: string;
    adjustment_for: string | null;
  }[];
  by_scheme: CycleReviewRow[];
  variance: {
    prior_period_code: string;
    prior_total: string;
    delta: string;
    delta_pct: string;
  } | null;
  multiplier_distribution: { bucket: string; count: number }[];
  movers: { gainers: MoverRow[]; losers: MoverRow[] };
  outliers: {
    capped: OutlierRow[];
    gated: OutlierRow[];
    held: OutlierRow[];
    exceptions: OutlierRow[];
  };
}

export interface CycleRegisterRow {
  entity_code: string;
  entity_name: string;
  entity_type: string | null;
  scheme_code: string;
  kind: 'final' | 'adjustment';
  adjustment_for: string;
  eligible_vp: string;
  gross_payout: string;
  total_payout: string;
  gatekeeper_status: GatekeeperStatus;
  hold_status: HoldStatus;
  run_status: PayoutRunStatus;
  payment_ref: string;
  [bankKey: string]: string | null;
}

export interface CycleRegister {
  cycle_id: number;
  period_code: string;
  status: CycleStatus;
  register_ref: string;
  bank_attribute_keys: string[];
  rows: CycleRegisterRow[];
  total_payout: string;
  payee_count: number;
  held_count: number;
}

export interface PayoutStatementLine {
  kpi_code: string;
  achievement_pct: string;
  applied_multiplier: string;
  weightage: string;
  weighted_multiplier: string;
  line_payout: string;
  treatment: LineTreatment;
}

export interface PayoutStatement {
  payout_id: number;
  entity: { code: string; name: string };
  period: { code: string; name: string };
  scheme: { code: string; name: string; version: number };
  variable_pay_amount: string;
  proration_factor: string;
  eligible_vp: string;
  gatekeeper_status: GatekeeperStatus;
  gate_results: GateResult[];
  gross_payout: string;
  capped: boolean;
  total_multiplier: string;
  total_payout: string;
  hold_status: HoldStatus;
  hold_reason: string;
  run_status: PayoutRunStatus;
  payment_ref: string;
  computation_id: number | null;
  lines: PayoutStatementLine[];
}

export interface ExceptionListParams {
  period?: number;
  status?: ExceptionStatus;
  entity?: number;
  page?: number;
}

export interface ExceptionPayload {
  entity: number;
  target_period: number;
  scheme?: number | null;
  category?: string;
  sales_kpi_action: KpiExceptionAction;
  execution_kpi_action: KpiExceptionAction;
  gatekeeper_action: ExceptionGatekeeperAction;
  reason: string;
  /** Required when the category's duration rule keys on a date (e.g. joining date). */
  reference_date?: string | null;
}
