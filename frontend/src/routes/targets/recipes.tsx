import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useRecipes, useSaveRecipe } from '../../hooks/useTargets';
import type { AllocationRecipe, WeightComponent } from '../../types/target';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { PageHeader } from '../../components/ui/PageHeader';
import { Pagination } from '../../components/ui/Pagination';
import { Select } from '../../components/ui/Select';
import { SimpleTable, type SimpleColumn } from '../../components/ui/SimpleTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import {EXTERNAL_METRICS_ENABLED} from '../../config/features';

const SOURCES = [
  { value: 'contribution', label: 'Historical contribution' },
  { value: 'attribute', label: 'Geography attribute (e.g. outlet_count)' },
  ...(EXTERNAL_METRICS_ENABLED
    ? [
        {
          value: 'external_metric',
          label: 'External metric (e.g. market index)',
        },
      ]
    : []),
  { value: 'equal', label: 'Equal' },
];

export default function RecipesPage() {
  const navigate = useNavigate();
  return (
    <div className="p-6">
      <PageHeader
        className="mb-5" title="Split recipes"
        description="How a territory's monthly number divides among its children. Versioned — every edit keeps history."
        actions={<Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/targets')}>Back to plans</Button>}
      />
      <RecipesTab />
    </div>
  );
}

// ---- recipes -------------------------------------------------------------------
function RecipesTab() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useRecipes({ page });
  const [editing, setEditing] = useState<AllocationRecipe | null | 'new'>(null);
  const recipes = data?.results ?? [];

  const columns: SimpleColumn<AllocationRecipe>[] = [
    { header: 'Recipe', render: (r) => <span className="font-medium text-gray-900">{r.name}</span> },
    {
      header: 'Blend',
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          {r.weight_components.map((c, i) => (
            <Badge key={i} variant="default">
              {c.source === 'equal' ? 'equal' : `${c.weight ?? 0}% ${c.key ?? c.source}`}
            </Badge>
          ))}
        </span>
      ),
    },
    { header: 'Growth', render: (r) => r.growth?.default_pct != null ? `+${r.growth.default_pct}%` : '—' },
    {
      header: 'Constraints',
      render: (r) => r.constraints?.max_growth_pct != null || r.constraints?.min_growth_pct != null
        ? `${r.constraints.min_growth_pct ?? '−∞'}% … +${r.constraints.max_growth_pct ?? '∞'}%` : '—',
    },
    { header: 'Version', align: 'center', render: (r) => `v${r.version}` },
    {
      header: '', align: 'right',
      render: (r) => <Button variant="ghost" size="sm" onClick={() => setEditing(r)}>Edit</Button>,
    },
  ];

  return (
    <Card padding="none">
      <div className="flex items-center justify-between px-4 py-3">
        <p className="text-sm text-gray-500">A recipe is a blend: e.g. 70% contribution + 30% outlet count, capped at +40% growth.</p>
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing('new')}>New recipe</Button>
      </div>
      {isLoading ? <div className="p-4"><TableSkeleton /></div>
        : recipes.length === 0
          ? <EmptyState icon={Plus} title="No recipes yet" description="Create the first split recipe to run a plan." actionLabel="New recipe" onAction={() => setEditing('new')} />
          : <>
              <SimpleTable columns={columns} rows={recipes} rowKey={(r) => r.id} />
              <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage} />
            </>}
      {editing !== null && (
        <RecipeModal recipe={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
    </Card>
  );
}

function RecipeModal({ recipe, onClose }: { recipe: AllocationRecipe | null; onClose: () => void }) {
  const save = useSaveRecipe();
  const [name, setName] = useState(recipe?.name ?? '');
  const [code, setCode] = useState(recipe?.code ?? '');
  const [components, setComponents] = useState<WeightComponent[]>(
    recipe?.weight_components?.length ? recipe.weight_components : [{ source: 'contribution', weight: 100 }]);
  const [basis, setBasis] = useState<string>((recipe?.base_window?.basis as string) ?? 'ly_same_period');
  const [growth, setGrowth] = useState(String(recipe?.growth?.default_pct ?? ''));
  const [maxGrowth, setMaxGrowth] = useState(String(recipe?.constraints?.max_growth_pct ?? ''));
  const [minGrowth, setMinGrowth] = useState(String(recipe?.constraints?.min_growth_pct ?? ''));
  const [unit, setUnit] = useState(String(recipe?.rounding?.unit ?? '1'));

  const totalWeight = components.reduce((s, c) => s + (c.source === 'equal' ? 0 : Number(c.weight ?? 0)), 0);

  function patch(i: number, p: Partial<WeightComponent>) {
    setComponents(components.map((c, j) => (j === i ? { ...c, ...p } : c)));
  }

  function submit() {
    save.mutate({
      id: recipe?.id ?? null,
      payload: {
        name, code,
        weight_components: components,
        base_window: { basis },
        growth: growth !== '' ? { default_pct: Number(growth) } : {},
        constraints: {
          ...(minGrowth !== '' ? { min_growth_pct: Number(minGrowth) } : {}),
          ...(maxGrowth !== '' ? { max_growth_pct: Number(maxGrowth) } : {}),
        },
        rounding: unit !== '' ? { unit: Number(unit) } : {},
      },
    }, {
      onSuccess: () => { notify.success(recipe ? 'Recipe updated (new version)' : 'Recipe created'); onClose(); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not save the recipe')),
    });
  }

  return (
    <Modal
      open onClose={onClose} size="3xl"
      title={recipe ? `Edit ${recipe.code} (v${recipe.version})` : 'New split recipe'}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} disabled={!name || !code} onClick={submit}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="GT value split" />
          <Input label="Code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())}
                 placeholder="GT_VALUE" disabled={recipe !== null} />
        </div>

        <div>
          <p className="mb-1 text-sm font-medium text-gray-700">Weight blend</p>
          <div className="space-y-2">
            {components.map((c, i) => (
              <div key={i} className="flex flex-wrap items-end gap-2">
                <div className="min-w-40 flex-1">
                  <Select label={i === 0 ? 'Source' : undefined} value={c.source}
                          onChange={(e) => patch(i, { source: e.target.value as WeightComponent['source'] })}
                          options={SOURCES} />
                </div>
                {(c.source === 'attribute' || c.source === 'external_metric') && (
                  <div className="min-w-40 flex-1">
                    <Input label={i === 0 ? 'Key' : undefined} value={c.key ?? ''}
                           onChange={(e) => patch(i, { key: e.target.value })}
                           placeholder={c.source === 'attribute' ? 'outlet_count' : 'MARKET_INDEX'} />
                  </div>
                )}
                {c.source !== 'equal' && (
                  <div className="w-24">
                    <Input label={i === 0 ? 'Weight %' : undefined} type="number" value={String(c.weight ?? '')}
                           onChange={(e) => patch(i, { weight: Number(e.target.value) })} />
                  </div>
                )}
                <Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4" />} aria-label="Remove component"
                        disabled={components.length === 1}
                        onClick={() => setComponents(components.filter((_, j) => j !== i))} />
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center justify-between">
            <Button variant="outline" size="sm" icon={<Plus className="h-4 w-4" />}
                    onClick={() => setComponents([...components, { source: 'attribute', key: '', weight: 0 }])}>
              Add component
            </Button>
            {totalWeight !== 100 && totalWeight > 0 && (
              <p className="text-xs text-amber-600">Weights sum to {totalWeight} — they are normalised, but 100 reads better.</p>
            )}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Select label="History window" value={basis} onChange={(e) => setBasis(e.target.value)}
                  options={[{ value: 'ly_same_period', label: 'Last year, same period' },
                            { value: 'previous_period', label: 'Previous period' },
                            { value: 'l3m_avg', label: 'Last 3 months' },
                            { value: 'l6m_avg', label: 'Last 6 months' }]} />
          <Input label="Default growth %" type="number" value={growth} onChange={(e) => setGrowth(e.target.value)} placeholder="12" />
          <Input label="Growth floor %" type="number" value={minGrowth} onChange={(e) => setMinGrowth(e.target.value)} placeholder="0" />
          <Input label="Growth cap %" type="number" value={maxGrowth} onChange={(e) => setMaxGrowth(e.target.value)} placeholder="40" />
        </div>
        <div className="w-40">
          <Input label="Round to (₹)" type="number" value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="1000" />
        </div>
      </div>
    </Modal>
  );
}

