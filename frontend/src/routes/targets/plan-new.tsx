import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, CalendarDays, Plus, Trash2 } from 'lucide-react';
import { useCreatePlan, usePeriodTree, usePlanYears, useRecipes } from '../../hooks/useTargets';
import { flattenPeriods } from '../../utils/periods';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { useGeographyTypes } from '../../hooks/useEntities';
import { useSKUGroups } from '../../hooks/useMasterData';
import { GeoNodeCombobox, type GeoSelection } from '../../components/entity/GeoNodeCombobox';
import type { PlanKpiSpec } from '../../types/target';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import { PageHeader } from '../../components/ui/PageHeader';
import { Select } from '../../components/ui/Select';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

/** Baseline presets — the blends real planners actually use. */
const BASELINE_PRESETS: Record<string, { label: string; spec: Record<string, unknown> }> = {
  lysm: { label: 'Last year, same period', spec: { components: [{ basis: 'ly_same_period', weight: 100 }] } },
  blend_60_40: {
    label: '60% LY + 40% last 3 months',
    spec: { components: [{ basis: 'ly_same_period', weight: 60 }, { basis: 'l3m_avg', weight: 40 }] },
  },
  l3m: { label: 'Last 3 months (average)', spec: { components: [{ basis: 'l3m_avg', weight: 100 }] } },
};

interface KpiRow {
  kpi_id: number | null;
  recipe_id: number | null;
  baseline: keyof typeof BASELINE_PRESETS;
  top_value: string;
}

export default function PlanNewPage() {
  const navigate = useNavigate();
  const createPlan = useCreatePlan();
  const { data: years } = usePlanYears();
  // Lookups, not list views — fetch everything so nothing past page 1 is unpickable.
  const { data: kpisResp } = useKpiDefinitions({ page_size: 200 });
  const { data: recipesResp } = useRecipes({ page_size: 200 });
  const { data: geoTypes } = useGeographyTypes();
  const { data: groupsResp } = useSKUGroups({ page_size: 200 });
  const geoTypeCode = geoTypes?.results?.[0]?.code ?? '';
  const geoLevels: string[] = geoTypes?.results?.[0]?.levels ?? [];
  const kpis = kpisResp?.results ?? [];
  const recipes = recipesResp?.results ?? [];
  const groups = groupsResp?.results ?? [];

  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [yearId, setYearId] = useState<number | null>(null);
  const [periodId, setPeriodId] = useState<number | null>(null);
  // Targets are always set monthly — the plan period is one month of the chosen year.
  const { data: yearTree } = usePeriodTree(yearId);
  const periodOptions = useMemo(() => flattenPeriods(yearTree), [yearTree]);
  const [root, setRoot] = useState<GeoSelection | null>(null);
  const [grain, setGrain] = useState('');
  const [reviewLevels, setReviewLevels] = useState<string[]>([]);
  const [productScope, setProductScope] = useState<string[]>([]);
  const [budget, setBudget] = useState('');
  const [rows, setRows] = useState<KpiRow[]>([
    { kpi_id: null, recipe_id: null, baseline: 'lysm', top_value: '' },
  ]);

  const valid = name && code && periodId && root && rows.some((r) => r.kpi_id);

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  function submit() {
    const kpiSpecs: PlanKpiSpec[] = rows
      .filter((r) => r.kpi_id)
      .map((r) => ({
        kpi_id: r.kpi_id!,
        recipe_id: r.recipe_id,
        baseline_spec: BASELINE_PRESETS[r.baseline].spec,
        top_value: r.top_value || null,
      }));
    createPlan.mutate({
      name, code, period_id: periodId!, root_geography_id: root!.id,
      planning_grain: grain, review_levels: reviewLevels, product_scope: productScope,
      settings: budget ? { payout_budget: budget } : {},
      kpis: kpiSpecs,
    }, {
      onSuccess: (plan) => { notify.success('Plan created'); navigate(`/targets/${plan.id}`); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not create the plan')),
    });
  }

  // A plan hangs off a plan year — without one the whole form is a dead end.
  if (years && (years.results ?? []).length === 0) {
    return (
      <div className="p-6">
        <PageHeader
          className="mb-5" title="New target plan"
          description="One planning exercise: a period, a territory, the KPIs and how each one splits."
          actions={<Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/targets')}>Cancel</Button>}
        />
        <Card className="max-w-3xl">
          <EmptyState icon={CalendarDays} title="Generate a plan year first"
                      description="A plan is created against a month of a plan year. None exists yet — generate one in the Planning calendar, then come back."
                      actionLabel="Open the Planning calendar" onAction={() => navigate('/targets/periods')} />
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6">
      <PageHeader
        className="mb-5" title="New target plan"
        description="One planning exercise: a period, a territory, the KPIs and how each one splits."
        actions={<Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/targets')}>Cancel</Button>}
      />

      <div className="max-w-3xl space-y-5">
        <Card>
          <h3 className="mb-1 text-sm font-semibold text-gray-800">Basics</h3>
          <p className="mb-3 text-xs text-gray-500">
            Targets are set monthly — pick the plan year, then the month this plan covers.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Plan name" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Jun 2026 GT Plan" />
            <Input label="Code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())}
                   placeholder="PLAN-JUN26-GT" />
            <Select label="Plan year" value={String(yearId ?? '')}
                    onChange={(e) => { setYearId(Number(e.target.value) || null); setPeriodId(null); }}
                    options={[{ value: '', label: 'Choose a plan year…' },
                      ...(years?.results ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
            <Select label="Plan month" value={String(periodId ?? '')}
                    onChange={(e) => setPeriodId(Number(e.target.value) || null)}
                    disabled={!yearId}
                    options={[{ value: '', label: yearId ? 'Choose a month…' : 'Pick the year first…' },
                      ...periodOptions]} />
            <GeoNodeCombobox typeCode={geoTypeCode} value={root} onChange={setRoot} label="Top territory" />
            <Select label="Plan down to (grain)" value={grain} onChange={(e) => setGrain(e.target.value)}
                    options={[{ value: '', label: 'Every level (to leaves)' },
                      ...geoLevels.map((l) => ({ value: l, label: l }))]} />
            <Input label="Payout budget (optional publish gate)" type="number" value={budget}
                   onChange={(e) => setBudget(e.target.value)} placeholder="e.g. 25000000" />
          </div>
        </Card>

        <Card>
          <h3 className="mb-1 text-sm font-semibold text-gray-800">KPIs</h3>
          <p className="mb-3 text-xs text-gray-500">Each KPI carries its own split recipe and baseline.</p>
          <div className="space-y-3">
            {rows.map((row, i) => (
              <div key={i} className="grid items-end gap-3 rounded-lg border border-gray-200 p-3 md:grid-cols-2 lg:grid-cols-3">
                <Select label="KPI" value={String(row.kpi_id ?? '')}
                        onChange={(e) => update(i, { kpi_id: Number(e.target.value) || null })}
                        options={[{ value: '', label: 'Choose…' },
                          ...kpis.map((k) => ({ value: String(k.id), label: k.name }))]} />
                <Select label="Split recipe" value={String(row.recipe_id ?? '')}
                        onChange={(e) => update(i, { recipe_id: Number(e.target.value) || null })}
                        options={[{ value: '', label: 'Choose…' },
                          ...recipes.map((r) => ({ value: String(r.id), label: r.name }))]} />
                <Select label="Baseline" value={row.baseline}
                        onChange={(e) => update(i, { baseline: e.target.value as KpiRow['baseline'] })}
                        options={Object.entries(BASELINE_PRESETS).map(([v, p]) => ({ value: v, label: p.label }))} />
                <Input label="Top number (optional now)" type="number" value={row.top_value}
                       onChange={(e) => update(i, { top_value: e.target.value })} placeholder="From the AOP letter" />
                <div className="flex justify-end">
                  {rows.length > 1 && (
                    <Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4" />}
                            onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Remove KPI">
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
          <Button variant="outline" size="sm" className="mt-3" icon={<Plus className="h-4 w-4" />}
                  onClick={() => setRows([...rows, { kpi_id: null, recipe_id: null, baseline: 'lysm', top_value: '' }])}>
            Add KPI
          </Button>
        </Card>

        <Card>
          <h3 className="mb-1 text-sm font-semibold text-gray-800">Field review</h3>
          <p className="mb-3 text-xs text-gray-500">
            Owners at these levels each get a review task when the plan goes for review.
          </p>
          <div className="flex flex-wrap gap-2">
            {geoLevels.map((level) => (
              <ToggleChip key={level} label={level} active={reviewLevels.includes(level)}
                          onClick={() => toggle(reviewLevels, level, setReviewLevels)} />
            ))}
          </div>
        </Card>

        <Card>
          <h3 className="mb-1 text-sm font-semibold text-gray-800">Product scope (brand split)</h3>
          <p className="mb-3 text-xs text-gray-500">
            SKU groups the product-split stage divides each territory's month into. Leave empty to skip.
          </p>
          <div className="flex flex-wrap gap-2">
            {groups.map((g) => (
              <ToggleChip key={g.code} label={g.name} active={productScope.includes(g.code)}
                          onClick={() => toggle(productScope, g.code, setProductScope)} />
            ))}
            {groups.length === 0 && <p className="text-xs text-gray-400">No SKU groups yet — create them under Master data.</p>}
          </div>
        </Card>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => navigate('/targets')}>Cancel</Button>
          <Button loading={createPlan.isPending} disabled={!valid} onClick={submit}>Create plan</Button>
        </div>
      </div>
    </div>
  );

  function update(i: number, patch: Partial<KpiRow>) {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
}

function ToggleChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={`rounded-full border px-3 py-1 text-sm transition-colors ${
              active ? 'border-primary bg-primary-50 text-primary' : 'border-gray-300 text-gray-600 hover:border-gray-400'}`}>
      {label}
    </button>
  );
}
