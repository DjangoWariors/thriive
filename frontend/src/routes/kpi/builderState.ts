import type {
    BooleanOperator, ExternalAggregation, ExternalConfig, GrowthBasis, GrowthOutput, KpiType, MeasureConfig,
} from '../../types/kpi';
import { EMPTY_MEASURE } from '../../components/builders/MeasurementBuilder';

/** Config fields shared by a saved KPIDefinition and a KpiTemplate. */
export interface KpiConfigSource {
    code?: string;
    name?: string;
    description?: string;
    category?: string;
    unit?: string;
    decimal_places?: number;
    kpi_type: KpiType;
    measure_config?: MeasureConfig | Record<string, never>;
    ratio_config?: { numerator?: MeasureConfig; denominator?: MeasureConfig } | Record<string, never>;
    growth_config?: { basis?: GrowthBasis; output?: GrowthOutput; offset?: number } | Record<string, never>;
    composite_config?: { expression?: string } | Record<string, never>;
    boolean_config?: { operator?: BooleanOperator; threshold?: number | string } | Record<string, never>;
    external_config?: ExternalConfig | Record<string, never>;
    applicable_entity_types?: string[];
    channel_filter?: string[];
    sku_filter?: { type?: 'all' | 'group' | 'explicit'; group_code?: string; sku_codes?: string[] } | Record<string, never>;
}

export interface BuilderState {
    code: string;
    name: string;
    description: string;
    category: string;
    unit: string;
    decimal_places: number;
    kpi_type: KpiType;
    measure_config: MeasureConfig;
    ratio_numerator: MeasureConfig;
    ratio_denominator: MeasureConfig;
    basis: GrowthBasis;
    output: GrowthOutput;
    offset: number;
    expression: string;
    operator: BooleanOperator;
    threshold: string;
    metric_code: string;
    /** '' = use the metric's default aggregation. */
    external_aggregation: '' | ExternalAggregation;
    target_source: 'allocation' | 'fixed';
    fixed_target: string;
    applicable_entity_types: string[];
    channel_filter: string[];
    sku_filter_type: 'all' | 'group' | 'explicit';
    sku_group_code: string;
    sku_codes: string;
}

export const INITIAL: BuilderState = {
    code: '', name: '', description: '', category: 'sales', unit: '₹', decimal_places: 2,
    kpi_type: 'value',
    measure_config: { ...EMPTY_MEASURE },
    ratio_numerator: { ...EMPTY_MEASURE },
    ratio_denominator: { ...EMPTY_MEASURE, measure_field: 'bill_ref', aggregation: 'count_distinct', net_logic: 'gross_only' },
    basis: 'last_year_same_period', output: 'growth_pct', offset: 12,
    expression: '', operator: 'gte', threshold: '0',
    metric_code: '', external_aggregation: '', target_source: 'allocation', fixed_target: '100',
    applicable_entity_types: [], channel_filter: [],
    sku_filter_type: 'all', sku_group_code: '', sku_codes: '',
};

/** Map a saved KPI or a template into the flat builder form state. */
export function kpiToBuilderState(src: KpiConfigSource): BuilderState {
    const ratio = (src.ratio_config ?? {}) as { numerator?: MeasureConfig; denominator?: MeasureConfig };
    const growth = (src.growth_config ?? {}) as { basis?: GrowthBasis; output?: GrowthOutput; offset?: number };
    const comp = (src.composite_config ?? {}) as { expression?: string };
    const boolc = (src.boolean_config ?? {}) as { operator?: BooleanOperator; threshold?: number | string };
    const ext = (src.external_config ?? {}) as Partial<ExternalConfig>;
    const sku = (src.sku_filter ?? {}) as { type?: 'all' | 'group' | 'explicit'; group_code?: string; sku_codes?: string[] };
    return {
        code: src.code ?? '',
        name: src.name ?? '',
        description: src.description ?? '',
        category: src.category ?? 'sales',
        unit: src.unit ?? '₹',
        decimal_places: src.decimal_places ?? 2,
        kpi_type: src.kpi_type,
        measure_config: { ...EMPTY_MEASURE, ...(src.measure_config as MeasureConfig) },
        ratio_numerator: { ...EMPTY_MEASURE, ...(ratio.numerator ?? {}) },
        ratio_denominator: { ...INITIAL.ratio_denominator, ...(ratio.denominator ?? {}) },
        basis: growth.basis ?? 'last_year_same_period',
        output: growth.output ?? 'growth_pct',
        offset: growth.offset ?? 12,
        expression: comp.expression ?? '',
        operator: boolc.operator ?? 'gte',
        threshold: String(boolc.threshold ?? '0'),
        metric_code: ext.metric_code ?? '',
        external_aggregation: ext.aggregation ?? '',
        target_source: ext.target_source ?? 'allocation',
        fixed_target: String(ext.fixed_target ?? '100'),
        applicable_entity_types: src.applicable_entity_types ?? [],
        channel_filter: src.channel_filter ?? [],
        sku_filter_type: sku.type ?? 'all',
        sku_group_code: sku.group_code ?? '',
        sku_codes: (sku.sku_codes ?? []).join(', '),
    };
}
