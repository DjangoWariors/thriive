import {useState} from 'react';
import type React from 'react';
import {useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {useQueryClient} from '@tanstack/react-query';
import {Plus, Pencil, Trash2, Upload, Radio, Table2} from 'lucide-react';
import {
    useExternalMetrics,
    useCreateExternalMetric,
    useUpdateExternalMetric,
    useDeactivateExternalMetric,
    useMetricValues,
} from '../../hooks/useKpi';
import {useRBAC} from '../../hooks/useRBAC';
import {kpiService} from '../../services/kpiService';
import type {ExternalMetric, ExternalMetricPayload} from '../../types/kpi';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {PageHeader} from '../../components/ui/PageHeader';
import {Pagination} from '../../components/ui/Pagination';
import {Modal} from '../../components/ui/Modal';
import {Badge} from '../../components/ui/Badge';
import {Spinner} from '../../components/ui/Spinner';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {BulkJobProgress} from '../../components/jobs/BulkJobProgress';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';

const GRANULARITY_LABEL: Record<string, string> = {
    entity: 'Person',
    geography_node: 'Territory',
};

export default function ExternalMetricsPage() {
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<ExternalMetric | null>(null);
    const [deleting, setDeleting] = useState<ExternalMetric | null>(null);
    const [importOpen, setImportOpen] = useState(false);
    const [valuesFor, setValuesFor] = useState<ExternalMetric | null>(null);

    const {canWrite} = useRBAC();
    const writable = canWrite('kpi_definitions');

    const {data: resp, isLoading} = useExternalMetrics();
    const deactivate = useDeactivateExternalMetric();
    const metrics = resp?.results ?? [];

    const confirmDelete = () => {
        if (!deleting) return;
        deactivate.mutate(deleting.id, {
            onSuccess: () => {
                notify.success(`${deleting.code} deactivated`);
                setDeleting(null);
            },
            onError: (e) => {
                notify.error(apiErrorMessage(e, 'Could not deactivate metric'));
                setDeleting(null);
            },
        });
    };

    return (
        <div className="p-6">
            <PageHeader
                title="External Metrics"
                description="Fact streams that arrive from outside the sales pipe — SFA productive calls, agency activation scores, TLSD — used by external KPIs and SIP gate criteria."
                actions={writable && (
                    <>
                        <Button variant="outline" icon={<Upload className="h-4 w-4"/>} onClick={() => setImportOpen(true)}>
                            Import values (CSV)
                        </Button>
                        <Button icon={<Plus className="h-4 w-4"/>} onClick={() => {
                            setEditing(null);
                            setFormOpen(true);
                        }}>
                            Add Metric
                        </Button>
                    </>
                )}
            />

            <HowThisWorks storageKey="external-metrics-help" className="mb-6">
                Not everything you incentivise is a sales transaction. Productive calls come from the SFA app,
                activation adherence from an agency tracker, compliance scores from L&amp;D. Define each stream
                here once — person-grain (a score belongs to one person) or territory-grain (counts that roll up
                the geography like sales) — then feed values via the push API or a CSV upload. Any external KPI
                or scheme gate can read them.
            </HowThisWorks>

            {isLoading ? (
                <TableSkeleton/>
            ) : metrics.length === 0 ? (
                <Card>
                    <EmptyState icon={Radio} title="No external metrics yet"
                                description="Add your first metric to start feeding SFA or agency data into KPIs."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={metrics}
                        rowKey={(m) => m.id}
                        columns={[
                            {header: 'Code', render: (m) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{m.code}</code>
                            )},
                            {header: 'Name', render: (m) => <span className="font-medium text-gray-900">{m.name}</span>},
                            {header: 'Attached to', render: (m) => (
                                <Badge variant={m.granularity === 'entity' ? 'info' : 'default'}>
                                    {GRANULARITY_LABEL[m.granularity]}
                                </Badge>
                            )},
                            {header: 'Grain', render: (m) => <span className="text-gray-600">{m.period_grain}</span>},
                            {header: 'Default aggregation', render: (m) => <span className="text-gray-600">{m.default_aggregation}</span>},
                            {header: 'Unit', render: (m) => <span className="text-gray-600">{m.unit || '—'}</span>},
                            {header: 'Actions', align: 'right', render: (m) => (
                                <div className="flex justify-end gap-1">
                                    <Button variant="ghost" size="sm" aria-label={`Browse ${m.code} values`}
                                            onClick={() => setValuesFor(m)}>
                                        <Table2 className="h-4 w-4"/>
                                    </Button>
                                    {writable && (
                                        <>
                                            <Button variant="ghost" size="sm" aria-label={`Edit ${m.code}`} onClick={() => {
                                                setEditing(m);
                                                setFormOpen(true);
                                            }}>
                                                <Pencil className="h-4 w-4"/>
                                            </Button>
                                            <Button variant="ghost" size="sm" aria-label={`Deactivate ${m.code}`}
                                                    onClick={() => setDeleting(m)}>
                                                <Trash2 className="h-4 w-4 text-danger"/>
                                            </Button>
                                        </>
                                    )}
                                </div>
                            )},
                        ]}
                    />
                </Card>
            )}

            <Modal open={formOpen} onClose={() => setFormOpen(false)}
                   title={editing ? `Edit ${editing.code}` : 'Add External Metric'} size="lg">
                <MetricForm existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Import metric values" size="xl">
                <MetricValueImport onClose={() => setImportOpen(false)}/>
            </Modal>

            <Modal open={valuesFor !== null} onClose={() => setValuesFor(null)}
                   title={valuesFor ? `Values — ${valuesFor.name}` : ''} size="xl">
                {valuesFor && <ValuesBrowser metric={valuesFor}/>}
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={confirmDelete}
                title="Deactivate metric"
                message={`Deactivate ${deleting?.code ?? ''}? Metrics still referenced by a KPI cannot be removed.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </div>
    );
}

const metricSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    code: z.string().min(1, 'Code is required').regex(/^[A-Z0-9_]+$/, 'Use A–Z, 0–9, underscore'),
    description: z.string(),
    unit: z.string(),
    granularity: z.enum(['entity', 'geography_node']),
    period_grain: z.enum(['daily', 'monthly']),
    default_aggregation: z.enum(['sum', 'avg', 'latest', 'max']),
});

type MetricFormValues = z.infer<typeof metricSchema>;

function MetricForm({existing, onDone}: { existing: ExternalMetric | null; onDone: () => void }) {
    const create = useCreateExternalMetric();
    const update = useUpdateExternalMetric();
    const [serverError, setServerError] = useState<string | null>(null);

    const {register, handleSubmit, watch, formState: {errors}} = useForm<MetricFormValues>({
        resolver: zodResolver(metricSchema),
        defaultValues: {
            name: existing?.name ?? '',
            code: existing?.code ?? '',
            description: existing?.description ?? '',
            unit: existing?.unit ?? '',
            granularity: existing?.granularity ?? 'geography_node',
            period_grain: existing?.period_grain ?? 'monthly',
            default_aggregation: existing?.default_aggregation ?? 'sum',
        },
    });
    const granularity = watch('granularity');

    const onSubmit = handleSubmit((values) => {
        setServerError(null);
        const payload: ExternalMetricPayload = {...values, name: values.name.trim(), code: values.code.trim()};
        const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save metric'));
        if (existing) {
            update.mutate({id: existing.id, payload}, {
                onSuccess: () => {
                    notify.success('Metric updated');
                    onDone();
                },
                onError,
            });
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('Metric created');
                    onDone();
                },
                onError,
            });
        }
    });

    return (
        <form onSubmit={onSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" {...register('name')} error={errors.name?.message}
                       placeholder="e.g. Productive Calls"/>
                <Input label="Code" {...register('code')} error={errors.code?.message} disabled={!!existing}
                       hint={existing ? 'Code cannot be changed.' : 'Referenced by KPIs and push payloads.'}
                       placeholder="PRODUCTIVE_CALLS"/>
                <Select label="Attached to" {...register('granularity')}
                        options={[
                            {value: 'geography_node', label: 'Territory (rolls up the geography, like sales)'},
                            {value: 'entity', label: 'Person (individual score, never rolled up)'},
                        ]}/>
                <Select label="Grain" {...register('period_grain')}
                        options={[
                            {value: 'daily', label: 'Daily'},
                            {value: 'monthly', label: 'Monthly (dates normalise to month start)'},
                        ]}/>
                <Select label="Default aggregation" {...register('default_aggregation')}
                        options={[
                            {value: 'sum', label: 'Sum'},
                            {value: 'avg', label: 'Average'},
                            {value: 'latest', label: 'Latest value'},
                            {value: 'max', label: 'Maximum'},
                        ]}/>
                <Input label="Unit" {...register('unit')} placeholder="e.g. calls, %, lines"/>
            </div>
            {granularity === 'entity' && (
                <p className="rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-dark">
                    Person-grain scores (RCPA %, iQuest) stay personal — a manager never sees a rolled-up
                    average of the team's scores.
                </p>
            )}
            <Input label="Description" {...register('description')} placeholder="Optional"/>
            {existing && (
                <p className="text-xs text-gray-500">
                    Attached-to and grain are frozen once values exist for this metric.
                </p>
            )}
            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button type="submit" loading={create.isPending || update.isPending}>
                    {existing ? 'Save changes' : 'Create metric'}
                </Button>
            </div>
        </form>
    );
}

const CSV_HEADER = 'metric_code,measured_on,value,entity_id,node_id,source,external_ref';

function MetricValueImport({onClose}: { onClose: () => void }) {
    const qc = useQueryClient();
    const [csvText, setCsvText] = useState('');
    const [fileName, setFileName] = useState('');
    const [jobId, setJobId] = useState<number | null>(null);
    const [submitting, setSubmitting] = useState(false);

    function onFile(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        setFileName(file.name);
        const reader = new FileReader();
        reader.onload = () => setCsvText(String(reader.result ?? ''));
        reader.readAsText(file);
    }

    async function confirmImport() {
        setSubmitting(true);
        try {
            const job = await kpiService.bulkImportMetricValues(csvText);
            setJobId(job.id);
        } catch (e) {
            notify.error(apiErrorMessage(e, 'We couldn’t start the upload. Please check the file and try again.'));
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="space-y-4">
            <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                Upload a CSV with these columns. Fill <code>entity_id</code> for person-grain metrics or{' '}
                <code>node_id</code> for territory-grain — never both. Re-uploading the same file refreshes
                rows, never duplicates.
                <code className="mt-1 block overflow-x-auto rounded bg-white px-2 py-1 text-[11px] text-gray-700">{CSV_HEADER}</code>
            </div>
            {jobId === null ? (
                <>
                    <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 py-6 text-sm text-gray-500 hover:border-primary hover:text-primary">
                        <Upload className="h-4 w-4"/>
                        {fileName || 'Choose a file from your computer…'}
                        <input type="file" accept=".csv,text/csv" className="hidden" onChange={onFile}/>
                    </label>
                    <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                        <Button onClick={confirmImport} loading={submitting} disabled={!csvText.trim()}>Upload</Button>
                    </div>
                </>
            ) : (
                <>
                    <BulkJobProgress jobId={jobId}
                                     onDone={() => void qc.invalidateQueries({queryKey: ['kpi', 'metric-values']})}/>
                    <div className="flex justify-end border-t border-gray-100 pt-4">
                        <Button onClick={onClose}>Done</Button>
                    </div>
                </>
            )}
        </div>
    );
}

function ValuesBrowser({metric}: { metric: ExternalMetric }) {
    const [page, setPage] = useState(1);
    const {data, isLoading} = useMetricValues({metric: metric.code, page});
    const rows = data?.results ?? [];
    const count = data?.count ?? 0;

    if (isLoading) return <div className="flex justify-center py-10"><Spinner/></div>;
    if (rows.length === 0) {
        return <EmptyState icon={Radio} title="No values yet"
                           description="Values arrive via the push API or the CSV import on this page."/>;
    }
    return (
        <div className="space-y-3">
            <SimpleTable
                rows={rows}
                rowKey={(v) => v.id}
                columns={[
                    {header: 'Date', render: (v) => <span className="text-gray-700">{v.measured_on}</span>},
                    {header: metric.granularity === 'entity' ? 'Entity' : 'Node',
                     render: (v) => <span className="text-gray-700">#{v.entity ?? v.node_id}</span>},
                    {header: 'Value', align: 'right', render: (v) => (
                        <span className="font-medium text-gray-900">{v.value}</span>
                    )},
                    {header: 'Source', render: (v) => <span className="text-gray-500">{v.source || '—'}</span>},
                    {header: 'Ref', render: (v) => <span className="text-gray-500">{v.external_ref || '—'}</span>},
                ]}
            />
            <Pagination count={count} page={page} onPageChange={setPage}/>
        </div>
    );
}
