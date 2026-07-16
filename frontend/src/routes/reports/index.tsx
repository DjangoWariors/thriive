import {useMemo, useState} from 'react';
import {BarChart3, Download, FileText, Lock, Play} from 'lucide-react';
import {useGenerateReport, useReportDefinitions, useReportExecutions} from '../../hooks/useReports';
import {reportService} from '../../services/reportService';
import {useRBAC} from '../../hooks/useRBAC';
import type {
    GenerateReportPayload,
    ReportCategory,
    ReportDefinition,
    ReportFormat,
} from '../../types/reports';
import {Card} from '../../components/ui/Card';
import {Button} from '../../components/ui/Button';
import {Select} from '../../components/ui/Select';
import {StatusBadge} from '../../components/ui/StatusBadge';
import {Spinner} from '../../components/ui/Spinner';
import {EmptyState} from '../../components/ui/EmptyState';
import {Pagination} from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import {Tabs} from '../../components/ui/Tabs';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {cn} from '../../utils/cn';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {formatRelative} from '../../utils/format';
import {ParamField, buildParameters} from './ParamField';
import {SchedulesSection} from './SchedulesSection';

// No 'coverage' entry: it is a valid backend category but no seeded report uses it;
// unknown categories fall back to their raw code below.
const CATEGORY_LABELS: Partial<Record<ReportCategory, string>> = {
    sales: 'Sales & Distribution',
    targets: 'Targets & Achievement',
    incentive: 'Incentive & Payout',
    compliance: 'Compliance',
    master: 'Master & Audit',
};

export default function ReportsPage() {
    const {data: definitions, isLoading} = useReportDefinitions();
    const [selectedCode, setSelectedCode] = useState<string | null>(null);
    const [tab, setTab] = useState<'generate' | 'schedules'>('generate');
    const {can} = useRBAC();

    const selected = definitions?.find((d) => d.code === selectedCode) ?? null;

    const grouped = useMemo(() => {
        const map = new Map<ReportCategory, ReportDefinition[]>();
        for (const def of definitions ?? []) {
            const list = map.get(def.category) ?? [];
            list.push(def);
            map.set(def.category, list);
        }
        return Array.from(map.entries());
    }, [definitions]);

    const canSchedule = can('report_schedule');

    return (
        <div className="p-6">
            <PageHeader
                title="Reports"
                description="Generate and download reports. Each report runs in your access scope."
            />

            {canSchedule && (
                <Tabs
                    className="mb-4"
                    activeTab={tab}
                    onChange={(v) => setTab(v as 'generate' | 'schedules')}
                    tabs={[
                        {value: 'generate', label: 'Generate'},
                        {value: 'schedules', label: 'Schedules'},
                    ]}
                />
            )}

            {tab === 'schedules' && canSchedule ? (
                <SchedulesSection definitions={definitions ?? []}/>
            ) : isLoading ? (
                <TableSkeleton/>
            ) : (definitions?.length ?? 0) === 0 ? (
                <Card>
                    <EmptyState icon={BarChart3} title="No reports available"
                                description="You don't have permission to run any reports yet."/>
                </Card>
            ) : (
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                    {/* Left: report catalog */}
                    <div className="space-y-5 lg:col-span-2">
                        {grouped.map(([category, defs]) => (
                            <div key={category}>
                                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                                    {CATEGORY_LABELS[category] ?? category}
                                </h2>
                                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                    {defs.map((def) => (
                                        <button
                                            key={def.code}
                                            type="button"
                                            onClick={() => setSelectedCode(def.code)}
                                            className={cn(
                                                'rounded-xl border bg-white p-4 text-left transition-colors',
                                                def.code === selectedCode
                                                    ? 'border-primary ring-1 ring-primary/20'
                                                    : 'border-gray-200 hover:border-primary/40',
                                            )}
                                        >
                                            <div className="flex items-center gap-2">
                                                <FileText className="h-4 w-4 text-primary"/>
                                                <span className="font-medium text-gray-900">{def.name}</span>
                                                {def.is_confidential && (
                                                    <Lock className="h-3.5 w-3.5 text-amber-500"/>
                                                )}
                                            </div>
                                            <p className="mt-1 text-xs text-gray-500">{def.description}</p>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Right: parameter form */}
                    <div className="lg:col-span-1">
                        {selected ? (
                            <GenerateForm key={selected.code} definition={selected}/>
                        ) : (
                            <Card>
                                <EmptyState icon={Play} title="Select a report"
                                            description="Pick a report on the left to configure and generate it."/>
                            </Card>
                        )}
                    </div>
                </div>
            )}

            {tab === 'generate' && (
                <div className="mt-8">
                    <h2 className="mb-3 text-sm font-semibold text-gray-700">Recent reports</h2>
                    <RecentExecutions/>
                </div>
            )}
        </div>
    );
}


function GenerateForm({definition}: { definition: ReportDefinition }) {
    const [values, setValues] = useState<Record<string, string>>({});
    const [format, setFormat] = useState<ReportFormat>(definition.default_formats[0] ?? 'xlsx');
    const generate = useGenerateReport();

    const missingRequired = definition.param_schema.some(
        (f) => f.required && !String(values[f.key] ?? '').trim(),
    );

    const onChange = (key: string, value: string) =>
        setValues((prev) => ({...prev, [key]: value}));

    const onGenerate = () => {
        const parameters = buildParameters(definition.param_schema, values);
        const payload: GenerateReportPayload = {code: definition.code, parameters, format};
        generate.mutate(payload, {
            onSuccess: () => notify.success('Report queued — it will appear below when ready.'),
            onError: (e) => notify.error(apiErrorMessage(e, 'Could not start report')),
        });
    };

    const formatOptions = definition.default_formats.map((f) => ({value: f, label: f.toUpperCase()}));

    return (
        <Card title={definition.name} subtitle={definition.description}>
            <div className="space-y-4">
                {definition.is_confidential && (
                    <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0"/>
                        <span>Confidential report — every run and download is recorded in the access log.</span>
                    </div>
                )}

                {definition.param_schema.length === 0 && (
                    <p className="text-sm text-gray-400">This report has no parameters.</p>
                )}

                {definition.param_schema.map((field) => (
                    <ParamField
                        key={field.key}
                        field={field}
                        value={values[field.key] ?? ''}
                        onChange={(v) => onChange(field.key, v)}
                    />
                ))}

                <Select
                    label="Format"
                    options={formatOptions}
                    value={format}
                    onChange={(e) => setFormat(e.target.value as ReportFormat)}
                />

                <Button
                    fullWidth
                    onClick={onGenerate}
                    loading={generate.isPending}
                    disabled={missingRequired}
                    icon={<Play className="h-4 w-4"/>}
                >
                    Generate report
                </Button>
            </div>
        </Card>
    );
}


function RecentExecutions() {
    const [page, setPage] = useState(1);
    const {data, isLoading} = useReportExecutions({page});
    const [downloadingId, setDownloadingId] = useState<number | null>(null);
    const rows = data?.results ?? [];

    const handleDownload = async (id: number, name: string, format: string) => {
        setDownloadingId(id);
        try {
            const blob = await reportService.download(id);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${name.replace(/\s+/g, '_').toLowerCase()}.${format}`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            notify.error(apiErrorMessage(e, 'Could not download report'));
        } finally {
            setDownloadingId(null);
        }
    };

    if (isLoading) {
        return <div className="flex justify-center py-12"><Spinner/></div>;
    }
    if (rows.length === 0) {
        return (
            <Card>
                <EmptyState icon={Download} title="No reports generated yet"
                            description="Generated reports show up here, ready to download."/>
            </Card>
        );
    }

    return (
        <Card padding="none">
            <SimpleTable
                rows={rows}
                rowKey={(exec) => exec.id}
                columns={[
                    {header: 'Report', render: (exec) => (
                        <span className="font-medium text-gray-900">{exec.definition_name}</span>
                    )},
                    {header: 'Format', render: (exec) => <span className="uppercase text-gray-600">{exec.format}</span>},
                    {header: 'Rows', render: (exec) => (
                        <span className="text-gray-600">{exec.status === 'completed' ? exec.row_count : '—'}</span>
                    )},
                    {header: 'Status', render: (exec) => (
                        exec.status === 'failed' ? (
                            <span title={exec.error}><StatusBadge status={exec.status}/></span>
                        ) : (
                            <StatusBadge status={exec.status}/>
                        )
                    )},
                    {header: 'Requested', render: (exec) => (
                        <span className="text-gray-600">{formatRelative(exec.created_at)}</span>
                    )},
                    {header: 'Action', align: 'right', render: (exec) => (
                        exec.status === 'completed' ? (
                            <Button
                                size="sm"
                                variant="outline"
                                loading={downloadingId === exec.id}
                                onClick={() => handleDownload(exec.id, exec.definition_name, exec.format)}
                                icon={<Download className="h-4 w-4"/>}
                            >
                                Download
                            </Button>
                        ) : !exec.is_terminal ? (
                            <span className="text-xs text-gray-400">Generating…</span>
                        ) : (
                            <span className="text-xs text-gray-400">—</span>
                        )
                    )},
                ]}
            />
            <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage}/>
        </Card>
    );
}
