import {useState} from 'react';
import {ArrowRightLeft, MapPin, Plus, Search, X} from 'lucide-react';
import {useAssignments, useEndAssignment} from '../../hooks/useAssignments';
import {useGeographyTypes} from '../../hooks/useEntities';
import {useRBAC} from '../../hooks/useRBAC';
import {AssignDialog} from '../../components/assignments/AssignDialog';
import {TerritoryTransferDialog} from '../../components/assignments/TerritoryTransferDialog';
import {PageHeader} from '../../components/ui/PageHeader';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {InfoTooltip} from '../../components/ui/InfoTooltip';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {EmptyState} from '../../components/ui/EmptyState';
import {Pagination} from '../../components/ui/Pagination';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import type {Assignment, AssignmentRole} from '../../types/assignment';
import {TERRITORY_ROLES_ENABLED} from '../../config/features';

const TODAY = new Date().toISOString().slice(0, 10);
const PAGE_SIZE = 50;

export default function OwnersPage() {
    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const [openOnly, setOpenOnly] = useState(true);
    const [q, setQ] = useState('');
    const [role, setRole] = useState<'' | AssignmentRole>('');
    const [page, setPage] = useState(1);

    const {data, isLoading} = useAssignments({
        ...(openOnly ? {open: true} : {}),
        ...(q.trim() ? {q: q.trim()} : {}),
        ...(role ? {role} : {}),
        page,
        page_size: PAGE_SIZE,
    });
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;

    const {data: geoTypesResp} = useGeographyTypes();
    const geoTypeCode = geoTypesResp?.results?.[0]?.code ?? '';

    const [assignOpen, setAssignOpen] = useState(false);
    const [transferOpen, setTransferOpen] = useState(false);

    const endMutation = useEndAssignment();
    const endAssignment = (a: Assignment) => {
        endMutation.mutate(
            {id: a.id, payload: {effective_to: TODAY, reason: 'Ended from the app'}},
            {
                onSuccess: () => notify.success("That's wrapped up — they're no longer in charge of it."),
                onError: (err) => notify.error(apiErrorMessage(err, "Sorry, we couldn't wrap that up")),
            },
        );
    };

    const setFilter = (apply: () => void) => {
        apply();
        setPage(1);
    };

    return (
        <div className="space-y-6 p-6">
            <PageHeader
                title="Territory Owners"
                description="The full record of who looks after which place, and since when. Everyday changes are one click away on a person's card or a territory's panel — this register is where you see (and audit) all of it."
                actions={
                    writable ? (
                        <div className="flex gap-2">
                            <Button variant="secondary" onClick={() => setTransferOpen(true)}>
                                <ArrowRightLeft className="h-4 w-4"/> Transfer territory
                            </Button>
                            <Button onClick={() => setAssignOpen(true)}>
                                <Plus className="h-4 w-4"/> New assignment
                            </Button>
                        </div>
                    ) : undefined
                }
            />

            <HowThisWorks storageKey="assignments-help">
                This is what connects your <strong>People &amp; Partners</strong> to your{' '}
                <strong>Territories</strong>. Every row simply says one person has looked after one place
                since a certain date. Since the sales belong to the place, the new owner picks up right
                where the last one left off — nothing gets moved or lost. Untick <em>only active</em> to
                see the whole history, including past owners.
            </HowThisWorks>

            <div className="flex flex-wrap items-end gap-3">
                <div className="w-64">
                    <Input
                        label="Search"
                        placeholder="Person or territory…"
                        value={q}
                        onChange={(e) => setFilter(() => setQ(e.target.value))}
                        leftIcon={<Search className="h-4 w-4"/>}
                    />
                </div>
                {TERRITORY_ROLES_ENABLED && (
                    <div className="w-56">
                        <Select
                            label="Role in territory"
                            value={role}
                            onChange={(e) => setFilter(() => setRole(e.target.value as '' | AssignmentRole))}
                            options={[
                                {value: '', label: 'All roles'},
                                {value: 'owner', label: 'Owner — credited with sales'},
                                {value: 'stand_in', label: 'Stand-in — temporary cover'},
                                {value: 'supervisor', label: 'Supervisor — oversight only'},
                            ]}
                        />
                    </div>
                )}
                <label className="flex items-center gap-2 pb-2 text-sm">
                    <input
                        type="checkbox"
                        checked={openOnly}
                        onChange={(e) => setFilter(() => setOpenOnly(e.target.checked))}
                    />
                    Only show the ones still active
                </label>
                {total > 0 && (
                    <span className="pb-2 text-xs text-gray-400">{total.toLocaleString()} record{total === 1 ? '' : 's'}</span>
                )}
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : rows.length === 0 ? (
                <EmptyState
                    icon={MapPin}
                    title={q || role || !openOnly ? 'Nothing matches those filters' : "Nobody's been given a territory yet"}
                    description={q || role || !openOnly
                        ? 'Try widening the search or clearing the filters.'
                        : 'Put someone in charge of a place, and its sales will start landing with them.'}
                />
            ) : (
                <Card className="overflow-hidden p-0">
                    <SimpleTable
                        rows={rows}
                        rowKey={(a) => a.id}
                        columns={[
                            {header: 'Person', render: (a) => (
                                <>
                                    <div className="font-medium">{a.assignee.name}</div>
                                    <div className="text-xs text-gray-500">{a.assignee.code}</div>
                                </>
                            )},
                            {header: 'Territory', render: (a) => (
                                <>
                                    <div className="font-medium">{a.scope.name}</div>
                                    <div className="text-xs text-gray-500">{a.scope.code} · {a.scope.level}</div>
                                </>
                            )},
                            ...(TERRITORY_ROLES_ENABLED ? [{header: (
                                <span className="inline-flex items-center gap-1">
                                    Role
                                    <InfoTooltip content="Owner = the person credited with the territory's sales. Stand-in = a temporary fill-in. Supervisor = oversees but isn't credited."/>
                                </span>
                            ), render: (a: Assignment) => <Badge>{a.role_in_scope.replace('_', '-')}</Badge>}] : []),
                            {header: 'From', render: (a) => <>{a.effective_from}</>},
                            {header: 'To', render: (a) => (
                                <>{a.effective_to ?? <span className="text-green-600">still going</span>}</>
                            )},
                            ...(writable ? [{
                                header: '', align: 'right' as const,
                                render: (a: Assignment) => (
                                    a.effective_to === null ? (
                                        <Button variant="ghost" size="sm" aria-label={`End assignment for ${a.assignee.name}`}
                                                onClick={() => endAssignment(a)} disabled={endMutation.isPending}>
                                            <X className="h-4 w-4"/> End
                                        </Button>
                                    ) : null
                                ),
                            }] : []),
                        ]}
                    />
                    <Pagination
                        page={page}
                        pageSize={PAGE_SIZE}
                        count={total}
                        onPageChange={setPage}
                    />
                </Card>
            )}

            {assignOpen && (
                <AssignDialog geoTypeCode={geoTypeCode} onClose={() => setAssignOpen(false)}/>
            )}
            {transferOpen && (
                <TerritoryTransferDialog geoTypeCode={geoTypeCode} onClose={() => setTransferOpen(false)}/>
            )}
        </div>
    );
}
