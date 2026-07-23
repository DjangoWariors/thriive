export type KpiType =
  | 'value'
  | 'count'
  | 'count_distinct'
  | 'ratio'
  | 'growth'
  | 'composite'
  | 'boolean'
  | 'external';

export type Aggregation = 'sum' | 'count' | 'count_distinct' | 'weighted_distinct';
export type NetLogic = 'sales_minus_returns' | 'gross_only' | 'returns_only' | 'all';
export type TransactionLevel = 'primary' | 'secondary' | 'tertiary';
export type GrowthBasis =
  | 'last_year_same_period'
  | 'previous_period'
  | 'previous_month'
  | 'custom_month_offset';
export type GrowthOutput = 'growth_pct' | 'growth_absolute' | 'index';
export type BooleanOperator = 'gte' | 'gt' | 'lte' | 'lt' | 'eq';
export type SkuFilterType = 'all' | 'group' | 'explicit';

export interface MeasureHaving {
  field: string;
  operator: BooleanOperator;
  value: number | string;
}

export interface MeasureConfig {
  measure_field: string;
  aggregation: Aggregation;
  net_logic: NetLogic;
  transaction_level?: '' | TransactionLevel;
  source_filter?: string[];
  /** count_distinct only: keep groups whose net (sales − returns) of `field` clears the threshold (e.g. EC). */
  having?: MeasureHaving;
  /** weighted_distinct only: the thing being grouped (e.g. outlet_code). Mirrors measure_field. */
  group_field?: string;
  /** weighted_distinct only: the field summed as each group's weight (e.g. net_amount). */
  weight_field?: string;
  /** weighted_distinct only: 'filtered' = weight uses the KPI's product scope; 'all' = the group's total throughput. */
  weight_scope?: 'filtered' | 'all';
}

export interface RatioConfig {
  numerator: MeasureConfig;
  denominator: MeasureConfig;
}

export interface GrowthConfig {
  basis: GrowthBasis;
  output: GrowthOutput;
  offset?: number;
}

export interface CompositeConfig {
  expression: string;
  components: { kpi_code: string }[];
}

export interface BooleanConfig {
  operator: BooleanOperator;
  threshold: number | string;
}

export interface SkuFilter {
  type: SkuFilterType;
  group_code?: string;
  sku_codes?: string[];
}

export type ExternalAggregation = 'sum' | 'avg' | 'latest' | 'max';
export type MetricGranularity = 'entity' | 'geography_node';
export type MetricPeriodGrain = 'daily' | 'monthly';

export interface ExternalConfig {
  metric_code: string;
  /** Omit to use the metric's default aggregation. */
  aggregation?: ExternalAggregation;
  /** 'fixed' = score KPI: achievement % reads as the raw score against fixed_target. */
  target_source: 'allocation' | 'fixed';
  fixed_target?: number | string;
}

/** Catalog entry for a non-transaction fact stream (SFA calls, agency scores, TLSD…). */
export interface ExternalMetric {
  id: number;
  code: string;
  name: string;
  description: string;
  unit: string;
  decimal_places: number;
  granularity: MetricGranularity;
  period_grain: MetricPeriodGrain;
  default_aggregation: ExternalAggregation;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExternalMetricPayload {
  code: string;
  name: string;
  description?: string;
  unit?: string;
  decimal_places?: number;
  granularity: MetricGranularity;
  period_grain: MetricPeriodGrain;
  default_aggregation: ExternalAggregation;
}

export interface ExternalMetricValue {
  id: number;
  metric: number;
  metric_code: string;
  entity: number | null;
  node_id: number | null;
  measured_on: string;
  value: string;
  source: string;
  external_ref: string;
  created_at: string;
}

export interface MetricValueListParams {
  metric?: string;
  entity?: number;
  node_id?: number;
  date_from?: string;
  date_to?: string;
  page?: number;
}

export interface IntegrationBatch {
  id: number;
  batch_kind: 'transactions' | 'metric_values';
  source: string;
  client_batch_ref: string;
  status: 'accepted' | 'partial' | 'rejected';
  received_count: number;
  accepted_count: number;
  rejected_count: number;
  row_errors: { index: number; external_ref: string; errors: string[]; row: Record<string, unknown> }[];
  pushed_by: number | null;
  pushed_by_display: string;
  created_at: string;
}

export interface IntegrationBatchListParams {
  batch_kind?: 'transactions' | 'metric_values';
  source?: string;
  status?: 'accepted' | 'partial' | 'rejected';
  page?: number;
}

export interface KPIDefinition {
  id: number;
  code: string;
  name: string;
  description: string;
  category: string;
  unit: string;
  decimal_places: number;
  kpi_type: KpiType;
  measure_config: MeasureConfig | Record<string, never>;
  ratio_config: RatioConfig | Record<string, never>;
  growth_config: GrowthConfig | Record<string, never>;
  composite_config: CompositeConfig | Record<string, never>;
  boolean_config: BooleanConfig | Record<string, never>;
  external_config: ExternalConfig | Record<string, never>;
  applicable_entity_types: string[];
  channel_filter: string[];
  sku_filter: SkuFilter | Record<string, never>;
  version: number;
  effective_from: string;
  effective_to: string | null;
  is_current: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KPIDefinitionListItem {
  id: number;
  code: string;
  name: string;
  kpi_type: KpiType;
  category: string;
  unit: string;
  decimal_places: number;
  applicable_entity_types: string[];
  channel_filter: string[];
  version: number;
  is_current: boolean;
  // Per-type config — used to render a compact read-only formula in the list.
  measure_config: MeasureConfig | Record<string, never>;
  ratio_config: RatioConfig | Record<string, never>;
  growth_config: GrowthConfig | Record<string, never>;
  composite_config: CompositeConfig | Record<string, never>;
  boolean_config: BooleanConfig | Record<string, never>;
  external_config: ExternalConfig | Record<string, never>;
  sku_filter: SkuFilter | Record<string, never>;
}

/** Writable config — what create/update/validate/preview accept. */
export interface KPIConfigPayload {
  code: string;
  name: string;
  description?: string;
  category?: string;
  unit?: string;
  decimal_places?: number;
  kpi_type: KpiType;
  measure_config?: MeasureConfig | Record<string, never>;
  ratio_config?: RatioConfig | Record<string, never>;
  growth_config?: GrowthConfig | Record<string, never>;
  composite_config?: CompositeConfig | Record<string, never>;
  boolean_config?: BooleanConfig | Record<string, never>;
  external_config?: ExternalConfig | Record<string, never>;
  applicable_entity_types?: string[];
  channel_filter?: string[];
  sku_filter?: SkuFilter | Record<string, never>;
}

/** A configurable builder starting point, served from the backend. */
export interface KpiTemplate {
  id: number;
  code: string;
  name: string;
  description: string;
  icon: string;
  display_order: number;
  category: string;
  unit: string;
  decimal_places: number;
  kpi_type: KpiType;
  measure_config: MeasureConfig | Record<string, never>;
  ratio_config: RatioConfig | Record<string, never>;
  growth_config: GrowthConfig | Record<string, never>;
  composite_config: CompositeConfig | Record<string, never>;
  boolean_config: BooleanConfig | Record<string, never>;
  external_config: ExternalConfig | Record<string, never>;
  sku_filter: SkuFilter | Record<string, never>;
}

export interface KpiValidateResult {
  valid: boolean;
  errors: string[];
}

export interface KpiPreviewResult {
  entity_id: number;
  period_start: string;
  period_end: string;
  kpi_type: KpiType;
  unit: string;
  result: string;
}

export interface KpiListParams {
  search?: string;
  kpi_type?: KpiType;
  category?: string;
  channel?: string;
  entity_type?: string;
  page?: number;
  page_size?: number;
}

export interface KPITransaction {
  id: number;
  attributed_node_id: number;
  /** "Name (CODE)" of the territory the sale is attributed to; '' when the node is unknown. */
  attributed_node_label: string;
  outlet_code: string;
  bill_ref: string;
  sku_code: string;
  channel_code: string;
  transaction_date: string;
  posted_date: string | null;
  transaction_type: 'sale' | 'return' | 'credit_note';
  transaction_level: TransactionLevel;
  source: string;
  external_ref: string;
  gross_amount: string;
  discount_amount: string;
  tax_amount: string;
  net_amount: string;
  quantity: string;
  uom: string;
  is_active: boolean;
  created_at: string;
}

export interface TransactionListParams {
  attributed_node_id?: number;
  channel_code?: string;
  transaction_level?: TransactionLevel;
  transaction_type?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
}
