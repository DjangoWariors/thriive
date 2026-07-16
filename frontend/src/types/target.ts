/** Targets are always set monthly; 'annual' is the fiscal-year container (never carries targets). */
export type PeriodType = 'annual' | 'monthly' | 'scheme' | 'custom';
export type PeriodStatus = 'draft' | 'published' | 'locked' | 'closed';
export type AllocationStatus = 'pending' | 'approved' | 'locked';

export interface TargetPeriod {
  id: number;
  name: string;
  code: string;
  fiscal_year: string;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  parent: number | null;
  channel: number | null;
  working_days: number | null;
  path: string;
  depth: number;
  status: PeriodStatus;
  is_active: boolean;
}

export interface TargetPeriodNode {
  id: number;
  name: string;
  code: string;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  status: PeriodStatus;
  working_days: number | null;
  depth: number;
  children: TargetPeriodNode[];
}

/** Body for the one-click plan-year generator. */
export interface GenerateYearPayload {
  fiscal_year: string;
  start_month?: number;
  channel_id?: number | null;
  working_days_per_month?: number;
}

/** Configurable change-cap. */
export interface RevisionPolicy {
  id: number;
  name: string;
  code: string;
  target_period: number | null;
  channel: number | null;
  entity_type: number | null;
  auto_approve_within_pct: string;
  hard_ceiling_pct: string | null;
  max_revisions_per_period: number | null;
  freeze_after: string | null;
  requires_reason: boolean;
  version: number;
  is_current: boolean;
  is_active: boolean;
}

export interface RevisionPolicyPayload {
  name: string;
  code: string;
  target_period?: number | null;
  channel?: number | null;
  entity_type?: number | null;
  auto_approve_within_pct: string;
  hard_ceiling_pct?: string | null;
  max_revisions_per_period?: number | null;
  freeze_after?: string | null;
  requires_reason: boolean;
}

/** A person's target rolled up from the territories they own (User × Retailer × SKU). */
export interface PersonViewRow {
  allocation_id: number;
  geography_node_id: number;
  geography_node: string | null;
  geography_code: string | null;
  channel: string | null;
  sku_group: string | null;
  target: string;
  status: AllocationStatus;
}

export interface PersonView {
  entity_id: number;
  entity: string;
  entity_code: string;
  owned_node_count: number;
  target: string;
  rows: PersonViewRow[];
}

export interface PeriodPayload {
  name: string;
  code: string;
  fiscal_year?: string;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  parent?: number | null;
  channel?: number | null;
  working_days?: number | null;
}

export interface TargetAllocation {
  id: number;
  target_period: number;
  period_code: string;
  kpi: number;
  kpi_code: string;
  geography_node: number | null;
  geography_name: string | null;
  geography_code: string | null;
  channel: number | null;
  sku_group: number | null;
  target_value: string;
  original_target_value: string;
  override_value: string | null;
  base_value: string | null;
  effective_target: string;
  status: AllocationStatus;
  is_modified: boolean;
  modification_reason: string;
  source: string;
}

// ── plan aggregate ────────────────────────────────────────────────────────────
export type PlanStatus = 'draft' | 'in_review' | 'published' | 'locked' | 'closed';
export type RunKind = 'baseline' | 'top_down' | 'spatial' | 'product' | 'realign';
export type RunStatus = 'pending' | 'running' | 'staged' | 'committed' | 'discarded' | 'failed';
export type ReviewStatus = 'pending' | 'accepted' | 'adjusted' | 'escalated' | 'force_closed';
export type WeightSource = 'contribution' | 'attribute' | 'external_metric' | 'equal';

export interface WeightComponent {
  source: WeightSource;
  key?: string;
  weight?: number;
}

export interface AllocationRecipe {
  id: number;
  name: string;
  code: string;
  channel: number | null;
  kpi: number | null;
  weight_components: WeightComponent[];
  base_window: { basis?: string };
  growth: { default_pct?: number; per_level_pct?: Record<string, Record<string, number>> };
  constraints: { min_growth_pct?: number; max_growth_pct?: number; floor_value?: number; no_negative?: boolean };
  rounding: { unit?: number };
  version: number;
  is_current: boolean;
  is_active: boolean;
}

export interface RecipePayload {
  name: string;
  code: string;
  channel?: number | null;
  kpi?: number | null;
  weight_components: WeightComponent[];
  base_window: Record<string, unknown>;
  growth: Record<string, unknown>;
  constraints: Record<string, unknown>;
  rounding: Record<string, unknown>;
}

export interface PlanKpi {
  id: number;
  kpi: number;
  kpi_code: string;
  kpi_name: string;
  recipe: number | null;
  recipe_code: string | null;
  baseline_spec: Record<string, unknown>;
  product_split: Record<string, unknown>;
  top_value: string | null;
  derived_top_value: string | null;
}

export interface PlanProgress {
  runs: { staged: number; committed: number };
  committed_stages: RunKind[];
  review: { total: number; open: number };
}

export interface TargetPlan {
  id: number;
  name: string;
  code: string;
  period: number;
  period_code: string;
  period_type: PeriodType;
  root_geography: number;
  root_geography_name: string;
  root_geography_code: string;
  channel: number | null;
  planning_grain: string;
  review_levels: string[];
  product_scope: string[];
  settings: Record<string, unknown>;
  status: PlanStatus;
  owner: number | null;
  kpis: PlanKpi[];
  progress: PlanProgress;
  created_at: string;
}

export interface PlanKpiSpec {
  kpi_id: number;
  recipe_id?: number | null;
  baseline_spec?: Record<string, unknown>;
  product_split?: Record<string, unknown>;
  top_value?: string | null;
}

export interface PlanCreatePayload {
  name: string;
  code: string;
  period_id: number;
  root_geography_id: number;
  channel_id?: number | null;
  planning_grain?: string;
  review_levels?: string[];
  product_scope?: string[];
  settings?: Record<string, unknown>;
  kpis: PlanKpiSpec[];
}

export interface PlanRun {
  id: number;
  plan: number;
  plan_code: string;
  kind: RunKind;
  status: RunStatus;
  scope_node: number | null;
  scope_node_code: string | null;
  config_snapshot: Record<string, unknown>;
  stats: Record<string, unknown>;
  job: number | null;
  committed_by: number | null;
  committed_at: string | null;
  created_at: string;
}

export interface RunPreview {
  run_id: number;
  kind: RunKind;
  staged_rows: number;
  staged_total: string;
  new: number;
  changed: number;
  unchanged: number;
  override_collisions: { geography_node: string; kpi: string; override: string; staged: string }[];
  override_collision_count: number;
  top_deltas: { geography_node: string; kpi: string; from: string; to: string; delta: string }[];
}

export interface ExplainRow {
  kpi: string;
  period: string;
  sku_group: string | null;
  value: string;
  base_value: string | null;
  explain: Record<string, unknown>;
}

/** Explain resolved plan-side: the latest committed run carrying rows for the node. */
export interface PlanExplain {
  run_id: number | null;
  kind: string | null;
  rows: ExplainRow[];
}

/** One entry of a target cell's revision timeline — who changed what, when and why. */
export interface TargetRevisionEntry {
  id: number;
  allocation: number;
  old_value: string;
  new_value: string;
  delta: string;
  delta_pct: string;
  reason: string;
  source: 'manual' | 'rebalance';
  band: 'auto' | 'escalate';
  status: 'approved' | 'pending' | 'rejected';
  requested_by: number | null;
  requested_by_name: string | null;
  approved_by: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  effective_date: string | null;
  created_at: string;
}

/** What a proposed target change would do, without applying it. */
export interface PreflightResult {
  outcome: 'auto' | 'escalate' | 'blocked';
  delta_pct: string | null;
  policy_code: string | null;
  requires_reason: boolean;
  message?: string;
}

export interface ReviewTask {
  id: number;
  plan: number;
  plan_code: string;
  node: number;
  node_name: string;
  node_code: string;
  node_level: string;
  owner_node: number | null;
  owner_name: string | null;
  status: ReviewStatus;
  submitted_by: number | null;
  submitted_at: string | null;
  notes: string;
}

/** Who is accountable for a grid row today — the territory's direct owner, or
 *  (inherited) the nearest ancestor's owner. Resolved through assignments. */
export interface GridOwner {
  entity_id: number;
  name: string;
  code: string;
  type: string;
  inherited: boolean;
}

export interface GridRow {
  geography_node_id: number;
  name: string;
  code: string;
  level: string;
  children_count: number;
  allocation_id: number | null;
  target: string | null;
  original: string | null;
  override: string | null;
  base: string | null;
  growth_pct: string | null;
  share_pct: string | null;
  bottom_up: string | null;
  gap: string | null;
  status: AllocationStatus | null;
  is_modified: boolean;
  review_status: ReviewStatus | null;
  owner: GridOwner | null;
}

export interface GridResponse {
  plan: number;
  kpi: string;
  period: string;
  parent: GridRow;
  rows: GridRow[];
  page: number;
  page_size: number;
  total: number;
}

export interface GapBoard {
  plan: string;
  status: PlanStatus;
  tasks_total: number;
  tasks_open: number;
  by_level: Record<string, Record<ReviewStatus, number>>;
  kpis: { kpi: string; top_down: string; bottom_up: string; gap: string }[];
  top_movers: { geography_node: string; kpi: string; top_down: string; current: string; delta: string }[];
}

export interface CostPreview {
  plan: string;
  scenarios: Record<string, string>;
  per_scheme: { scheme: string; entities: number; scenarios: Record<string, string> }[];
  budget: string | null;
  over_budget_at_100: boolean;
}
