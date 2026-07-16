import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Controller, useFieldArray, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowLeft, ArrowRight, Check, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useKpiBlueprint } from '../../hooks/useKpi';
import { useChannels, useEntityTypes } from '../../hooks/useEntities';
import { useCreateScheme, useScheme, useUpdateScheme } from '../../hooks/useIncentives';
import { incentiveService } from '../../services/incentiveService';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Spinner } from '../../components/ui/Spinner';
import { Tabs } from '../../components/ui/Tabs';
import { Textarea } from '../../components/ui/Textarea';
import { TierBuilder, defaultTiers, tierGridErrors } from '../../components/builders/TierBuilder';
import { cn } from '../../utils/cn';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { SchemePayload } from '../../types/incentive';

// ── schema ──────────────────────────────────────────────────────────────────

const tierSchema = z.object({
  min_achievement_pct: z.string(),
  max_achievement_pct: z.string().nullable(),
  multiplier: z.string(),
});

const kpiRowSchema = z.object({
  kpi: z.number().min(1, 'Choose a KPI'),
  incentive_category: z.enum(['sales', 'execution']),
  weightage: z.string().min(1, 'Required'),
  min_qualifying_pct: z.string(),
  multiplier_cap: z.string(),
  tiers: z.array(tierSchema).min(1, 'Add at least one tier'),
});

const wizardSchema = z
  .object({
    name: z.string().min(1, 'Give the scheme a name'),
    code: z.string().min(1, 'Required').regex(/^[A-Z0-9_]+$/, 'Capital letters, digits and _ only'),
    description: z.string(),
    target_entity_type: z.number().min(1, 'Choose who this scheme pays'),
    channel: z.number().nullable(),
    payout_frequency: z.enum(['monthly', 'annual']),
    vp_basis_pct: z.string().min(1, 'Required'),
    overall_cap_pct: z.string(),
    gates: z.array(z.object({
      kpi: z.number().min(1, 'Choose a KPI'),
      operator: z.enum(['gte', 'gt']),
      threshold_pct: z.string().min(1, 'Set the threshold'),
    })),
    gatekeeper_action: z.enum(['zero_payout', 'cap_at_1x']),
    kpis: z.array(kpiRowSchema).min(1, 'Add at least one KPI'),
  })
  .superRefine((v, ctx) => {
    const sum = v.kpis.reduce((acc, k) => acc + (parseFloat(k.weightage) || 0), 0);
    if (v.kpis.length && Math.abs(sum - 100) > 0.001) {
      ctx.addIssue({
        code: 'custom', path: ['kpis'],
        message: `KPI weightages must total exactly 100% (currently ${sum.toFixed(2)}%)`,
      });
    }
    const seen = new Set<number>();
    v.kpis.forEach((k, i) => {
      if (k.kpi > 0 && seen.has(k.kpi)) {
        ctx.addIssue({ code: 'custom', path: ['kpis', i, 'kpi'], message: 'This KPI is already in the scheme' });
      }
      seen.add(k.kpi);
      tierGridErrors(k.tiers).forEach((err) =>
        ctx.addIssue({ code: 'custom', path: ['kpis', i, 'tiers'], message: err }),
      );
    });
    const gateSeen = new Set<number>();
    v.gates.forEach((g, i) => {
      if (g.kpi > 0 && gateSeen.has(g.kpi)) {
        ctx.addIssue({ code: 'custom', path: ['gates', i, 'kpi'], message: 'This KPI is already a gate' });
      }
      gateSeen.add(g.kpi);
    });
  });

type WizardValues = z.infer<typeof wizardSchema>;

const INITIAL: WizardValues = {
  name: '', code: '', description: '',
  target_entity_type: 0, channel: null,
  payout_frequency: 'monthly',
  vp_basis_pct: '100', overall_cap_pct: '',
  gates: [], gatekeeper_action: 'zero_payout',
  kpis: [{ kpi: 0, incentive_category: 'sales', weightage: '100',
           min_qualifying_pct: '', multiplier_cap: '', tiers: defaultTiers() }],
};

const STEPS = ['Basics', 'KPIs & Weightage', 'Multiplier Slabs', 'Gate Criteria & Caps', 'Review'];

const STEP_FIELDS: (keyof WizardValues)[][] = [
  ['name', 'code', 'target_entity_type', 'vp_basis_pct'],
  ['kpis'],
  ['kpis'],
  ['gates', 'overall_cap_pct'],
  [],
];

function toPayload(v: WizardValues): SchemePayload {
  return {
    name: v.name,
    code: v.code,
    description: v.description,
    target_entity_type: v.target_entity_type,
    channel: v.channel,
    payout_frequency: v.payout_frequency,
    vp_basis_pct: v.vp_basis_pct,
    overall_cap_pct: v.overall_cap_pct || null,
    gates: v.gates.map((g, i) => ({
      kpi: g.kpi, operator: g.operator, threshold_pct: g.threshold_pct, display_order: i,
    })),
    gatekeeper_action: v.gatekeeper_action,
    kpis: v.kpis.map((k, i) => ({
      kpi: k.kpi,
      incentive_category: k.incentive_category,
      weightage: k.weightage,
      min_qualifying_pct: k.min_qualifying_pct || null,
      multiplier_cap: k.multiplier_cap || null,
      display_order: i,
      tiers: k.tiers,
    })),
  };
}

// ── page ────────────────────────────────────────────────────────────────────

export default function SchemeBuilderPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const editId = id ? Number(id) : null;

  const [step, setStep] = useState(0);
  const [tierTab, setTierTab] = useState('0');
  const [saving, setSaving] = useState(false);
  const [serverErrors, setServerErrors] = useState<string[]>([]);

  const { data: typesResp } = useEntityTypes();
  const { data: channelsResp } = useChannels();
  const { data: allKpis } = useKpiBlueprint();
  const { data: existing, isLoading: loadingExisting } = useScheme(editId);
  const createScheme = useCreateScheme();
  const updateScheme = useUpdateScheme();

  const form = useForm<WizardValues>({ resolver: zodResolver(wizardSchema), defaultValues: INITIAL, mode: 'onBlur' });
  const { control, register, watch, setValue, getValues, trigger, reset, formState: { errors } } = form;
  const kpiArray = useFieldArray({ control, name: 'kpis' });

  useEffect(() => {
    if (!existing) return;
    reset({
      name: existing.name,
      code: existing.code,
      description: existing.description,
      target_entity_type: existing.target_entity_type,
      channel: existing.channel,
      payout_frequency: existing.payout_frequency,
      vp_basis_pct: existing.vp_basis_pct,
      overall_cap_pct: existing.overall_cap_pct ?? '',
      gates: existing.gates.map((g) => ({
        kpi: g.kpi, operator: g.operator, threshold_pct: g.threshold_pct,
      })),
      gatekeeper_action: existing.gatekeeper_action,
      kpis: existing.kpis.map((k) => ({
        kpi: k.kpi,
        incentive_category: k.incentive_category,
        weightage: k.weightage,
        min_qualifying_pct: k.min_qualifying_pct ?? '',
        multiplier_cap: k.multiplier_cap ?? '',
        tiers: k.tiers,
      })),
    });
  }, [existing, reset]);

  const entityTypes = (typesResp?.results ?? []).filter((t) => t.incentive_eligible);
  const channels = channelsResp?.results ?? [];
  const selectedTypeCode = entityTypes.find((t) => t.id === watch('target_entity_type'))?.code;
  const kpiOptions = useMemo(() => {
    const list = allKpis ?? [];
    return list.filter(
      (k) =>
        !selectedTypeCode ||
        k.applicable_entity_types.length === 0 ||
        k.applicable_entity_types.includes(selectedTypeCode),
    );
  }, [allKpis, selectedTypeCode]);
  const kpiName = (kpiId: number | null) =>
    (allKpis ?? []).find((k) => k.id === kpiId)?.name ?? '—';

  const kpis = watch('kpis');
  const weightSum = kpis.reduce((acc, k) => acc + (parseFloat(k.weightage) || 0), 0);
  const gateArray = useFieldArray({ control, name: 'gates' });
  const gatesWatch = watch('gates');

  const next = async () => {
    const valid = await trigger(STEP_FIELDS[step]);
    if (!valid) return;
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const save = async () => {
    const valid = await trigger();
    if (!valid) return;
    const payload = toPayload(getValues());
    setSaving(true);
    setServerErrors([]);
    try {
      const result = await incentiveService.validateScheme(payload);
      if (!result.valid) {
        setServerErrors(result.errors);
        return;
      }
      if (editId) {
        await updateScheme.mutateAsync({ id: editId, payload });
        notify.success(`Scheme updated — a new version (v${(existing?.version ?? 1) + 1}) is now current`);
      } else {
        await createScheme.mutateAsync(payload);
        notify.success('Scheme created');
      }
      navigate('/incentives/schemes');
    } catch (e) {
      notify.error(apiErrorMessage(e, 'Sorry, we couldn’t save the scheme'));
    } finally {
      setSaving(false);
    }
  };

  if (editId && loadingExisting) {
    return <div className="flex justify-center py-20"><Spinner size="lg" /></div>;
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-6">
        <button onClick={() => navigate('/incentives/schemes')}
                className="mb-2 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
          <ArrowLeft size={14} /> Back to schemes
        </button>
        <h1 className="text-2xl font-bold text-gray-900">
          {editId ? `Edit Scheme — ${existing?.name ?? ''}` : 'New Incentive Scheme'}
        </h1>
        {editId && (
          <p className="text-sm text-amber-600">
            Saving creates version {(existing?.version ?? 1) + 1}. Payouts already computed against
            v{existing?.version} are not affected.
          </p>
        )}
      </div>

      {/* Stepper */}
      <div className="mb-6 flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => i < step && setStep(i)}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold',
                i < step ? 'bg-success text-white' : i === step ? 'bg-primary text-white' : 'bg-gray-200 text-gray-500',
              )}
            >
              {i < step ? <Check size={14} /> : i + 1}
            </button>
            <span className={cn('text-xs font-medium', i === step ? 'text-primary' : 'text-gray-500')}>
              {label}
            </span>
            {i < STEPS.length - 1 && <div className="h-px w-6 bg-gray-300" />}
          </div>
        ))}
      </div>

      <Card>
        {/* ── Step 1: Basics ── */}
        {step === 0 && (
          <div className="space-y-4">
            <p className="text-sm text-gray-500">
              Name the scheme and choose who it pays. The variable-pay basis is the share of each
              person's monthly variable pay this scheme pays against.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <Input label="Scheme name" placeholder="Field Force Monthly Incentive"
                     error={errors.name?.message} {...register('name')} />
              <Input label="Code" placeholder="FF_MONTHLY" disabled={!!editId}
                     hint={editId ? 'The code cannot change across versions' : 'Capital letters, digits and underscores'}
                     error={errors.code?.message}
                     {...register('code', {
                       onChange: (e) => setValue('code', e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_')),
                     })} />
            </div>
            <Textarea label="Description" rows={2} placeholder="What this scheme rewards and who it covers"
                      {...register('description')} />
            <div className="grid grid-cols-3 gap-4">
              <Controller name="target_entity_type" control={control} render={({ field }) => (
                <Select label="Pays (entity type)" placeholder="Choose…"
                        error={errors.target_entity_type?.message}
                        value={field.value ? String(field.value) : ''}
                        onChange={(e) => field.onChange(Number(e.target.value))}
                        options={entityTypes.map((t) => ({ value: String(t.id), label: t.name }))} />
              )} />
              <Controller name="channel" control={control} render={({ field }) => (
                <Select label="Channel (optional)"
                        value={field.value ? String(field.value) : ''}
                        onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : null)}
                        options={[{ value: '', label: 'All channels' },
                                  ...channels.map((c) => ({ value: String(c.id), label: c.name }))]} />
              )} />
              <Controller name="payout_frequency" control={control} render={({ field }) => (
                <Select label="SIP component" value={field.value}
                        onChange={(e) => field.onChange(e.target.value)}
                        options={[{ value: 'monthly', label: 'Monthly KPIs (runs per month)' },
                                  { value: 'annual', label: 'Annual performance (one run per year)' }]} />
              )} />
              <Input label="Variable-pay basis %" type="number" min={1} max={100} step="0.01"
                     hint="Share of VP this component pays against — e.g. 80 monthly + 20 annual"
                     error={errors.vp_basis_pct?.message} {...register('vp_basis_pct')} />
            </div>
            {entityTypes.length === 0 && (
              <p className="text-sm text-amber-600">
                No entity type is marked incentive-eligible yet — set that flag on an entity type first.
              </p>
            )}
          </div>
        )}

        {/* ── Step 2: KPIs & weightage ── */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Add the KPIs this scheme rewards and how much each one matters. Weightages must total 100%.
              </p>
              <Badge variant={Math.abs(weightSum - 100) < 0.001 ? 'success' : 'warning'}>
                Total weight: {weightSum.toFixed(2)}%
              </Badge>
            </div>
            {typeof errors.kpis?.message === 'string' && (
              <p className="text-sm text-danger">{errors.kpis.message}</p>
            )}

            {kpiArray.fields.map((row, i) => (
              <div key={row.id} className="rounded-lg border border-gray-200 p-4">
                <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_36px] items-end gap-3">
                  <Controller name={`kpis.${i}.kpi`} control={control} render={({ field }) => (
                    <Select label="KPI" placeholder="Choose…"
                            error={errors.kpis?.[i]?.kpi?.message}
                            value={field.value ? String(field.value) : ''}
                            onChange={(e) => field.onChange(Number(e.target.value))}
                            options={kpiOptions.map((k) => ({ value: String(k.id), label: `${k.name} (${k.code})` }))} />
                  )} />
                  <Controller name={`kpis.${i}.incentive_category`} control={control} render={({ field }) => (
                    <Select label="Category" value={field.value}
                            onChange={(e) => field.onChange(e.target.value)}
                            options={[{ value: 'sales', label: 'Sales' }, { value: 'execution', label: 'Execution' }]} />
                  )} />
                  <Input label="Weight %" type="number" min={0} step="0.01"
                         error={errors.kpis?.[i]?.weightage?.message}
                         {...register(`kpis.${i}.weightage`)} />
                  <Input label="Min qualify %" type="number" min={0} step="0.01" placeholder="—"
                         {...register(`kpis.${i}.min_qualifying_pct`)} />
                  <Input label="Cap ×" type="number" min={0} step="0.001" placeholder="—"
                         {...register(`kpis.${i}.multiplier_cap`)} />
                  <button type="button" onClick={() => kpiArray.remove(i)}
                          disabled={kpiArray.fields.length <= 1}
                          aria-label={`Remove KPI ${i + 1}`}
                          className="mb-1 flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-danger/10 hover:text-danger disabled:opacity-30">
                    <Trash2 size={15} />
                  </button>
                </div>
                <p className="mt-2 text-xs text-gray-400">
                  Category drives exception handling (e.g., on approved leave, sales KPIs can default
                  to 1× while execution KPIs stay actual). Min qualify zeroes the line below that
                  achievement; Cap limits the multiplier.
                </p>
              </div>
            ))}

            <Button type="button" variant="outline" size="sm" icon={<Plus size={14} />}
                    onClick={() => kpiArray.append({ kpi: 0, incentive_category: 'sales', weightage: '',
                                                     min_qualifying_pct: '', multiplier_cap: '', tiers: defaultTiers() })}>
              Add KPI
            </Button>
          </div>
        )}

        {/* ── Step 3: Tiers ── */}
        {step === 2 && (
          <div className="space-y-4">
            <p className="text-sm text-gray-500">
              For each KPI, map achievement % to a payout multiplier. Bands are contiguous steps —
              min is inclusive, max is exclusive, and the last band is unlimited.
            </p>
            <Tabs
              tabs={kpis.map((k, i) => ({ value: String(i), label: kpiName(k.kpi) }))}
              activeTab={tierTab}
              onChange={setTierTab}
            />
            {kpis.map((_, i) => (
              String(i) === tierTab && (
                <div key={i}>
                  {typeof errors.kpis?.[i]?.tiers?.message === 'string' && (
                    <p className="mb-2 text-sm text-danger">{errors.kpis[i]?.tiers?.message}</p>
                  )}
                  <Controller name={`kpis.${i}.tiers`} control={control} render={({ field }) => (
                    <TierBuilder value={field.value} onChange={field.onChange} />
                  )} />
                </div>
              )
            ))}
          </div>
        )}

        {/* ── Step 4: Gate criteria & caps ── */}
        {step === 3 && (
          <div className="space-y-5">
            <div>
              <p className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
                <ShieldCheck size={15} className="text-primary" /> Gate criteria (all must pass)
              </p>
              <p className="text-xs text-gray-500">
                Qualifying hurdles checked before any incentive is paid — e.g. RCPA ≥ 85%,
                geofenced coverage ≥ 85%, iQuest ≥ 80%. If any gate fails, the chosen consequence
                applies to the whole payout regardless of other performance.
              </p>
            </div>

            {gateArray.fields.map((field, i) => (
              <div key={field.id} className="grid grid-cols-[1fr_9rem_9rem_auto] items-end gap-3 rounded-lg border border-gray-200 p-3">
                <Controller name={`gates.${i}.kpi`} control={control} render={({ field: f }) => (
                  <Select label="Gate KPI" placeholder="Choose…"
                          error={errors.gates?.[i]?.kpi?.message}
                          value={f.value ? String(f.value) : ''}
                          onChange={(e) => f.onChange(e.target.value ? Number(e.target.value) : 0)}
                          options={kpiOptions.map((k) => ({ value: String(k.id), label: `${k.name} (${k.code})` }))} />
                )} />
                <Controller name={`gates.${i}.operator`} control={control} render={({ field: f }) => (
                  <Select label="Passes when" value={f.value}
                          onChange={(e) => f.onChange(e.target.value)}
                          options={[{ value: 'gte', label: '≥ threshold' }, { value: 'gt', label: '> threshold' }]} />
                )} />
                <Input label="Threshold %" type="number" min={0} step="0.01"
                       error={errors.gates?.[i]?.threshold_pct?.message}
                       {...register(`gates.${i}.threshold_pct`)} />
                <Button type="button" variant="ghost" size="sm" onClick={() => gateArray.remove(i)}>
                  <Trash2 className="h-4 w-4 text-danger" />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" icon={<Plus className="h-4 w-4" />}
                    onClick={() => gateArray.append({ kpi: 0, operator: 'gte', threshold_pct: '' })}>
              Add gate
            </Button>

            {gatesWatch.length > 0 && (
              <div className="w-72">
                <Controller name="gatekeeper_action" control={control} render={({ field }) => (
                  <Select label="If any gate fails" value={field.value}
                          onChange={(e) => field.onChange(e.target.value)}
                          options={[{ value: 'zero_payout', label: 'Zero the payout' },
                                    { value: 'cap_at_1x', label: 'Cap multipliers at 1×' }]} />
                )} />
              </div>
            )}

            <div className="w-64">
              <Input label="Overall payout cap % (optional)" type="number" min={0} step="0.01"
                     placeholder="e.g. 150"
                     hint="Total payout never exceeds this % of eligible variable pay"
                     {...register('overall_cap_pct')} />
            </div>
          </div>
        )}

        {/* ── Step 5: Review ── */}
        {step === 4 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="rounded-lg bg-gray-50 p-4">
                <p className="mb-2 text-xs font-semibold uppercase text-gray-500">Scheme</p>
                <p className="font-medium text-gray-900">{getValues('name')} <code className="ml-1 text-xs text-gray-500">{getValues('code')}</code></p>
                <p className="text-gray-600">
                  Pays {entityTypes.find((t) => t.id === getValues('target_entity_type'))?.name ?? '—'}
                  {' · '}{channels.find((c) => c.id === getValues('channel'))?.name ?? 'All channels'}
                  {' · '}VP basis {getValues('vp_basis_pct')}%
                  {getValues('overall_cap_pct') && ` · capped at ${getValues('overall_cap_pct')}% of VP`}
                </p>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <p className="mb-2 text-xs font-semibold uppercase text-gray-500">Gate criteria</p>
                {gatesWatch.length > 0 ? (
                  <div className="space-y-0.5 text-gray-700">
                    {gatesWatch.map((g, i) => (
                      <p key={i}>
                        {kpiName(g.kpi)} {g.operator === 'gt' ? '>' : '≥'} {g.threshold_pct}%
                      </p>
                    ))}
                    <p className="pt-1 text-xs text-gray-500">
                      All must pass → otherwise{' '}
                      {getValues('gatekeeper_action') === 'zero_payout' ? 'zero payout' : 'multipliers capped at 1×'}
                    </p>
                  </div>
                ) : (
                  <p className="text-gray-500">None</p>
                )}
              </div>
            </div>

            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-200 text-xs uppercase text-gray-500">
                <tr>
                  <th className="py-2 pr-4">KPI</th>
                  <th className="py-2 pr-4">Category</th>
                  <th className="py-2 pr-4 text-right">Weight</th>
                  <th className="py-2 pr-4">Tiers</th>
                  <th className="py-2">Limits</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {kpis.map((k, i) => (
                  <tr key={i}>
                    <td className="py-2 pr-4 font-medium text-gray-900">{kpiName(k.kpi)}</td>
                    <td className="py-2 pr-4"><Badge variant={k.incentive_category === 'sales' ? 'info' : 'purple'}>{k.incentive_category}</Badge></td>
                    <td className="py-2 pr-4 text-right">{k.weightage}%</td>
                    <td className="py-2 pr-4 text-xs text-gray-600">
                      {k.tiers.map((t) =>
                        `${t.min_achievement_pct}–${t.max_achievement_pct ?? '∞'}→${t.multiplier}×`,
                      ).join('  ')}
                    </td>
                    <td className="py-2 text-xs text-gray-500">
                      {k.min_qualifying_pct && `min ${k.min_qualifying_pct}%`}
                      {k.min_qualifying_pct && k.multiplier_cap && ' · '}
                      {k.multiplier_cap && `cap ${k.multiplier_cap}×`}
                      {!k.min_qualifying_pct && !k.multiplier_cap && '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {serverErrors.length > 0 && (
              <div className="rounded-lg border border-danger/30 bg-danger/5 p-3">
                <p className="mb-1 text-sm font-medium text-danger">The configuration was rejected:</p>
                <ul className="list-inside list-disc text-sm text-danger">
                  {serverErrors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Footer nav */}
        <div className="mt-6 flex justify-between border-t border-gray-100 pt-4">
          <Button variant="outline" onClick={() => setStep((s) => Math.max(0, s - 1))}
                  disabled={step === 0} icon={<ArrowLeft size={14} />}>
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => void next()} iconRight={<ArrowRight size={14} />}>
              Continue
            </Button>
          ) : (
            <Button onClick={() => void save()} loading={saving} icon={<Check size={14} />}>
              {editId ? 'Save as new version' : 'Create scheme'}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
