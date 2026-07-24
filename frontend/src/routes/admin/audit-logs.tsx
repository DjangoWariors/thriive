import {useState} from 'react';
import {ChevronDown, ChevronRight, Eye, FileText, Search, ShieldCheck} from 'lucide-react';
import {useAccessLogs, useAuditLogs, useComputationLogs, useVerifyChain} from '../../hooks/useAudit';
import {useRBAC} from '../../hooks/useRBAC';
import type {AuditLogEntry, ComputationLogEntry} from '../../types/audit';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Avatar} from '../../components/ui/Avatar';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {Tabs} from '../../components/ui/Tabs';
import {EmptyState} from '../../components/ui/EmptyState';
import {Pagination} from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {formatRelative} from '../../utils/format';
import {notify} from '../../utils/notify';

type TabValue = 'audit' | 'computation' | 'access';

const ACTION_OPTIONS = [
    {value: '', label: 'All actions'},
    {value: 'create', label: 'Create'},
    {value: 'update', label: 'Update'},
    {value: 'move', label: 'Move / Transfer'},
    {value: 'deactivate', label: 'Deactivate'},
    {value: 'reactivate', label: 'Reactivate'},
    {value: 'approve', label: 'Approve'},
    {value: 'reject', label: 'Reject'},
    {value: 'login', label: 'Login'},
];

const ACTION_VARIANT: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'default' | 'purple'> = {
    create: 'success',
    update: 'info',
    move: 'warning',
    deactivate: 'danger',
    reactivate: 'success',
    approve: 'success',
    reject: 'danger',
    login: 'purple',
};

const COMP_TYPE_OPTIONS = [
    {value: '', label: 'All types'},
    {value: 'payout', label: 'Payout'},
    {value: 'achievement', label: 'Achievement'},
];

function fullTimestamp(value: string): string {
    return new Date(value).toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

/** Per-page expand state: SimpleTable columns must stay hook-free, so the open
 * set lives on the tab and rows just read it. */
function useOpenIds() {
    const [openIds, setOpenIds] = useState<Set<number>>(new Set());
    const toggle = (id: number) =>
        setOpenIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    return {openIds, toggle};
}

export default function AuditLogsPage() {
    const [tab, setTab] = useState<TabValue>('audit');
    const {can} = useRBAC();
    const verify = useVerifyChain();

    const onVerify = () =>
        verify.mutate(undefined, {
            onSuccess: (result) => {
                if (result.ok) {
                    notify.success(`Chain intact — ${result.checked} entries verified.`);
                } else {
                    notify.error(`Chain broken at entry #${result.broken_at}: ${result.reason}`);
                }
            },
            onError: () => notify.error('Chain verification failed.'),
        });

    return (
        <div className="p-6">
            <PageHeader
                title="Audit Trail"
                description="Immutable, hash-chained record of every mutation and computation."
                actions={
                    <Button variant="secondary" onClick={onVerify} loading={verify.isPending}
                            icon={<ShieldCheck className="h-4 w-4"/>}>
                        Verify chain integrity
                    </Button>
                }
            />

            <Tabs
                className="mb-4"
                activeTab={tab}
                onChange={(v) => setTab(v as TabValue)}
                tabs={[
                    {value: 'audit', label: 'Audit Logs'},
                    {value: 'computation', label: 'Computation Logs'},
                    ...(can('audit_access') ? [{value: 'access', label: 'Access Logs'}] : []),
                ]}
            />

            {tab === 'audit' && <AuditLogTab/>}
            {tab === 'computation' && <ComputationLogTab/>}
            {tab === 'access' && <AccessLogTab/>}
        </div>
    );
}


function hasChanges(row: AuditLogEntry): boolean {
    return row.changes != null && Object.keys(row.changes).length > 0;
}

function AuditLogTab() {
    const [page, setPage] = useState(1);
    const [action, setAction] = useState('');
    const [entityType, setEntityType] = useState('');
    const [q, setQ] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const {openIds, toggle} = useOpenIds();

    const onFilter = <T, >(setter: (v: T) => void) => (value: T) => {
        setter(value);
        setPage(1);
    };

    const params = {
        page,
        ...(action ? {action} : {}),
        ...(entityType ? {entity_type: entityType} : {}),
        ...(q ? {q} : {}),
        ...(dateFrom ? {date_from: dateFrom} : {}),
        ...(dateTo ? {date_to: dateTo} : {}),
    };
    const {data, isLoading} = useAuditLogs(params);
    const rows = data?.results ?? [];

    return (
        <>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Select options={ACTION_OPTIONS} value={action}
                        onChange={(e) => onFilter(setAction)(e.target.value)}/>
                <Input placeholder="Record type, e.g. hierarchy.Entity"
                       value={entityType} onChange={(e) => onFilter(setEntityType)(e.target.value)}/>
                <Input placeholder="Search changes…" leftIcon={<Search className="h-4 w-4"/>}
                       value={q} onChange={(e) => onFilter(setQ)(e.target.value)}/>
                <Input type="date" aria-label="From date" value={dateFrom}
                       onChange={(e) => onFilter(setDateFrom)(e.target.value)}/>
                <Input type="date" aria-label="To date" value={dateTo}
                       onChange={(e) => onFilter(setDateTo)(e.target.value)}/>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : rows.length === 0 ? (
                <Card>
                    <EmptyState icon={ShieldCheck} title="No audit entries"
                                description="Mutations will appear here as they happen."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={rows}
                        rowKey={(row) => row.id}
                        onRowClick={(row) => hasChanges(row) && toggle(row.id)}
                        expandedRow={(row) =>
                            openIds.has(row.id) && hasChanges(row)
                                ? <ChangesDiff changes={row.changes as Record<string, unknown>}/>
                                : null
                        }
                        columns={[
                            {header: '', className: 'w-8', render: (row) => (
                                hasChanges(row) ? (
                                    <span className="text-gray-400" aria-expanded={openIds.has(row.id)}>
                                        {openIds.has(row.id)
                                            ? <ChevronDown className="h-4 w-4"/>
                                            : <ChevronRight className="h-4 w-4"/>}
                                    </span>
                                ) : null
                            )},
                            {header: 'Timestamp', render: (row) => (
                                <span className="text-gray-600" title={fullTimestamp(row.timestamp)}>
                                    {formatRelative(row.timestamp)}
                                </span>
                            )},
                            {header: 'User', render: (row) => (
                                row.user_label ? (
                                    <div className="flex items-center gap-2">
                                        <Avatar name={row.user_label} size="sm"/>
                                        <span className="text-gray-900">{row.user_label}</span>
                                    </div>
                                ) : <span className="text-gray-400">System</span>
                            )},
                            {header: 'Action', render: (row) => (
                                <Badge variant={ACTION_VARIANT[row.action] ?? 'default'}>{row.action}</Badge>
                            )},
                            {header: 'Record Type', render: (row) => <span className="text-gray-600">{row.entity_type || '—'}</span>},
                            {header: 'Record ID', render: (row) => <span className="text-gray-600">{row.entity_id ?? '—'}</span>},
                        ]}
                    />
                    <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage}/>
                </Card>
            )}
        </>
    );
}


function ChangesDiff({changes}: { changes: Record<string, unknown> }) {
    const entries = Object.entries(changes).map(([field, value]) => ({field, ...splitChange(value)}));
    return (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <SimpleTable
                className="text-xs"
                rows={entries}
                rowKey={(e) => e.field}
                columns={[
                    {header: 'Field', render: (e) => <span className="font-medium text-gray-700">{e.field}</span>},
                    {header: 'Old Value', render: (e) => <span className="font-mono text-danger">{e.oldVal}</span>},
                    {header: 'New Value', render: (e) => <span className="font-mono text-success">{e.newVal}</span>},
                ]}
            />
        </div>
    );
}

/** Render a changes value as old → new, supporting {old,new}, {from,to}, [old,new], or a bare value. */
function splitChange(value: unknown): { oldVal: string; newVal: string } {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        const obj = value as Record<string, unknown>;
        if ('old' in obj || 'new' in obj) return {oldVal: fmt(obj.old), newVal: fmt(obj.new)};
        if ('from' in obj || 'to' in obj) return {oldVal: fmt(obj.from), newVal: fmt(obj.to)};
    }
    if (Array.isArray(value) && value.length === 2) {
        return {oldVal: fmt(value[0]), newVal: fmt(value[1])};
    }
    return {oldVal: '—', newVal: fmt(value)};
}

function fmt(value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}


function ComputationLogTab() {
    const [page, setPage] = useState(1);
    const [type, setType] = useState('');
    const {openIds, toggle} = useOpenIds();

    const onFilter = <T, >(setter: (v: T) => void) => (value: T) => {
        setter(value);
        setPage(1);
    };

    const params = {page, ...(type ? {computation_type: type} : {})};
    const {data, isLoading} = useComputationLogs(params);
    const rows = data?.results ?? [];

    return (
        <>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:max-w-xs">
                <Select options={COMP_TYPE_OPTIONS} value={type}
                        onChange={(e) => onFilter(setType)(e.target.value)}/>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : rows.length === 0 ? (
                <Card>
                    <EmptyState icon={FileText} title="No computation logs"
                                description="Payout and achievement runs record their config snapshot here."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={rows}
                        rowKey={(row) => row.id}
                        onRowClick={(row) => toggle(row.id)}
                        expandedRow={(row) =>
                            openIds.has(row.id) ? (
                                <div className="grid gap-3 sm:grid-cols-2">
                                    <JsonBlock title="Config snapshot" value={row.config_snapshot}/>
                                    <JsonBlock title="Result snapshot" value={row.result_snapshot}/>
                                </div>
                            ) : null
                        }
                        columns={[
                            {header: '', className: 'w-8', render: (row: ComputationLogEntry) => (
                                <span className="text-gray-400" aria-expanded={openIds.has(row.id)}>
                                    {openIds.has(row.id)
                                        ? <ChevronDown className="h-4 w-4"/>
                                        : <ChevronRight className="h-4 w-4"/>}
                                </span>
                            )},
                            {header: 'Timestamp', render: (row) => (
                                <span className="text-gray-600" title={fullTimestamp(row.timestamp)}>
                                    {formatRelative(row.timestamp)}
                                </span>
                            )},
                            {header: 'Type', render: (row) => <Badge variant="info">{row.computation_type}</Badge>},
                            // entity_id is 0, not null, for a period-wide computation.
                            {header: 'Entity', render: (row) => <span className="text-gray-600">{row.entity_label || (row.entity_id ? `#${row.entity_id}` : '—')}</span>},
                            {header: 'Period', render: (row) => <span className="text-gray-600">{row.period_label || (row.period_id ? `#${row.period_id}` : '—')}</span>},
                        ]}
                    />
                    <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage}/>
                </Card>
            )}
        </>
    );
}

function AccessLogTab() {
    const [page, setPage] = useState(1);
    const [resource, setResource] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');

    const onFilter = <T, >(setter: (v: T) => void) => (value: T) => {
        setter(value);
        setPage(1);
    };

    const params = {
        page,
        ...(resource ? {resource} : {}),
        ...(dateFrom ? {date_from: dateFrom} : {}),
        ...(dateTo ? {date_to: dateTo} : {}),
    };
    const {data, isLoading} = useAccessLogs(params);
    const rows = data?.results ?? [];

    return (
        <>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Input placeholder="Resource, e.g. payout" value={resource}
                       onChange={(e) => onFilter(setResource)(e.target.value)}/>
                <Input type="date" aria-label="From date" value={dateFrom}
                       onChange={(e) => onFilter(setDateFrom)(e.target.value)}/>
                <Input type="date" aria-label="To date" value={dateTo}
                       onChange={(e) => onFilter(setDateTo)(e.target.value)}/>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : rows.length === 0 ? (
                <Card>
                    <EmptyState icon={Eye} title="No access log entries"
                                description="Confidential reads (payouts, exports) are disclosed here."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={rows}
                        rowKey={(row) => row.id}
                        columns={[
                            {header: 'Timestamp', render: (row) => (
                                <span className="text-gray-600" title={fullTimestamp(row.timestamp)}>
                                    {formatRelative(row.timestamp)}
                                </span>
                            )},
                            {header: 'Accessed By', render: (row) => (
                                row.user_label ? (
                                    <div className="flex items-center gap-2">
                                        <Avatar name={row.user_label} size="sm"/>
                                        <span className="text-gray-900">{row.user_label}</span>
                                    </div>
                                ) : <span className="text-gray-400">System</span>
                            )},
                            {header: 'Resource', render: (row) => <Badge variant="purple">{row.resource}</Badge>},
                            {header: 'Action', render: (row) => <span className="text-gray-600">{row.action}</span>},
                            {header: 'Record ID', render: (row) => <span className="text-gray-600">{row.object_id ?? '—'}</span>},
                            {header: 'Subject Entity', render: (row) => <span className="text-gray-600">{row.subject_entity_id ?? '—'}</span>},
                            {header: 'IP', render: (row) => <span className="font-mono text-xs text-gray-500">{row.ip_address ?? '—'}</span>},
                        ]}
                    />
                    <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage}/>
                </Card>
            )}
        </>
    );
}

function JsonBlock({title, value}: { title: string; value: unknown }) {
    const empty = value == null || (typeof value === 'object' && Object.keys(value).length === 0);
    return (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 bg-gray-50 px-3 py-2 text-xs font-semibold uppercase text-gray-400">
                {title}
            </div>
            <pre className="max-h-64 overflow-auto p-3 text-xs text-gray-700">
                {empty ? '—' : JSON.stringify(value, null, 2)}
            </pre>
        </div>
    );
}
