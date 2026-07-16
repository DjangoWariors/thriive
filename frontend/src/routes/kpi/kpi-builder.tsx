import {useEffect, useMemo, useState} from 'react';
import {useNavigate, useParams, useSearchParams} from 'react-router';
import {
    ChevronLeft, ChevronRight, ArrowLeft, Play, Sparkles, Tag, Settings2, Filter, FlaskConical, Plus, Info,
} from 'lucide-react';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Textarea} from '../../components/ui/Textarea';
import {Badge} from '../../components/ui/Badge';
import {Spinner} from '../../components/ui/Spinner';
import {InfoTooltip} from '../../components/ui/InfoTooltip';
import {Stepper, StepIntro, Example, type WizardStep} from '../../components/ui/WizardChrome';
import {MeasurementBuilder} from '../../components/builders/MeasurementBuilder';
import {EntityCombobox, type EntitySelection} from '../../components/entity/EntityCombobox';
import {SKUGroupCombobox} from '../../components/master/SKUGroupCombobox';
import {SKUMultiSelect} from '../../components/master/SKUMultiSelect';
import {useKpi, useCreateKpi, useUpdateKpi, useKpiBlueprint, useKpiTemplates, useExternalMetrics} from '../../hooks/useKpi';
import {useBlueprint, useChannels} from '../../hooks/useEntities';
import {kpiService} from '../../services/kpiService';
import type {
    BooleanOperator, GrowthBasis, GrowthOutput, KPIConfigPayload, KpiTemplate, KpiType,
} from '../../types/kpi';
import {type BuilderState, INITIAL, kpiToBuilderState} from './builderState';
import {resolveTemplateIcon} from './kpiTemplates';
import {describeKpi} from './describeKpi';
import {kpiFormula} from './kpiFormula';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {EXTERNAL_METRICS_ENABLED} from '../../config/features';

const KPI_TYPES: { value: KpiType; label: string; hint: string; note?: string }[] = [
    {
        value: 'value',
        label: 'Total value (sum)',
        hint: 'Sum of a value or quantity — e.g. total secondary sales for the period.'
    },
    {value: 'count', label: 'Transaction count', hint: 'Count of matching transactions.'},
    {
        value: 'count_distinct',
        label: 'Unique count (distinct)',
        hint: 'Distinct count of a field — outlets, bills or SKUs (e.g. Effective Coverage).'
    },
    {
        value: 'ratio',
        label: 'Ratio (value per value)',
        hint: 'One aggregate divided by another — e.g. value per bill (drop size), lines per bill.',
        note: 'Aggregated as total numerator ÷ total denominator over the entity’s subtree — not the average of each child’s ratio. Only the former is correct at roll-up.'
    },
    {
        value: 'growth',
        label: 'Growth vs prior period',
        hint: 'Current period vs a prior period — e.g. YoY growth %.',
        note: 'The comparison window (including to-date) is aligned automatically, so growth stays accurate on any day of the period. Do not model it as two separate KPIs.'
    },
    {
        value: 'composite',
        label: 'Composite (weighted KPIs)',
        hint: 'Weighted combination of existing KPIs.',
        note: 'References existing KPI codes only. To use raw transaction fields, choose a measure-based type instead.'
    },
    {
        value: 'boolean',
        label: 'Met / not-met flag',
        hint: 'Threshold test returning 1 (met) or 0 (not met) — e.g. MSL compliance.',
        note: 'Resolves to 1 or 0, so it can be averaged and fed into composite scorecards or compliance reports.'
    },
    {
        value: 'external',
        label: 'External metric (SFA / agency feed)',
        hint: 'Reads a non-sales fact stream pushed from outside — productive calls, activation adherence, RCPA %, TLSD.',
        note: 'Define the metric under Admin → External Metrics first, then feed values via API push or CSV. Person-grain scores never roll up to managers.'
    },
];

const EXTERNAL_AGG_OPTIONS = [
    {value: '', label: 'Metric default'},
    {value: 'sum', label: 'Sum over the period'},
    {value: 'avg', label: 'Average over the period'},
    {value: 'latest', label: 'Latest value in the period'},
    {value: 'max', label: 'Maximum in the period'},
];

const BASIS_OPTIONS: { value: GrowthBasis; label: string }[] = [
    {value: 'last_year_same_period', label: 'Same period last year (YoY)'},
    {value: 'previous_period', label: 'Previous period'},
    {value: 'previous_month', label: 'Previous month'},
    {value: 'custom_month_offset', label: 'Custom month offset'},
];
const OUTPUT_OPTIONS: { value: GrowthOutput; label: string }[] = [
    {value: 'growth_pct', label: 'Growth %'},
    {value: 'growth_absolute', label: 'Absolute change'},
    {value: 'index', label: 'Index (current ÷ base × 100)'},
];
const OPERATOR_OPTIONS: { value: BooleanOperator; label: string }[] = [
    {value: 'gte', label: '≥ (at least)'},
    {value: 'gt', label: '> (greater than)'},
    {value: 'lte', label: '≤ (at most)'},
    {value: 'lt', label: '< (less than)'},
    {value: 'eq', label: '= (equals)'},
];

// First and last day of the current month, as YYYY-MM-DD — sensible defaults for the preview.
function currentMonthRange(): { start: string; end: string } {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth();
    const pad = (n: number) => String(n).padStart(2, '0');
    return {
        start: `${y}-${pad(m + 1)}-01`,
        end: `${y}-${pad(m + 1)}-${pad(new Date(y, m + 1, 0).getDate())}`,
    };
}

type StepKey = 'start' | 'basics' | 'definition' | 'scope' | 'preview';

const STEP_DEF: Record<StepKey, { step: WizardStep; intro: { title: string; body: string } }> = {
    start: {
        step: {label: 'Template', icon: Sparkles},
        intro: {
            title: 'Start from a template',
            body: 'Select a template to prefill the configuration, or start from scratch. Everything remains editable.'
        },
    },
    basics: {
        step: {label: 'Details', icon: Tag},
        intro: {
            title: 'KPI details',
            body: 'Set the display name, code (referenced in composite formulas), and metric type.'
        },
    },
    definition: {
        step: {label: 'Calculation', icon: Settings2},
        intro: {
            title: 'Define the calculation',
            body: 'Configure the aggregation and measure. The formula and description below update live.'
        },
    },
    scope: {
        step: {label: 'Scope', icon: Filter},
        intro: {
            title: 'Scope',
            body: 'Restrict the KPI to specific roles, channels or SKUs. Leave a filter blank to apply to all.'
        },
    },
    preview: {
        step: {label: 'Preview', icon: FlaskConical},
        intro: {
            title: 'Preview & save',
            body: 'Evaluate the KPI against an entity and date range before saving. Nothing is persisted until you save.'
        },
    },
};

export default function KpiBuilderPage() {
    const navigate = useNavigate();
    const params = useParams();
    const [searchParams] = useSearchParams();
    const editId = params.id ? Number(params.id) : null;
    const cloneParam = searchParams.get('clone');
    const cloneId = !editId && cloneParam ? Number(cloneParam) : null;

    const {data: existing, isLoading: loadingExisting} = useKpi(editId);
    const {data: cloneSrc} = useKpi(cloneId);
    const {data: entityTypes} = useBlueprint();
    const {data: channelsResp} = useChannels();
    const {data: kpiBlueprint} = useKpiBlueprint();
    const {data: templates, isLoading: loadingTemplates} = useKpiTemplates();
    const create = useCreateKpi();
    const update = useUpdateKpi();

    const stepKeys: StepKey[] = editId
        ? ['basics', 'definition', 'scope', 'preview']
        : ['start', 'basics', 'definition', 'scope', 'preview'];

    const [step, setStep] = useState(0);
    const [s, setS] = useState<BuilderState>(INITIAL);
    const set = (patch: Partial<BuilderState>) => setS((prev) => ({...prev, ...patch}));
    const currentKey = stepKeys[step];

    useEffect(() => {
        if (existing) setS(kpiToBuilderState(existing));
    }, [existing]);

    // Cloning: prefill from an existing KPI but blank the code so it saves as a brand-new one.
    useEffect(() => {
        if (cloneSrc) {
            const base = kpiToBuilderState(cloneSrc);
            setS({...base, code: '', name: base.name ? `${base.name} (copy)` : ''});
            setStep(1); // skip the Start step, land on Basics
        }
    }, [cloneSrc]);

    const channels = channelsResp?.results ?? [];

    const payload = useMemo<KPIConfigPayload>(() => {
        const body: KPIConfigPayload = {
            code: s.code.trim(), name: s.name.trim(), description: s.description,
            category: s.category, unit: s.unit, decimal_places: s.decimal_places, kpi_type: s.kpi_type,
            applicable_entity_types: s.applicable_entity_types,
            channel_filter: s.channel_filter,
            sku_filter:
                s.sku_filter_type === 'group'
                    ? {type: 'group', group_code: s.sku_group_code}
                    : s.sku_filter_type === 'explicit'
                        ? {type: 'explicit', sku_codes: s.sku_codes.split(',').map((c) => c.trim()).filter(Boolean)}
                        : {type: 'all'},
        };
        if (['value', 'count', 'count_distinct', 'growth', 'boolean'].includes(s.kpi_type)) {
            body.measure_config = s.measure_config;
        }
        if (s.kpi_type === 'ratio') {
            body.ratio_config = {numerator: s.ratio_numerator, denominator: s.ratio_denominator};
        }
        if (s.kpi_type === 'growth') {
            body.growth_config = {
                basis: s.basis,
                output: s.output, ...(s.basis === 'custom_month_offset' ? {offset: s.offset} : {})
            };
        }
        if (s.kpi_type === 'composite') {
            const codes = Array.from(new Set((s.expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [])));
            body.composite_config = {expression: s.expression, components: codes.map((c) => ({kpi_code: c}))};
        }
        if (s.kpi_type === 'boolean') {
            body.boolean_config = {operator: s.operator, threshold: s.threshold};
        }
        if (s.kpi_type === 'external') {
            body.external_config = {
                metric_code: s.metric_code,
                ...(s.external_aggregation ? {aggregation: s.external_aggregation} : {}),
                target_source: s.target_source,
                ...(s.target_source === 'fixed' ? {fixed_target: s.fixed_target} : {}),
            };
        }
        return body;
    }, [s]);

    // Validate the config server-side whenever it changes, so problems surface early —
    // on the step where they're fixed, not only at the final Save.
    const [issues, setIssues] = useState<string[] | null>(null);
    useEffect(() => {
        let cancelled = false;
        kpiService.validate(payload)
            .then((res) => {
                if (!cancelled) setIssues(res.valid ? [] : res.errors);
            })
            .catch(() => {
                if (!cancelled) setIssues(null);
            });
        return () => {
            cancelled = true;
        };
    }, [payload]);

    function applyTemplate(t: KpiTemplate) {
        setS(kpiToBuilderState(t));
        setStep((x) => x + 1);
    }

    function startFromScratch() {
        setS(INITIAL);
        setStep((x) => x + 1);
    }

    function save() {
        const onError = (e: unknown) => notify.error(apiErrorMessage(e, 'Save failed. Check the configuration and try again.'));
        if (editId) {
            update.mutate({id: editId, payload}, {
                onSuccess: () => {
                    notify.success('KPI saved — a new version was created; prior versions are retained.');
                    navigate('/kpi/definitions');
                },
                onError,
            });
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('KPI created.');
                    navigate('/kpi/definitions');
                },
                onError,
            });
        }
    }

    if (editId && loadingExisting) {
        return <div className="flex justify-center py-20"><Spinner size="lg"/></div>;
    }

    const canNext = currentKey === 'basics' ? s.code.trim() !== '' && s.name.trim() !== '' : true;
    const saving = create.isPending || update.isPending;
    const isLast = step === stepKeys.length - 1;

    return (
        <div className="p-6">
            <button onClick={() => navigate('/kpi/definitions')}
                    className="mb-3 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
                <ArrowLeft className="h-4 w-4"/> Back to KPIs
            </button>
            <h1 className="text-2xl font-bold text-gray-900">{editId ? `Edit ${s.code}` : 'Create KPI'}</h1>

            <div className="my-5">
                <Stepper
                    steps={stepKeys.map((k) => STEP_DEF[k].step)}
                    current={step}
                    onStepClick={(i) => {
                        if (i < step) setStep(i);
                    }}
                />
            </div>

            <div className="max-w-3xl rounded-xl border border-gray-200 bg-white p-6">
                <StepIntro {...STEP_DEF[currentKey].intro} />
                {currentKey === 'start' && (
                    <StartStep
                        templates={(templates ?? []).filter((t) => EXTERNAL_METRICS_ENABLED || t.kpi_type !== 'external')}
                        loading={loadingTemplates}
                        onPick={applyTemplate}
                        onScratch={startFromScratch}
                    />
                )}
                {currentKey === 'basics' && <BasicsStep s={s} set={set} editing={!!editId}/>}
                {currentKey === 'definition' && (
                    <DefinitionStep s={s} set={set}
                                    kpiCodes={(kpiBlueprint ?? []).map((k) => k.code).filter((c) => c !== s.code)}/>
                )}
                {currentKey === 'scope' && (
                    <ScopeStep
                        s={s} set={set}
                        entityTypes={(entityTypes ?? []).map((t) => ({code: t.code, name: t.name}))}
                        channels={channels.map((c) => ({code: c.code, name: c.name}))}
                    />
                )}
                {currentKey === 'preview' && <PreviewStep payload={payload}/>}
            </div>

            {/* Show config problems once the calculation is being defined — not on Basics,
                where the measure isn't set yet and the errors would just be premature noise. */}
            {['definition', 'scope', 'preview'].includes(currentKey) && issues && issues.length > 0 && (
                <div className="mt-3 max-w-3xl rounded-lg border border-danger-100 bg-danger-50 px-4 py-3">
                    <p className="text-xs font-medium text-danger">Fix these before saving:</p>
                    <ul className="mt-1 list-disc pl-4 text-sm text-danger">
                        {issues.map((m) => <li key={m}>{m}</li>)}
                    </ul>
                </div>
            )}

            {currentKey !== 'start' && (
                <div className="mt-3 max-w-3xl rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Formula</p>
                    <p className="mt-0.5 font-mono text-sm text-gray-800">{kpiFormula(payload)}</p>
                    <p className="mt-2 text-xs font-medium uppercase tracking-wide text-gray-400">What this KPI measures</p>
                    <p className="mt-0.5 text-sm text-gray-700">{describeKpi(payload)}</p>
                </div>
            )}

            {currentKey !== 'start' && (
                <div className="mt-5 max-w-3xl">
                    <div className="flex justify-between">
                        <Button variant="outline" icon={<ChevronLeft className="h-4 w-4"/>} disabled={step === 0}
                                onClick={() => setStep((x) => x - 1)}>
                            Back
                        </Button>
                        {!isLast ? (
                            <Button iconRight={<ChevronRight className="h-4 w-4"/>} disabled={!canNext}
                                    onClick={() => setStep((x) => x + 1)}>
                                Next
                            </Button>
                        ) : (
                            <Button loading={saving} disabled={!!issues && issues.length > 0}
                                    onClick={save}>{editId ? 'Save changes' : 'Create KPI'}</Button>
                        )}
                    </div>
                    {currentKey === 'basics' && !canNext && (
                        <p className="mt-2 text-right text-xs text-gray-400">
                            Enter a display name and code to continue.
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

// ── steps ────────────────────────────────────────────────────────────────────
function StartStep({templates, loading, onPick, onScratch}: {
    templates: KpiTemplate[];
    loading: boolean;
    onPick: (t: KpiTemplate) => void;
    onScratch: () => void;
}) {
    if (loading) {
        return <div className="flex justify-center py-10"><Spinner/></div>;
    }
    return (
        <div className="grid grid-cols-2 gap-3">
            {templates.map((t) => {
                const Icon = resolveTemplateIcon(t.icon);
                return (
                    <button
                        key={t.id}
                        type="button"
                        onClick={() => onPick(t)}
                        className="flex flex-col gap-2 rounded-lg border border-gray-200 bg-white p-4 text-left transition-colors hover:border-primary hover:bg-primary-50"
                    >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-50 text-primary">
              <Icon className="h-5 w-5"/>
            </span>
                        <span className="text-sm font-semibold text-gray-900">{t.name}</span>
                        <span className="text-xs leading-relaxed text-gray-500">{t.description}</span>
                    </button>
                );
            })}
            <button
                type="button"
                onClick={onScratch}
                className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 bg-white p-4 text-center transition-colors hover:border-primary hover:bg-primary-50"
            >
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-500">
          <Plus className="h-5 w-5"/>
        </span>
                <span className="text-sm font-semibold text-gray-900">Blank KPI</span>
                <span className="text-xs leading-relaxed text-gray-500">Configure from an empty definition.</span>
            </button>
        </div>
    );
}

function BasicsStep({s, set, editing}: { s: BuilderState; set: (p: Partial<BuilderState>) => void; editing: boolean }) {
    const activeType = KPI_TYPES.find((t) => t.value === s.kpi_type);
    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Display name" value={s.name} onChange={(e) => set({name: e.target.value})}
                       hint="Shown on dashboards and reports." placeholder="e.g. Secondary Sales (Net)"/>
                <div>
                    <Input label="Code" value={s.code} disabled={editing}
                           onChange={(e) => set({code: e.target.value.toUpperCase().replace(/\s+/g, '_')})}
                           hint={editing ? "A KPI's code can't be changed once created." : 'Unique identifier, used in formulas.'}
                           placeholder="SECONDARY_NSV"/>
                    {!editing &&
                        <Example>Referenced in composite KPIs, e.g. <code className="rounded bg-gray-100 px-1">0.6 *
                            SECONDARY_NSV</code>.</Example>}
                </div>
                <Input label="Category" value={s.category} onChange={(e) => set({category: e.target.value})}
                       hint="Groups KPIs in lists and schemes."
                       placeholder="e.g. Sales, Distribution, Compliance"/>
                <Input label="Unit" value={s.unit} onChange={(e) => set({unit: e.target.value})}
                       hint="Displayed after the value." placeholder="e.g. ₹, cases, %, outlets"/>
                <div>
          <span className="mb-1 flex items-center gap-1.5 text-sm font-medium text-gray-700">
            Decimal places
            <InfoTooltip
                content="Decimal places to display. Use 0 for whole numbers, 1–2 for ratios and percentages."/>
          </span>
                    <Input type="number" value={s.decimal_places}
                           onChange={(e) => set({decimal_places: Number(e.target.value)})}/>
                </div>
                <Select label="Metric type" value={s.kpi_type}
                        onChange={(e) => set({kpi_type: e.target.value as KpiType})}
                        options={KPI_TYPES
                            .filter((t) => t.value !== 'external' || EXTERNAL_METRICS_ENABLED || s.kpi_type === 'external')
                            .map((t) => ({value: t.value, label: t.label}))}/>
            </div>
            {activeType && (
                <div className="rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-dark">
                    <p>{activeType.hint}</p>
                    {activeType.note && <p className="mt-1.5 text-primary-dark/80">{activeType.note}</p>}
                </div>
            )}
            <Textarea label="Description (optional)" value={s.description}
                      onChange={(e) => set({description: e.target.value})} rows={2}
                      placeholder="A short description so colleagues know what this measures and why."/>
        </div>
    );
}

function DefinitionStep({s, set, kpiCodes}: {
    s: BuilderState;
    set: (p: Partial<BuilderState>) => void;
    kpiCodes: string[]
}) {
    if (['value', 'count', 'count_distinct'].includes(s.kpi_type)) {
        return <MeasurementBuilder value={s.measure_config} onChange={(m) => set({measure_config: m})}
                                   title="Measure"/>;
    }
    if (s.kpi_type === 'external') {
        return <ExternalDefinition s={s} set={set}/>;
    }
    if (s.kpi_type === 'ratio') {
        return (
            <div className="space-y-4">
                <p className="text-sm text-gray-500">A ratio divides a numerator by a denominator — for example,
                    total sales ÷ number of bills gives the average value per bill.</p>
                <MeasurementBuilder value={s.ratio_numerator} onChange={(m) => set({ratio_numerator: m})}
                                    title="Numerator"/>
                <div className="text-center text-2xl text-gray-300">÷</div>
                <MeasurementBuilder value={s.ratio_denominator} onChange={(m) => set({ratio_denominator: m})}
                                    title="Denominator"/>
            </div>
        );
    }
    if (s.kpi_type === 'growth') {
        return (
            <div className="space-y-4">
                <MeasurementBuilder value={s.measure_config} onChange={(m) => set({measure_config: m})}
                                    title="Base measure"/>
                <div className="grid grid-cols-2 gap-3">
                    <div>
                        <span className="mb-1 flex items-center gap-1.5 text-sm font-medium text-gray-700">
                            Comparison basis
                            <InfoTooltip content="The comparison window is derived from the compute range, so a period-to-date comparison is automatic: computing on the 12th compares the 1st–12th against the prior period's 1st–12th, keeping growth like-for-like on any day of the period." />
                        </span>
                        <Select aria-label="Comparison basis" value={s.basis}
                                onChange={(e) => set({basis: e.target.value as GrowthBasis})} options={BASIS_OPTIONS}/>
                    </div>
                    <Select label="Output" value={s.output}
                            onChange={(e) => set({output: e.target.value as GrowthOutput})} options={OUTPUT_OPTIONS}/>
                    {s.basis === 'custom_month_offset' && (
                        <Input label="Months offset" type="number" value={s.offset}
                               onChange={(e) => set({offset: Number(e.target.value)})}/>
                    )}
                </div>
            </div>
        );
    }
    if (s.kpi_type === 'boolean') {
        return (
            <div className="space-y-4">
                <MeasurementBuilder value={s.measure_config} onChange={(m) => set({measure_config: m})}
                                    title="Base measure"/>
                <div className="flex flex-wrap items-end gap-2 text-sm text-gray-600">
                    <span className="pb-2">Met when result is</span>
                    <div className="w-40">
                        <Select aria-label="Comparison operator" value={s.operator}
                                onChange={(e) => set({operator: e.target.value as BooleanOperator})}
                                options={OPERATOR_OPTIONS}/>
                    </div>
                    <div className="w-32">
                        <Input aria-label="Threshold" value={s.threshold} onChange={(e) => set({threshold: e.target.value})}
                               placeholder="e.g. 10"/>
                    </div>
                </div>
                <p className="text-xs text-gray-500">Resolves to 1 (met) or 0 (not met).</p>
            </div>
        );
    }
    // composite
    const knownCodes = new Set(kpiCodes);
    const refs = Array.from(new Set(s.expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? []));
    const unknownRefs = refs.filter((r) => !knownCodes.has(r));
    return (
        <div className="space-y-3">
            <p className="text-sm text-gray-500">
                Weighted combination of existing KPIs. Enter an expression referencing their codes — click a code below
                to insert it.
            </p>
            <p className="flex items-start gap-1.5 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                    A composite stores the <strong>expression, not a fixed value</strong>. Each component KPI is
                    recomputed from source data for the entity and period in view, then combined — so the definition
                    rolls up correctly at every level of the hierarchy.
                </span>
            </p>
            <Textarea label="Expression" value={s.expression} onChange={(e) => set({expression: e.target.value})} rows={3}
                      placeholder="e.g.  0.7 * SECONDARY_NSV + 0.3 * FOCUS_SALES"/>
            {refs.length > 0 && (
                unknownRefs.length > 0
                    ? <p className="text-xs text-danger">Unknown KPI code(s): {unknownRefs.join(', ')}. Insert a code below or check the spelling.</p>
                    : <p className="text-xs text-success">All {refs.length} code{refs.length === 1 ? '' : 's'} resolved.</p>
            )}
            <div>
                <p className="mb-1 text-xs font-medium text-gray-500">Insert a KPI code:</p>
                <div className="flex flex-wrap gap-1.5">
                    {kpiCodes.map((code) => (
                        <button key={code} type="button"
                                onClick={() => set({expression: `${s.expression}${s.expression ? ' ' : ''}${code}`})}
                                className="rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-600 hover:border-primary hover:text-primary">
                            {code}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
}

function ExternalDefinition({s, set}: { s: BuilderState; set: (p: Partial<BuilderState>) => void }) {
    const {data: metricsResp, isLoading} = useExternalMetrics();
    const metrics = metricsResp?.results ?? [];
    const selected = metrics.find((m) => m.code === s.metric_code);

    if (isLoading) return <div className="flex justify-center py-8"><Spinner/></div>;
    return (
        <div className="space-y-4">
            <p className="flex items-start gap-1.5 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0"/>
                <span>
                    External KPIs read a <strong>fact stream pushed from outside</strong> (SFA calls, agency
                    scores, TLSD) instead of sales transactions. Values arrive via the push API or CSV import
                    under Admin → External Metrics.
                </span>
            </p>
            <Select
                label="External metric"
                value={s.metric_code}
                onChange={(e) => set({metric_code: e.target.value})}
                options={[
                    {value: '', label: metrics.length ? 'Select a metric…' : 'No metrics defined yet'},
                    ...metrics.map((m) => ({value: m.code, label: `${m.name} (${m.code})`})),
                ]}
            />
            {metrics.length === 0 && EXTERNAL_METRICS_ENABLED && (
                <p className="text-xs text-gray-500">
                    Define the metric first under{' '}
                    <a href="/admin/external-metrics" target="_blank" rel="noopener noreferrer"
                       className="font-medium text-primary hover:underline">Admin → External Metrics</a>.
                </p>
            )}
            {selected && (
                <p className="text-xs text-gray-500">
                    {selected.granularity === 'entity'
                        ? 'Person-grain: each value belongs to one person; managers do not get a rolled-up score.'
                        : 'Territory-grain: values attach to geography nodes and roll up the owned subtree like sales.'}
                    {' '}Grain: {selected.period_grain}. Default aggregation: {selected.default_aggregation}.
                </p>
            )}
            <Select label="Aggregation over the period" value={s.external_aggregation}
                    onChange={(e) => set({external_aggregation: e.target.value as BuilderState['external_aggregation']})}
                    options={EXTERNAL_AGG_OPTIONS}/>
            <div>
                <Select
                    label="Target basis"
                    value={s.target_source}
                    onChange={(e) => set({target_source: e.target.value as BuilderState['target_source']})}
                    options={[
                        {value: 'allocation', label: 'Allocated targets (geography, like sales KPIs)'},
                        {value: 'fixed', label: 'Fixed benchmark (score KPI)'},
                    ]}
                />
                {s.target_source === 'fixed' && (
                    <div className="mt-2">
                        <Input label="Fixed benchmark" value={s.fixed_target}
                               onChange={(e) => set({fixed_target: e.target.value})}
                               hint="Achievement % = value ÷ benchmark × 100. Use 100 for percentage scores (RCPA %, iQuest) so achievement reads as the raw score."/>
                    </div>
                )}
            </div>
        </div>
    );
}

function ChipMultiSelect({label, options, selected, onToggle}: {
    label: string; options: { code: string; name: string }[]; selected: string[]; onToggle: (code: string) => void;
}) {
    return (
        <div>
            <p className="mb-1.5 text-sm font-medium text-gray-700">{label}</p>
            {options.length === 0 ? (
                <p className="text-xs text-gray-400">Nothing set up yet — this KPI will apply to everyone.</p>
            ) : (
                <div className="flex flex-wrap gap-1.5">
                    {options.map((o) => {
                        const active = selected.includes(o.code);
                        return (
                            <button key={o.code} type="button" onClick={() => onToggle(o.code)}
                                    className={['rounded-md border px-2.5 py-1 text-xs',
                                        active ? 'border-primary bg-primary text-white' : 'border-gray-200 bg-gray-50 text-gray-600 hover:border-primary'].join(' ')}>
                                {o.name} <span className="opacity-60">({o.code})</span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function ScopeStep({s, set, entityTypes, channels}: {
    s: BuilderState; set: (p: Partial<BuilderState>) => void;
    entityTypes: { code: string; name: string }[]; channels: { code: string; name: string }[];
}) {
    const toggle = (list: string[], code: string) =>
        list.includes(code) ? list.filter((c) => c !== code) : [...list, code];
    return (
        <div className="space-y-5">
            <ChipMultiSelect label="Applicable roles (blank = all)" options={entityTypes}
                             selected={s.applicable_entity_types}
                             onToggle={(c) => set({applicable_entity_types: toggle(s.applicable_entity_types, c)})}/>
            <ChipMultiSelect label="Channels (blank = all)" options={channels}
                             selected={s.channel_filter}
                             onToggle={(c) => set({channel_filter: toggle(s.channel_filter, c)})}/>
            <div>
                <Select label="SKU filter" value={s.sku_filter_type}
                        onChange={(e) => set({sku_filter_type: e.target.value as BuilderState['sku_filter_type']})}
                        options={[
                            {value: 'all', label: 'All SKUs'},
                            {value: 'group', label: 'SKU group'},
                            {value: 'explicit', label: 'Specific SKUs'},
                        ]}/>
                {s.sku_filter_type === 'group' && (
                    <div className="mt-2 space-y-1">
                        <SKUGroupCombobox value={s.sku_group_code}
                                          onChange={(g) => set({sku_group_code: g ? g.code : ''})}/>
                        <p className="text-xs text-gray-500">
                            Only SKUs in the selected group are included; the chip shows how many resolve today.{' '}
                            <a href="/master/sku-groups?create=1" target="_blank" rel="noopener noreferrer"
                               className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline">
                                <Plus className="h-3 w-3"/>New group
                            </a>
                        </p>
                    </div>
                )}
                {s.sku_filter_type === 'explicit' && (() => {
                    const codes = s.sku_codes.split(',').map((c) => c.trim()).filter(Boolean);
                    return (
                        <div className="mt-2 space-y-1">
                            <SKUMultiSelect value={codes}
                                            onChange={(next) => set({sku_codes: next.join(', ')})}/>
                            <p className="text-xs text-gray-500">
                                {codes.length > 0
                                    ? `Includes ${codes.length} selected SKU${codes.length === 1 ? '' : 's'}.`
                                    : 'Search and add the SKUs to include.'}
                            </p>
                        </div>
                    );
                })()}
            </div>
        </div>
    );
}

function PreviewStep({payload}: { payload: KPIConfigPayload }) {
    const [entity, setEntity] = useState<EntitySelection | null>(null);
    const defaultRange = useMemo(currentMonthRange, []);
    const [start, setStart] = useState(defaultRange.start);
    const [end, setEnd] = useState(defaultRange.end);
    const [result, setResult] = useState<string | null>(null);
    const [resultIsZero, setResultIsZero] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    async function runPreview() {
        if (!entity) return;
        setError(null);
        setResult(null);
        setLoading(true);
        try {
            const res = await kpiService.preview({
                config: payload,
                entity_id: entity.id,
                period_start: start,
                period_end: end
            });
            setResult(`${res.result} ${res.unit}`.trim());
            setResultIsZero(Number(res.result) === 0);
        } catch (e) {
            setError(apiErrorMessage(e, 'Preview failed'));
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="space-y-4">
            <p className="text-sm text-gray-600">
                <strong>Preview</strong> evaluates this KPI on real sales data for one entity and date range, so you can
                validate the result <em>before</em> saving. It does not save the KPI or change any data.
            </p>
            <div className="grid grid-cols-3 gap-3">
                <EntityCombobox label="Entity (person / team)" value={entity} onChange={setEntity}/>
                <Input label="From date" type="date" value={start} onChange={(e) => setStart(e.target.value)}/>
                <Input label="To date" type="date" value={end} onChange={(e) => setEnd(e.target.value)}/>
            </div>
            <p className="text-xs text-gray-500">The result rolls up the selected entity’s whole subtree.</p>
            <Button icon={<Play className="h-4 w-4"/>} loading={loading} disabled={!entity} onClick={runPreview}>
                Run preview
            </Button>
            {result !== null && (
                <div className="rounded-lg border border-success-100 bg-success-50 px-4 py-3">
                    <p className="text-xs text-success">
                        Preview result for {entity?.name} · {start} to {end}
                    </p>
                    <p className="text-2xl font-bold text-success">{result}</p>
                    <p className="mt-1 text-xs text-success/80">Preview only — nothing has been saved yet.</p>
                </div>
            )}
            {result !== null && resultIsZero && (
                <p className="text-xs text-gray-500">
                    Result is 0 — no matching data for this entity and date range, or the KPI evaluates to zero.
                </p>
            )}
            {error && <p className="rounded-lg bg-danger-50 px-3 py-2 text-sm text-danger">{error}</p>}
            <div className="rounded-lg bg-gray-50 px-3 py-2">
                <p className="mb-1 text-xs font-medium text-gray-500">Configuration summary</p>
                <div className="flex flex-wrap gap-1.5">
                    <Badge
                        variant="info">{KPI_TYPES.find((t) => t.value === payload.kpi_type)?.label ?? payload.kpi_type}</Badge>
                    <Badge variant="default">{payload.code || 'no code'}</Badge>
                    {payload.unit && <Badge variant="default">unit: {payload.unit}</Badge>}
                </div>
            </div>
        </div>
    );
}
