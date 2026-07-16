import type {
  BooleanConfig, BooleanOperator, CompositeConfig, ExternalConfig, GrowthConfig, MeasureConfig, RatioConfig,
} from '../../types/kpi';
import type { DescribableKpi } from './describeKpi';

/**
 * A compact, read-only formula notation for a KPI, derived from its config — e.g.
 *   SUM(NSV)                                   (value)
 *   SUM(NSV) ÷ COUNT(DISTINCT bills)           (ratio / drop size)
 *   COUNT(DISTINCT outlets WHERE NSV > 0)      (effective coverage)
 *   (SUM(NSV) − SUM(NSV)[LY]) ÷ SUM(NSV)[LY] × 100   (growth)
 * Read-only: this just visualises the math the guided builder produced; it is not parsed back.
 */

// Short, friendly tokens for the raw transaction columns.
const FIELD: Record<string, string> = {
  net_amount: 'NSV', gross_amount: 'GSV', discount_amount: 'Disc', tax_amount: 'Tax',
  quantity: 'Qty', base_quantity: 'Vol', outlet_code: 'outlets', bill_ref: 'bills', sku_code: 'SKUs',
};
const fld = (f?: string) => (f ? FIELD[f] ?? f : '?');

const OP: Record<BooleanOperator, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=' };

const BASIS: Record<string, string> = {
  last_year_same_period: 'LY', previous_period: 'prev', previous_month: 'prev-mo', custom_month_offset: 'offset',
};

function measureTerm(m?: MeasureConfig | Record<string, never>): string {
  const mc = m as MeasureConfig | undefined;
  if (!mc || !mc.aggregation) return '?';
  if (mc.aggregation === 'count') return 'COUNT()';
  if (mc.aggregation === 'weighted_distinct') {
    return `WEIGHTED(${fld(mc.group_field ?? mc.measure_field)} by ${fld(mc.weight_field ?? 'net_amount')})`;
  }
  if (mc.aggregation === 'count_distinct') {
    if (mc.having) return `COUNT(DISTINCT ${fld(mc.measure_field)} WHERE ${fld(mc.having.field)} ${OP[mc.having.operator]} ${mc.having.value})`;
    return `COUNT(DISTINCT ${fld(mc.measure_field)})`;
  }
  return `SUM(${fld(mc.measure_field)})`;
}

/** Channel / product scope as a compact suffix, so Focus Value reads differently from Core Value. */
function scopeTag(k: DescribableKpi): string {
  const parts: string[] = [];
  if (k.channel_filter?.length) parts.push(k.channel_filter.join('/'));
  const sku = k.sku_filter;
  if (sku && 'type' in sku) {
    if (sku.type === 'group' && sku.group_code) parts.push(sku.group_code);
    if (sku.type === 'explicit' && sku.sku_codes?.length) parts.push(`${sku.sku_codes.length} SKUs`);
  }
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

export function kpiFormula(k: DescribableKpi): string {
  let core: string;
  switch (k.kpi_type) {
    case 'value':
    case 'count':
    case 'count_distinct':
      core = measureTerm(k.measure_config);
      break;
    case 'ratio': {
      const r = k.ratio_config as RatioConfig | undefined;
      core = `${measureTerm(r?.numerator)} ÷ ${measureTerm(r?.denominator)}`;
      break;
    }
    case 'growth': {
      const g = k.growth_config as GrowthConfig | undefined;
      const x = measureTerm(k.measure_config);
      const base = `${x}[${BASIS[g?.basis ?? ''] ?? 'prev'}]`;
      if (g?.output === 'growth_absolute') core = `${x} − ${base}`;
      else if (g?.output === 'index') core = `${x} ÷ ${base} × 100`;
      else core = `(${x} − ${base}) ÷ ${base} × 100`;
      break;
    }
    case 'boolean': {
      const b = k.boolean_config as BooleanConfig | undefined;
      core = `${measureTerm(k.measure_config)} ${OP[b?.operator ?? 'gte']} ${b?.threshold ?? 0}`;
      break;
    }
    case 'composite': {
      const c = k.composite_config as CompositeConfig | undefined;
      core = c?.expression || '—';
      break;
    }
    case 'external': {
      const x = k.external_config as ExternalConfig | undefined;
      const agg = (x?.aggregation ?? 'default').toUpperCase();
      core = x?.metric_code ? `${agg}(feed:${x.metric_code})` : 'feed:?';
      if (x?.target_source === 'fixed') core += ` vs ${x.fixed_target ?? 100}`;
      break;
    }
    default:
      core = '—';
  }
  return core + scopeTag(k);
}
