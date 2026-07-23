import { Select } from '../ui/Select';
import { Input } from '../ui/Input';
import { InfoTooltip } from '../ui/InfoTooltip';
import { Example } from '../ui/WizardChrome';
import type { Aggregation, BooleanOperator, MeasureConfig, NetLogic } from '../../types/kpi';

// Plain-language choices. The `value` sent to the backend never changes — only the words
// the user reads. Everything here is written for a sales/finance user, not an engineer.

const AGGREGATIONS: { value: Aggregation; label: string }[] = [
  { value: 'sum', label: 'Sum of a value (e.g. total sales)' },
  { value: 'count', label: 'Count of transactions' },
  { value: 'count_distinct', label: 'Count of distinct values (e.g. outlets, bills, SKUs)' },
];

const SUM_FIELDS = [
  { value: 'net_amount', label: 'Sales value after returns (NSV)' },
  { value: 'gross_amount', label: 'Sales value before returns (GSV)' },
  { value: 'base_quantity', label: 'Volume (base unit — cases/units/kg comparable)' },
  { value: 'quantity', label: 'Quantity (as entered)' },
];

const DISTINCT_FIELDS = [
  { value: 'outlet_code', label: 'Shops / outlets' },
  { value: 'bill_ref', label: 'Bills / invoices' },
  { value: 'sku_code', label: 'Products (SKUs)' },
];

// What each group is weighted by in a weighted-distribution (numeric distribution) KPI.
const WEIGHT_FIELDS = [
  { value: 'net_amount', label: 'Sales value after returns (NSV)' },
  { value: 'gross_amount', label: 'Sales value before returns (GSV)' },
  { value: 'base_quantity', label: 'Volume (normalised)' },
];

const WEIGHT_SCOPES = [
  { value: 'filtered', label: 'sales of filtered SKUs only' },
  { value: 'all', label: 'total sales (all SKUs)' },
];

// The data sources a transaction can carry (Transaction.source). Restricting a measure
// to one or more makes the KPI trust only that feed (e.g. count only DMS-synced rows).
const SOURCE_OPTIONS = [
  { value: 'dms_sync', label: 'DMS sync' },
  { value: 'sfa_sync', label: 'Field app (SFA)' },
  { value: 'manual_entry', label: 'Manual entry' },
  { value: 'api_push', label: 'API push' },
];

const NET_LOGIC: { value: NetLogic; label: string }[] = [
  { value: 'sales_minus_returns', label: 'Net (sales − returns)' },
  { value: 'gross_only', label: 'Gross (sales only)' },
  { value: 'all', label: 'All (as recorded)' },
];

const LEVELS = [
  { value: '', label: 'Any stage' },
  { value: 'primary', label: 'Primary — Company to Distributor' },
  { value: 'secondary', label: 'Secondary — Distributor to Retailer' },
  { value: 'tertiary', label: 'Tertiary — Retailer to Shopper' },
];

const HAVING_OPS: { value: BooleanOperator; label: string }[] = [
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'eq', label: '=' },
];

const HAVING_FIELDS = [
  { value: 'net_amount', label: 'sales value (net)' },
  { value: 'gross_amount', label: 'sales value (gross)' },
  { value: 'quantity', label: 'quantity' },
];

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="w-full">
      <span className="mb-1 flex items-center gap-1.5 text-sm font-medium text-gray-700">
        {label}
        {help && <InfoTooltip content={help} />}
      </span>
      {children}
    </div>
  );
}

const AGG_EXAMPLE: Record<Aggregation, string> = {
  sum: 'e.g. total secondary NSV for the period.',
  count: 'e.g. number of bills raised.',
  count_distinct: 'e.g. distinct outlets that purchased — Effective Coverage.',
  weighted_distinct: 'e.g. numeric distribution — outlets weighted by sales.',
};

interface Props {
  value: MeasureConfig;
  onChange: (next: MeasureConfig) => void;
  lockAggregation?: boolean;
  title?: string;
}

export function MeasurementBuilder({ value, onChange, lockAggregation = false, title }: Props) {
  const set = (patch: Partial<MeasureConfig>) => onChange({ ...value, ...patch });
  const isDistinct = value.aggregation === 'count_distinct' || value.aggregation === 'weighted_distinct';
  const isWeighted = value.aggregation === 'weighted_distinct';
  // The dropdown only offers sum/count/count_distinct; weighted_distinct is reached via the toggle.
  const aggSelectValue = isWeighted ? 'count_distinct' : value.aggregation;
  const fieldOptions = isDistinct ? DISTINCT_FIELDS : SUM_FIELDS;
  const showField = value.aggregation !== 'count';
  const fieldLabel = isDistinct ? 'Distinct field' : 'Field';
  const isAmountField = value.measure_field === 'net_amount' || value.measure_field === 'gross_amount';
  const isVolumeField = value.measure_field === 'base_quantity' || value.measure_field === 'quantity';

  // The distinct field doubles as group_field for weighted distribution — keep them in sync.
  const onFieldChange = (field: string) =>
    set({ measure_field: field, ...(isWeighted ? { group_field: field } : {}) });

  // Sum and distinct offer disjoint field lists, so the field must move with the aggregation.
  // Carrying it across is silent rather than obvious: React falls back to selecting the first
  // option when the value matches none, so the user reads "Shops / outlets" while the config
  // still says net_amount — and the backend gets "count distinct values of a decimal column".
  const onAggregationChange = (next: Aggregation) => {
    const nowDistinct = next === 'count_distinct';
    if (isDistinct === nowDistinct) return set({ aggregation: next });
    set({
      aggregation: next,
      measure_field: nowDistinct ? 'outlet_code' : 'net_amount',
      // These only mean anything under a distinct count.
      having: undefined,
      group_field: undefined,
      weight_field: undefined,
      weight_scope: undefined,
    });
  };

  const toggleWeighted = (on: boolean) => {
    if (on) {
      set({
        aggregation: 'weighted_distinct',
        group_field: value.measure_field || 'outlet_code',
        weight_field: value.weight_field || 'net_amount',
        weight_scope: value.weight_scope || 'filtered',
        having: undefined,
      });
    } else {
      set({ aggregation: 'count_distinct', group_field: undefined, weight_field: undefined, weight_scope: undefined });
    }
  };

  const toggleSource = (code: string) => {
    const current = value.source_filter ?? [];
    const next = current.includes(code) ? current.filter((c) => c !== code) : [...current, code];
    set({ source_filter: next.length ? next : undefined });
  };

  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
      {title && <p className="text-sm font-semibold text-gray-800">{title}</p>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Field
            label="Aggregation"
            help="Sum gives a money/volume total; count answers 'how many times'; distinct count answers 'how many different ones'. The same data can tell very different stories — ₹10 lakh on one giant bill is not ₹10 lakh across 200 shops."
          >
            <Select
              aria-label="Aggregation"
              value={aggSelectValue}
              disabled={lockAggregation}
              onChange={(e) => onAggregationChange(e.target.value as Aggregation)}
              options={AGGREGATIONS}
            />
          </Field>
          <Example>{AGG_EXAMPLE[value.aggregation]}</Example>
        </div>
        {showField && (
          <div>
            <Field
              label={fieldLabel}
              help={
                isDistinct
                  ? 'The field to count distinct values of — outlets, bills or SKUs.'
                  : 'NSV (net of returns) is the standard measure for incentives and targets — it cannot be inflated by billing then returning stock. GSV is gross, before returns. Volume (base unit) sums across mixed pack sizes; Quantity (as entered) may mix packs and units.'
              }
            >
              <Select
                aria-label={fieldLabel}
                value={value.measure_field}
                onChange={(e) => onFieldChange(e.target.value)}
                options={fieldOptions}
              />
            </Field>
            {!isDistinct && isAmountField && (
              <Example>NSV for net sales value; GSV excludes returns.</Example>
            )}
            {!isDistinct && isVolumeField && (
              <Example>Use <strong>Volume (base unit)</strong> for cross-SKU volume — converts cases/units/kg to a common base.</Example>
            )}
          </div>
        )}
        <Field
          label="Returns handling"
          help="Net subtracts returns from sales (the usual choice for sales value). Gross ignores returns entirely."
        >
          <Select
            aria-label="Returns handling"
            value={value.net_logic}
            onChange={(e) => set({ net_logic: e.target.value as NetLogic })}
            options={NET_LOGIC}
          />
        </Field>
        <Field
          label="Sales stage"
          help="Primary = company → distributor. Secondary = distributor → retailer. Tertiary = retailer → shopper. Pick 'Any stage' to count all."
        >
          <Select
            aria-label="Sales stage"
            value={value.transaction_level ?? ''}
            onChange={(e) => set({ transaction_level: e.target.value as MeasureConfig['transaction_level'] })}
            options={LEVELS}
          />
        </Field>
      </div>

      {isDistinct && (
        <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-3">
          {/* Weighted / numeric distribution — count each one by how much it sells. */}
          <label className="flex cursor-pointer items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={isWeighted}
              onChange={(e) => toggleWeighted(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
            />
            <span>
              <span className="inline-flex items-center gap-1.5">
                Weight by sales (numeric distribution)
                <InfoTooltip content="Numeric (weighted) distribution: each group is weighted by its sales rather than counted flat, so a larger outlet contributes more. Combine with a SKU scope to measure weighted reach of a brand." />
              </span>
              <span className="block text-xs text-gray-400">
                Converts a flat count into numeric distribution / weighted reach.
              </span>
            </span>
          </label>

          {isWeighted ? (
            <div className="flex flex-wrap items-end gap-2 text-sm text-gray-600">
              <span className="pb-2">Weight by</span>
              <div className="w-56">
                <Select
                  aria-label="Weight by field"
                  value={value.weight_field ?? 'net_amount'}
                  onChange={(e) => set({ weight_field: e.target.value })}
                  options={WEIGHT_FIELDS}
                />
              </div>
              <span className="pb-2">over</span>
              <div className="w-72">
                <Select
                  aria-label="Weight scope"
                  value={value.weight_scope ?? 'filtered'}
                  onChange={(e) => set({ weight_scope: e.target.value as 'filtered' | 'all' })}
                  options={WEIGHT_SCOPES}
                />
              </div>
            </div>
          ) : (
            <>
              <label className="flex cursor-pointer items-start gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={!!value.having}
                  onChange={(e) =>
                    set({ having: e.target.checked ? { field: 'net_amount', operator: 'gt', value: 0 } : undefined })
                  }
                  className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                />
                <span>
                  Effective Coverage — count only qualifying groups
                  <span className="block text-xs text-gray-400">
                    Counts a group only when its value clears a threshold (e.g. outlets with net sales {'>'} 0).
                    Excludes outlets that appear on a single bill later fully returned, which would otherwise
                    inflate coverage.
                  </span>
                </span>
              </label>
              {value.having && (
                <div className="mt-1 flex flex-wrap items-end gap-2 text-sm text-gray-600">
                  <span className="pb-2">Qualify when</span>
                  <div className="w-40">
                    <Select
                      aria-label="Qualifying field"
                      value={value.having.field}
                      onChange={(e) => set({ having: { ...value.having!, field: e.target.value } })}
                      options={HAVING_FIELDS}
                    />
                  </div>
                  <div className="w-24">
                    <Select
                      aria-label="Qualifying operator"
                      value={value.having.operator}
                      onChange={(e) => set({ having: { ...value.having!, operator: e.target.value as BooleanOperator } })}
                      options={HAVING_OPS}
                    />
                  </div>
                  <div className="w-28">
                    <Input
                      aria-label="Qualifying threshold"
                      value={String(value.having.value)}
                      onChange={(e) => set({ having: { ...value.having!, value: e.target.value } })}
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Restrict the measure to specific data feeds. Empty = trust every source. */}
      <div className="rounded-lg border border-gray-200 bg-white p-3 hidden">
        <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-gray-700">
          Source filter
          <InfoTooltip content="Restrict this measure to one or more data feeds — e.g. trust only DMS-synced rows and ignore manual entries. Leave all unticked to count every source. The calculator otherwise ignores where a transaction came from." />
        </span>
        <div className="flex flex-wrap gap-1.5">
          {SOURCE_OPTIONS.map((src) => {
            const active = (value.source_filter ?? []).includes(src.value);
            return (
              <button
                key={src.value}
                type="button"
                onClick={() => toggleSource(src.value)}
                className={[
                  'rounded-md border px-2.5 py-1 text-xs',
                  active
                    ? 'border-primary bg-primary text-white'
                    : 'border-gray-200 bg-gray-50 text-gray-600 hover:border-primary',
                ].join(' ')}
              >
                {src.label}
              </button>
            );
          })}
        </div>
        {!value.source_filter?.length && (
          <p className="mt-1.5 text-xs text-gray-400">None selected — all sources included.</p>
        )}
      </div>
    </div>
  );
}

export const EMPTY_MEASURE: MeasureConfig = {
  measure_field: 'net_amount',
  aggregation: 'sum',
  net_logic: 'sales_minus_returns',
  transaction_level: 'secondary',
};
