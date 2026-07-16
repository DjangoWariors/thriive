import type { KPITransaction } from './kpi';

/** Money & percentage values arrive as strings (Decimal) — format via utils/format.ts. */

export interface AchievementListItem {
  id: number;
  target_period: number;
  kpi: number;
  kpi_code: string;
  kpi_name: string;
  entity: number;
  entity_name: string;
  entity_code: string;
  channel_code: string | null;
  target_value: string;
  achieved_value: string;
  achievement_pct: string;
  projected_pct: string;
  gap_to_target: string;
  growth_pct: string | null;
  is_provisional: boolean;
}

export interface AchievementDetail extends AchievementListItem {
  period_name: string;
  kpi_unit: string;
  gross_value: string;
  returns_value: string;
  daily_run_rate: string;
  projected_value: string;
  required_run_rate: string;
  working_days_elapsed: number;
  working_days_total: number;
  ly_value: string | null;
  computed_at: string | null;
  computation_id: number | null;
}

export interface KpiCard {
  id: number;
  kpi_code: string;
  kpi_name: string;
  unit: string;
  weight_pct: string | null;
  target: string;
  achieved: string;
  pct: string;
  projected_pct: string;
  required_run_rate: string;
  gap: string;
  growth_pct: string | null;
  multiplier: string | null;
  is_provisional: boolean;
}

export interface RankRow {
  rank: number;
  entity_id: number;
  entity_name: string;
  entity_code: string;
  entity_type: string | null;
  channel: string | null;
  achievement_pct: string;
  projected_pct: string;
  payout: string | null;
}

export interface TrendPoint {
  label: string;
  target: string;
  achieved: string;
  pct: string;
}

export interface ChannelMixSlice {
  channel: string;
  pct: string;
}

export interface DashboardAlert {
  id: number;
  entity_name: string;
  rule_code: string;
  severity: 'info' | 'warning' | 'critical';
  metric: string;
  metric_value: string;
  message: string;
  kpi_code: string | null;
}

export interface DashboardSummary {
  overall_achievement_pct: string;
  projected_pct: string;
  primary_target: string;
  primary_achieved: string;
  primary_kpi_name: string | null;
  estimated_payout: string | null;
  payout_kind: 'estimate' | 'final' | null;
  active_entities: number;
  open_alerts: number;
}

export interface DashboardData {
  entity: { id: number; name: string; code: string; type: string | null } | null;
  summary: DashboardSummary;
  kpi_cards: KpiCard[];
  child_ranking: RankRow[] | null;
  trend: TrendPoint[];
  channel_mix: ChannelMixSlice[];
  alerts: DashboardAlert[];
  modules: { incentives: boolean; exceptions: boolean };
}

export interface DrilldownResponse {
  breakdown: {
    achievement: AchievementDetail;
    gross_value: string;
    returns_value: string;
    net_value: string;
  };
  count: number;
  next: string | null;
  previous: string | null;
  results: KPITransaction[];
}

export interface Alert {
  id: number;
  rule: number;
  rule_code: string;
  metric: string;
  entity: number;
  entity_name: string;
  target_period: number;
  kpi: number | null;
  kpi_code: string | null;
  metric_value: string;
  severity: 'info' | 'warning' | 'critical';
  status: 'open' | 'acknowledged' | 'resolved';
  message: string;
  computed_at: string | null;
}

export type AlertMetric =
  | 'achievement_pct'
  | 'projected_pct'
  | 'gap_to_target'
  | 'required_run_rate'
  | 'no_sale_days'
  | 'growth_pct';

export interface AlertRule {
  id: number;
  name: string;
  code: string;
  metric: AlertMetric;
  comparator: 'lt' | 'lte' | 'gt' | 'gte' | 'eq';
  threshold: string;
  scope_entity_types: string[];
  scope_channels: string[];
  kpi: number | null;
  severity: 'info' | 'warning' | 'critical';
  recipient_role: string;
  message_template: string;
  is_enabled: boolean;
  version: number;
  is_current: boolean;
}

export interface AchievementListParams {
  period?: number;
  kpi?: number;
  entity?: number;
  channel?: string;
  entity_type?: string;
  page?: number;
}

// ── territory grid (plan tracking) ────────────────────────────────────────────

export interface TerritoryGridRow {
  node_id: number;
  name: string;
  code: string;
  level: string;
  children_count: number;
  target: string | null;
  actual: string | null;
  achievement_pct: string | null;
  gap: string | null;
  run_rate_needed: string | null;
}

export interface TerritoryGrid {
  parent: number | null;
  rows: TerritoryGridRow[];
  page: number;
  page_size: number;
  total: number;
}

export interface TerritoryGridParams {
  kpi: number;
  period: number;
  parent?: number;
  channel?: string;
  channel_id?: number;
  sku_group?: number;
  page?: number;
  page_size?: number;
}
