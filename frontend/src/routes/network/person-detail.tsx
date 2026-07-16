import {useMemo, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router';
import {type ColumnDef} from '@tanstack/react-table';
import {ArrowLeft, ArrowRightLeft, Edit2, GitBranch, Users} from 'lucide-react';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Button} from '../../components/ui/Button';
import {StatusBadge} from '../../components/ui/StatusBadge';
import {CardGridSkeleton} from '../../components/ui/Skeleton';
import {EmptyState} from '../../components/ui/EmptyState';
import {Breadcrumb} from '../../components/ui/Breadcrumb';
import {DataTable} from '../../components/data/DataTable';
import {EntityForm} from '../../components/entity/EntityForm';
import {TransferDialog} from '../../components/entity/TransferDialog';
import {useEntity, useEntitySubtree} from '../../hooks/useEntities';
import {useRBAC} from '../../hooks/useRBAC';
import type {EntitySubtreeItem} from '../../types/entity';

function BackLink() {
    return (
        <Link
            to="/network/people"
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-primary"
        >
            <ArrowLeft className="h-4 w-4"/>
            Back to People & Partners
        </Link>
    );
}

const columns: ColumnDef<EntitySubtreeItem, unknown>[] = [
    {
        accessorKey: 'name',
        header: 'Name',
        cell: ({row}) => (
            <Link
                to={`/network/people/${row.original.id}`}
                className="font-medium text-gray-900 hover:text-primary hover:underline"
            >
                {row.original.name}
            </Link>
        ),
    },
    {
        accessorKey: 'entity_type_name',
        header: 'Type',
        cell: ({getValue}) => (getValue() as string | null) ?? '—',
    },
    {
        id: 'email',
        header: 'Email',
        accessorFn: (row) => row.linked_user?.email ?? '',
        cell: ({row}) => row.original.linked_user?.email ?? '—',
    },
    {
        id: 'mobile',
        header: 'Mobile',
        accessorFn: (row) => row.linked_user?.mobile ?? '',
        cell: ({row}) => row.original.linked_user?.mobile ?? '—',
    },
    {
        accessorKey: 'status',
        header: 'Status',
        cell: ({row}) => <StatusBadge status={row.original.status}/>,
    },
    {
        id: 'channel',
        header: 'Channel',
        accessorFn: (row) => row.channel?.name ?? '',
        cell: ({row}) => row.original.channel?.name ?? '—',
    },
];

export default function EntityDetailPage() {
    const {id} = useParams();
    const navigate = useNavigate();
    const entityId = Number(id);
    const valid = Number.isFinite(entityId) && entityId > 0;

    const [showEdit, setShowEdit] = useState(false);
    const [showTransfer, setShowTransfer] = useState(false);
    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const {data: entity, isLoading} = useEntity(valid ? entityId : 0);
    const {data: subtree, isLoading: subtreeLoading} = useEntitySubtree(valid ? entityId : 0);

    const rows = useMemo(() => subtree?.results ?? [], [subtree]);
    const totalRows = subtree?.count ?? 0;
    const truncated = totalRows > rows.length;

    if (!valid) {
        return (
            <div className="mx-auto max-w-5xl space-y-4 p-6">
                <BackLink/>
                <div className="flex h-96 items-center justify-center">
                    <EmptyState
                        icon={GitBranch}
                        title="Invalid entity"
                        description="The entity ID in the URL is not valid."
                    />
                </div>
            </div>
        );
    }

    if (isLoading) {
        return <div className="p-6"><CardGridSkeleton/></div>;
    }

    if (!entity) {
        return (
            <div className="mx-auto max-w-5xl space-y-4 p-6">
                <BackLink/>
                <div className="flex h-96 items-center justify-center text-sm text-gray-400">
                    Entity not found.
                </div>
            </div>
        );
    }

    const etColor = entity.entity_type.display_config.color ?? '#6B7280';

    return (
        <div className="mx-auto max-w-5xl space-y-4 p-6">
            <Breadcrumb
                items={[
                    {label: 'People & Partners', onClick: () => navigate('/network/people')},
                    {label: entity.name},
                ]}
            />

            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="h-3 w-3 shrink-0 rounded-full" style={{background: etColor}}/>
                        <h1 className="truncate text-xl font-semibold text-gray-900">{entity.name}</h1>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <Badge variant="info">{entity.entity_type.name}</Badge>
                        <StatusBadge status={entity.status}/>
                        {entity.channel !== null && <Badge variant="default">{entity.channel.name}</Badge>}
                        {entity.display_code && entity.display_code !== entity.code && (
                            <span className="font-mono text-xs font-medium text-gray-600">{entity.display_code}</span>
                        )}
                        <span className="font-mono text-xs text-gray-500">{entity.code}</span>
                    </div>
                </div>

                {writable && (
                    <div className="flex shrink-0 items-center gap-2">
                        <Button size="sm" variant="outline" icon={<Edit2 className="h-3.5 w-3.5"/>}
                                onClick={() => setShowEdit(true)}>
                            Edit
                        </Button>
                        <Button size="sm" variant="outline" icon={<ArrowRightLeft className="h-3.5 w-3.5"/>}
                                onClick={() => setShowTransfer(true)}>
                            Transfer
                        </Button>
                    </div>
                )}
            </div>

            <Card
                title="Related Users"
                padding="sm"
                actions={
                    <span className="inline-flex items-center gap-1.5 text-xs text-gray-400">
                        <Users className="h-3.5 w-3.5"/>
                        {totalRows} under this entity
                    </span>
                }
            >
                <DataTable
                    columns={columns}
                    data={rows}
                    isLoading={subtreeLoading}
                    searchPlaceholder="Search team…"
                    emptyTitle="No related users"
                    emptyDescription="This entity has no descendants in the hierarchy."
                />
                {truncated && (
                    <p className="pt-3 text-center text-xs text-gray-400">
                        Showing the first {rows.length} of {totalRows} descendants. Use the
                        Entity Browser to explore the full team.
                    </p>
                )}
            </Card>

            {showEdit && <EntityForm entity={entity} onClose={() => setShowEdit(false)}/>}
            {showTransfer && <TransferDialog entity={entity} onClose={() => setShowTransfer(false)}/>}
        </div>
    );
}
