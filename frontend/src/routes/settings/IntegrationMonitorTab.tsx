import {useState} from 'react';
import {ChevronDown, ChevronRight, Copy, PlugZap} from 'lucide-react';
import {useIntegrationBatches} from '../../hooks/useKpi';
import type {IntegrationBatch, IntegrationBatchListParams} from '../../types/kpi';
import {Button} from '../../components/ui/Button';
import {Pagination} from '../../components/ui/Pagination';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {StatusBadge} from '../../components/ui/StatusBadge';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {notify} from '../../utils/notify';
import {formatRelative} from '../../utils/format';

export function IntegrationMonitorTab() {
    const [filters, setFilters] = useState<IntegrationBatchListParams>({});
    const [page, setPage] = useState(1);
    const [openId, setOpenId] = useState<number | null>(null);

    const {data, isLoading} = useIntegrationBatches({...filters, page});
    const batches = data?.results ?? [];

    const setFilter = (patch: IntegrationBatchListParams) => {
        setFilters((f) => ({...f, ...patch}));
        setPage(1);
    };

    return (
        <>
            <p className="mb-3 text-sm text-gray-500">
                Every inbound push from DMS / SFA / agency systems — received, accepted and rejected row
                counts, with the failed payloads kept for reconciliation.
            </p>

            <HowThisWorks storageKey="integration-monitor-help" className="mb-6">
                External systems push transactions and metric values in batches. Valid rows land immediately;
                invalid rows come back — and are stored here — with the reason each one failed. Because ingestion
                is idempotent, the source system simply fixes the failed rows and pushes them again: nothing is
                ever duplicated. Use “Copy failed rows” to hand the payload back to the integration team.
            </HowThisWorks>

            <div className="mb-4 flex flex-wrap gap-3">
                <div className="w-44">
                    <Select label="Kind" value={filters.batch_kind ?? ''}
                            onChange={(e) => setFilter({batch_kind: (e.target.value || undefined) as IntegrationBatchListParams['batch_kind']})}
                            options={[
                                {value: '', label: 'All kinds'},
                                {value: 'transactions', label: 'Transactions'},
                                {value: 'metric_values', label: 'Metric values'},
                            ]}/>
                </div>
                <div className="w-44">
                    <Select label="Status" value={filters.status ?? ''}
                            onChange={(e) => setFilter({status: (e.target.value || undefined) as IntegrationBatchListParams['status']})}
                            options={[
                                {value: '', label: 'All statuses'},
                                {value: 'accepted', label: 'Accepted'},
                                {value: 'partial', label: 'Partial'},
                                {value: 'rejected', label: 'Rejected'},
                            ]}/>
                </div>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : batches.length === 0 ? (
                <Card>
                    <EmptyState icon={PlugZap} title="No integration batches yet"
                                description="Batches appear here as soon as an external system pushes data."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={batches}
                        rowKey={(b) => b.id}
                        onRowClick={(b) => setOpenId(openId === b.id ? null : b.id)}
                        expandedRow={(b) =>
                            openId === b.id && b.rejected_count > 0 ? <BatchErrors batch={b}/> : null
                        }
                        columns={[
                            {header: '', className: 'w-8', render: (b) => (
                                b.rejected_count > 0 ? (
                                    <span className="text-gray-400" aria-expanded={openId === b.id}>
                                        {openId === b.id ? <ChevronDown className="h-4 w-4"/> : <ChevronRight className="h-4 w-4"/>}
                                    </span>
                                ) : null
                            )},
                            {header: 'When', render: (b) => <span className="text-gray-700">{formatRelative(b.created_at)}</span>},
                            {header: 'Kind', render: (b) => (
                                <span className="text-gray-600">{b.batch_kind === 'transactions' ? 'Transactions' : 'Metric values'}</span>
                            )},
                            {header: 'Source', render: (b) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{b.source}</code>
                            )},
                            {header: 'Batch ref', render: (b) => <span className="text-gray-500">{b.client_batch_ref || '—'}</span>},
                            {header: 'Status', render: (b) => <StatusBadge status={b.status}/>},
                            {header: 'Received', align: 'right', render: (b) => <span className="text-gray-700">{b.received_count}</span>},
                            {header: 'Accepted', align: 'right', render: (b) => <span className="text-success">{b.accepted_count}</span>},
                            {header: 'Rejected', align: 'right', render: (b) => <span className="text-danger">{b.rejected_count}</span>},
                            {header: 'Pushed by', render: (b) => <span className="text-gray-500">{b.pushed_by_display || '—'}</span>},
                        ]}
                    />
                </Card>
            )}

            <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage} className="mt-2"/>
        </>
    );
}

function BatchErrors({batch}: { batch: IntegrationBatch }) {
    const copyFailedRows = () => {
        const rows = batch.row_errors.map((e) => e.row);
        void navigator.clipboard.writeText(JSON.stringify(rows, null, 2)).then(
            () => notify.success(`${rows.length} failed row${rows.length === 1 ? '' : 's'} copied as JSON`),
            () => notify.error('Could not copy to clipboard'),
        );
    };

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                    Rejected rows ({batch.rejected_count})
                </p>
                <Button variant="outline" size="sm" icon={<Copy className="h-3.5 w-3.5"/>} onClick={copyFailedRows}>
                    Copy failed rows
                </Button>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border border-gray-200 bg-white">
                <SimpleTable
                    className="text-xs"
                    rows={batch.row_errors}
                    rowKey={(e) => e.index}
                    columns={[
                        {header: 'Row', render: (e) => <span className="text-gray-500">#{e.index}</span>},
                        {header: 'External ref', render: (e) => <span className="text-gray-500">{e.external_ref || '—'}</span>},
                        {header: 'Errors', render: (e) => <span className="text-danger">{e.errors.join('; ')}</span>},
                    ]}
                />
            </div>
            <p className="text-[11px] text-gray-400">
                Fix these rows at the source and push them again — ingestion is idempotent, so re-pushing never
                duplicates the rows that already landed.
            </p>
        </div>
    );
}
