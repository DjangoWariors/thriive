import type {
    BooleanConfig,
    BooleanOperator,
    CompositeConfig,
    ExternalConfig,
    GrowthConfig,
    MeasureConfig,
    RatioConfig,
    SkuFilter,
    KpiType,
} from '../../types/kpi';

/**
 * Shape both the wizard payload (KPIConfigPayload) and a saved KPIDefinition satisfy. Lets the
 * builder, detail drawer, and list share one description. Standard BI phrasing — the worded
 * companion to the symbolic formula in ``kpiFormula``.
 */
export interface DescribableKpi {
    kpi_type: KpiType;
    unit?: string;
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

// Net-logic adjective applied to a summed field.
const NET_ADJ: Record<string, string> = {
    sales_minus_returns: 'net ',
    gross_only: 'gross ',
    returns_only: 'returned ',
    all: '',
};

// Noun for a summed field.
const SUM_NOUN: Record<string, string> = {
    net_amount: 'sales value',
    gross_amount: 'sales value',
    discount_amount: 'discount',
    tax_amount: 'tax',
    quantity: 'quantity',
    base_quantity: 'volume',
};

const DISTINCT_NOUN: Record<string, string> = {
    outlet_code: 'outlets',
    bill_ref: 'bills',
    sku_code: 'SKUs',
};

const HAVING_NOUN: Record<string, string> = {
    net_amount: 'net sales',
    gross_amount: 'gross sales',
    quantity: 'quantity',
};

const OP_SYMBOL: Record<BooleanOperator, string> = {
    gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=',
};

const STAGE: Record<string, string> = {
    primary: ', primary stage',
    secondary: ', secondary stage',
    tertiary: ', tertiary stage',
};

const WEIGHT_NOUN: Record<string, string> = {
    net_amount: 'net sales value',
    gross_amount: 'gross sales value',
    base_quantity: 'volume',
    quantity: 'quantity',
};

const BASIS: Record<string, string> = {
    last_year_same_period: 'same period last year',
    previous_period: 'previous period',
    previous_month: 'previous month',
    custom_month_offset: 'a prior period',
};

const OUTPUT: Record<string, string> = {
    growth_pct: 'growth %',
    growth_absolute: 'absolute change',
    index: 'index (100 = no change)',
};

const EXTERNAL_AGG: Record<string, string> = {
    sum: 'sum',
    avg: 'average',
    latest: 'latest value',
    max: 'maximum',
};

function suffix(m: MeasureConfig): string {
    const stage = STAGE[m.transaction_level ?? ''] ?? '';
    const source = m.source_filter?.length ? `, source: ${m.source_filter.join('/')}` : '';
    return `${stage}${source}`;
}

/** Full aggregate phrase in BI terms, e.g. "sum of net sales value, secondary stage". */
function aggregated(m: MeasureConfig): string {
    const s = suffix(m);
    if (m.aggregation === 'weighted_distinct') {
        const noun = DISTINCT_NOUN[m.group_field ?? m.measure_field] ?? 'records';
        const weight = WEIGHT_NOUN[m.weight_field ?? 'net_amount'] ?? 'net sales value';
        const scope = m.weight_scope === 'all' ? ' (total throughput)' : '';
        return `weighted distinct count of ${noun} by ${weight}${scope}${s}`;
    }
    if (m.aggregation === 'count') {
        return `count of transactions${s}`;
    }
    if (m.aggregation === 'count_distinct') {
        const noun = DISTINCT_NOUN[m.measure_field] ?? m.measure_field ?? 'records';
        const having = m.having
            ? ` where ${HAVING_NOUN[m.having.field] ?? m.having.field} ${OP_SYMBOL[m.having.operator]} ${m.having.value}`
            : '';
        return `distinct count of ${noun}${having}${s}`;
    }
    const noun = SUM_NOUN[m.measure_field] ?? m.measure_field ?? 'value';
    return `sum of ${NET_ADJ[m.net_logic] ?? ''}${noun}${s}`;
}

function isMeasure(v: unknown): v is MeasureConfig {
    return !!v && typeof v === 'object' && 'aggregation' in (v as object);
}

const cap = (str: string) => (str ? str[0].toUpperCase() + str.slice(1) : str);

function scopeSuffix(k: DescribableKpi): string {
    const parts: string[] = [];
    if (k.applicable_entity_types?.length) parts.push(`roles: ${k.applicable_entity_types.join('/')}`);
    if (k.channel_filter?.length) parts.push(`channels: ${k.channel_filter.join('/')}`);
    const sku = k.sku_filter as SkuFilter | undefined;
    if (sku?.type === 'group' && sku.group_code) parts.push(`SKU group: ${sku.group_code}`);
    if (sku?.type === 'explicit' && sku.sku_codes?.length) parts.push(`${sku.sku_codes.length} SKUs`);
    return parts.length ? ` · ${parts.join(' · ')}` : '';
}

/** A standard-BI description of what a KPI measures (worded companion to the formula). */
export function describeKpi(k: DescribableKpi): string {
    const m = isMeasure(k.measure_config) ? k.measure_config : null;
    let core: string;

    switch (k.kpi_type) {
        case 'value':
        case 'count':
        case 'count_distinct':
            core = m ? cap(aggregated(m)) : 'Measure';
            break;
        case 'ratio': {
            const r = k.ratio_config as RatioConfig | undefined;
            core = r?.numerator && r?.denominator
                ? `${cap(aggregated(r.numerator))} ÷ ${aggregated(r.denominator)}`
                : 'Ratio';
            break;
        }
        case 'growth': {
            const g = k.growth_config as GrowthConfig | undefined;
            const base = m ? aggregated(m) : 'measure';
            core = `${cap(base)} vs ${BASIS[g?.basis ?? ''] ?? 'a prior period'}, as ${OUTPUT[g?.output ?? 'growth_pct']}`;
            break;
        }
        case 'composite': {
            const c = k.composite_config as CompositeConfig | undefined;
            core = c?.expression ? `Weighted expression: ${c.expression}` : 'Composite of KPIs';
            break;
        }
        case 'boolean': {
            const b = k.boolean_config as BooleanConfig | undefined;
            const base = m ? aggregated(m) : 'the result';
            core = `1 if ${base} ${OP_SYMBOL[b?.operator ?? 'gte']} ${b?.threshold ?? 0}, else 0`;
            break;
        }
        case 'external': {
            const x = k.external_config as ExternalConfig | undefined;
            const agg = EXTERNAL_AGG[x?.aggregation ?? ''] ?? 'metric-default aggregation';
            const target = x?.target_source === 'fixed'
                ? `, scored against a fixed benchmark of ${x?.fixed_target ?? 100}`
                : '';
            core = x?.metric_code
                ? `${cap(agg)} of external metric ${x.metric_code} (SFA / agency feed)${target}`
                : 'External metric feed';
            break;
        }
        default:
            core = 'Metric';
    }

    return `${core}${scopeSuffix(k)}`;
}
