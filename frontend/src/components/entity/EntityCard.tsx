import {useState} from 'react';
import {Link} from 'react-router';
import {Edit2, ArrowRightLeft, Repeat, Trash2, RotateCcw, User, MapPin, GitBranch, Link2, X} from 'lucide-react';
import {notify} from '../../utils/notify';
import {Card} from '../ui/Card';
import {Badge} from '../ui/Badge';
import {Button} from '../ui/Button';
import {Breadcrumb} from '../ui/Breadcrumb';
import {StatusBadge} from '../ui/StatusBadge';
import {Spinner} from '../ui/Spinner';
import {ConfirmDialog} from '../ui/ConfirmDialog';
import {EntityForm} from './EntityForm';
import {TransferDialog} from './TransferDialog';
import {ChangeTypeDialog} from './ChangeTypeDialog';
import {AssignDialog} from '../assignments/AssignDialog';
import {TerritoryTransferDialog} from '../assignments/TerritoryTransferDialog';
import type {EntitySelection} from './EntityCombobox';
import type {GeoSelection} from './GeoNodeCombobox';
import type {Assignment} from '../../types/assignment';
import {
    useEntity,
    useEntityChildren,
    useEntityRelationships,
    useEndRelationship,
    useDeactivateEntity,
    useReactivateEntity,
    useGeographyTypes,
} from '../../hooks/useEntities';
import {useAssignments, useEndAssignment} from '../../hooks/useAssignments';
import {useHierarchyStore} from '../../stores/hierarchyStore';
import {useRBAC} from '../../hooks/useRBAC';
import {CHANGE_ROLE_ENABLED, PERSON_TRANSFER_ENABLED} from '../../config/features';



function AttributesSection({entity}: { entity: NonNullable<ReturnType<typeof useEntity>['data']> }) {
    const schema = entity.entity_type.attribute_schema;
    if (schema.length === 0) {
        return <p className="text-sm text-gray-400">No extra details set up for this type.</p>;
    }
    return (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
            {schema.map((f) => {
                const val = entity.attributes[f.key];
                const display =
                    val === undefined || val === null ? '—' :
                        typeof val === 'boolean' ? (val ? 'Yes' : 'No') :
                            String(val);
                return (
                    <div key={f.key}>
                        <dt className="text-xs font-medium text-gray-500">{f.label}</dt>
                        <dd className="mt-0.5 text-sm text-gray-900 break-words">{display}</dd>
                    </div>
                );
            })}
        </dl>
    );
}



const ROLE_LABEL: Record<string, string> = {
    owner: 'Owner',
    stand_in: 'Stand-in',
    supervisor: 'Supervisor',
};

function TerritoriesOwned({assignee, writable, canOwn}: {
    assignee: EntitySelection;
    writable: boolean;
    canOwn: boolean;
}) {
    const {data} = useAssignments({assignee: assignee.id, open: true});
    const owned = data?.results ?? [];

    const {data: geoTypesResp} = useGeographyTypes();
    const geoTypeCode = geoTypesResp?.results?.[0]?.code ?? '';

    const [assignOpen, setAssignOpen] = useState(false);
    const [transferScope, setTransferScope] = useState<GeoSelection | null>(null);

    const endMutation = useEndAssignment();
    const endAssignment = (a: Assignment) => {
        endMutation.mutate(
            {
                id: a.id,
                payload: {effective_to: new Date().toISOString().slice(0, 10), reason: 'Ended from the app'},
            },
            {
                onSuccess: () => notify.success("That's wrapped up — they're no longer in charge of it."),
                onError: () => notify.error("Sorry, we couldn't wrap that up."),
            },
        );
    };

    // Hide the card when there's nothing useful to show: read-only viewers with no
    // assignments, or end-of-the-line partners (like retailers) who sit in a territory
    // but never look after one.
    if (owned.length === 0 && (!writable || !canOwn)) return null;

    return (
        <Card
            title="Territories owned"
            padding="sm"
            actions={
                writable && canOwn ? (
                    <Button size="sm" variant="ghost" icon={<MapPin className="h-3.5 w-3.5"/>}
                            onClick={() => setAssignOpen(true)}>
                        Assign territory
                    </Button>
                ) : undefined
            }
        >
            {owned.length === 0 ? (
                <p className="text-sm text-gray-400">
                    Nobody's been given a territory here yet. Assign one and its sales start landing here.
                </p>
            ) : (
                <>
                    <ul className="space-y-1.5">
                        {owned.map((a) => (
                            <li key={a.id} className="flex items-center gap-2 text-sm">
                                <MapPin className="h-4 w-4 shrink-0 text-gray-400"/>
                                <span className="font-medium text-gray-900">{a.scope.name}</span>
                                <Badge variant="default">{a.scope.level}</Badge>
                                {a.role_in_scope !== 'owner' && (
                                    <span className="text-xs text-gray-500">
                                        {ROLE_LABEL[a.role_in_scope] ?? a.role_in_scope}
                                    </span>
                                )}
                                <span className="ml-auto text-xs text-gray-400">since {a.effective_from}</span>
                                {writable && (
                                    <span className="flex shrink-0 gap-1">
                                        <Button size="sm" variant="ghost"
                                                aria-label={`Transfer ${a.scope.name}`}
                                                onClick={() => setTransferScope({
                                                    id: a.scope.id, name: a.scope.name,
                                                    level: a.scope.level, code: a.scope.code,
                                                })}>
                                            <ArrowRightLeft className="h-3.5 w-3.5"/>
                                        </Button>
                                        <Button size="sm" variant="ghost"
                                                aria-label={`End assignment for ${a.scope.name}`}
                                                disabled={endMutation.isPending}
                                                onClick={() => endAssignment(a)}>
                                            <X className="h-3.5 w-3.5"/>
                                        </Button>
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                    <p className="mt-3 text-xs text-gray-500">
                        Any sales in these places land with this person. Use ⇄ to hand a territory to
                        someone new — the place and its numbers stay put, only the owner changes.
                    </p>
                </>
            )}

            {assignOpen && (
                <AssignDialog geoTypeCode={geoTypeCode} fixedAssignee={assignee}
                              onClose={() => setAssignOpen(false)}/>
            )}
            {transferScope && (
                <TerritoryTransferDialog geoTypeCode={geoTypeCode} fixedScope={transferScope}
                                         onClose={() => setTransferScope(null)}/>
            )}
        </Card>
    );
}

interface Props {
    entityId: number;
}

export function EntityCard({entityId}: Props) {
    const [showEditForm, setShowEditForm] = useState(false);
    const [showTransfer, setShowTransfer] = useState(false);
    const [showChangeType, setShowChangeType] = useState(false);
    const [showDeactivateConfirm, setShowDeactivateConfirm] = useState(false);

    const {select} = useHierarchyStore();
    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');
    const {data: entity, isLoading} = useEntity(entityId);
    const {data: childrenData} = useEntityChildren(entityId);
    const childItems = childrenData?.pages.flatMap((p) => p.results) ?? [];
    const childCount = childrenData?.pages[0]?.count ?? 0;
    const {data: relsData} = useEntityRelationships(entityId);
    const endRelMutation = useEndRelationship();
    const deactivateMutation = useDeactivateEntity();
    const reactivateMutation = useReactivateEntity();

    const relationships = relsData?.results ?? [];

    if (isLoading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spinner size="lg"/>
            </div>
        );
    }

    if (!entity) {
        return (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
                Entity not found.
            </div>
        );
    }

    const et = entity.entity_type;
    const etColor = et.display_config.color ?? '#6B7280';

    function handleDeactivate() {
        deactivateMutation.mutate(entity!.id, {
            onSuccess: () => {
                notify.success(`${entity!.name} was removed.`);
                select(null);
            },
            onError: () =>
                notify.error('You can’t remove someone who still has a team. Move or remove their team first.'),
        });
    }

    function handleReactivate() {
        reactivateMutation.mutate(entity!.id, {
            onSuccess: () => notify.success(`${entity!.name} reactivated.`),
            onError: () =>
                notify.error('Cannot reactivate: the parent may be inactive. Reactivate the parent first.'),
        });
    }

    const trail = entity.parent_info
        ? [{label: entity.parent_info.name, onClick: () => select(entity.parent_info!.id)}, {label: entity.name}]
        : [{label: 'Top level'}, {label: entity.name}];

    return (
        <div className="space-y-4 p-6">

            <Breadcrumb items={trail}/>

            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
            <span
                className="h-3 w-3 shrink-0 rounded-full"
                style={{background: etColor}}
            />
                        <h2 className="text-xl font-semibold text-gray-900 truncate">{entity.name}</h2>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <Badge variant="info">{et.name}</Badge>
                        <StatusBadge status={entity.status}/>
                        {entity.channel !== null && (
                            <Badge variant="default">{entity.channel.name}</Badge>
                        )}
                        <span className="font-mono text-xs text-gray-500">{entity.code}</span>
                    </div>
                </div>


                {writable && (
                    <div className="flex shrink-0 items-center gap-2">
                        <Button size="sm" variant="outline" icon={<Edit2 className="h-3.5 w-3.5"/>}
                                onClick={() => setShowEditForm(true)}>
                            Edit
                        </Button>
                        {PERSON_TRANSFER_ENABLED && (
                            <Button size="sm" variant="outline" icon={<ArrowRightLeft className="h-3.5 w-3.5"/>}
                                    onClick={() => setShowTransfer(true)}>
                                Transfer person
                            </Button>
                        )}
                        {CHANGE_ROLE_ENABLED && entity.status === 'active' && (
                            <Button size="sm" variant="outline" icon={<Repeat className="h-3.5 w-3.5"/>}
                                    onClick={() => setShowChangeType(true)}>
                                Change Role
                            </Button>
                        )}
                        {entity.status !== 'active' && (
                            <Button size="sm" variant="primary" icon={<RotateCcw className="h-3.5 w-3.5"/>}
                                    loading={reactivateMutation.isPending}
                                    onClick={handleReactivate}>
                                Activate
                            </Button>
                        )}
                        {entity.status === 'active' && (
                            <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5"/>}
                                    onClick={() => setShowDeactivateConfirm(true)}>
                                Deactivate
                            </Button>
                        )}
                    </div>
                )}
            </div>


            <Card title="Attributes" padding="sm" actions={
                writable ? (
                    <Button size="sm" variant="ghost" icon={<Edit2 className="h-3.5 w-3.5"/>}
                            onClick={() => setShowEditForm(true)}>
                        Edit
                    </Button>
                ) : undefined
            }>
                <AttributesSection entity={entity}/>
            </Card>


            <Card title="Hierarchy" padding="sm">
                <div className="space-y-2 text-sm">
                    {entity.parent_info ? (
                        <div className="flex items-center gap-2">
                            <GitBranch className="h-4 w-4 shrink-0 text-gray-400"/>
                            <span className="text-gray-500">Reports to:</span>
                            <span className="font-medium text-gray-900">{entity.parent_info.name}</span>
                            {entity.parent_info.type && (
                                <span className="font-mono text-xs text-gray-400">({entity.parent_info.type})</span>
                            )}
                        </div>
                    ) : (
                        <p className="text-gray-400">Top of the hierarchy — no manager above.</p>
                    )}
                </div>
            </Card>


            <TerritoriesOwned
                assignee={{id: entity.id, name: entity.name, code: entity.code, type: et.name}}
                writable={writable}
                canOwn={!et.is_leaf}
            />


            {childCount > 0 && (
                <Card
                    title="Team"
                    subtitle={`${childCount} direct ${childCount === 1 ? 'member' : 'members'}`}
                    padding="sm"
                >
                    <ul className="space-y-1.5">
                        {childItems.slice(0, 8).map((child) => (
                            <li key={child.id} className="flex items-center justify-between text-sm">
                                <span className="font-medium text-gray-900">{child.name}</span>
                                <div className="flex items-center gap-2">
                                    {(child.entity_type_name ?? child.entity_type_code) && (
                                        <span
                                            className="text-xs text-gray-500">{child.entity_type_name ?? child.entity_type_code}</span>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => select(child.id)}
                                        className="text-xs text-primary hover:underline"
                                    >
                                        View
                                    </button>
                                </div>
                            </li>
                        ))}
                        {childCount > 8 && (
                            <li className="text-xs text-gray-400">+{childCount - 8} more</li>
                        )}
                    </ul>
                </Card>
            )}


            {relationships.length > 0 && (
                <Card title="Relationships" padding="sm">
                    <ul className="space-y-2">
                        {relationships.map((rel) => {
                            const isFrom = rel.from_entity === entityId;
                            return (
                                <li key={rel.id} className="flex items-center justify-between text-sm">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <Link2 className="h-3.5 w-3.5 shrink-0 text-gray-400"/>
                                        <span className="text-xs text-gray-500">{rel.type_name}</span>
                                        {isFrom ? (
                                            <span className="text-gray-900 truncate">→ {rel.to_entity_name}</span>
                                        ) : (
                                            <span className="text-gray-900 truncate">← {rel.from_entity_name}</span>
                                        )}
                                        <span className="shrink-0 text-xs text-gray-400">
                      from {rel.effective_from}
                                            {rel.effective_to ? ` to ${rel.effective_to}` : ''}
                    </span>
                                    </div>
                                    {writable && rel.effective_to === null && (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                endRelMutation.mutate(rel.id, {
                                                    onSuccess: () => notify.success('Relationship ended.'),
                                                })
                                            }
                                            className="shrink-0 text-xs text-danger hover:underline"
                                        >
                                            End
                                        </button>
                                    )}
                                </li>
                            );
                        })}
                    </ul>
                </Card>
            )}


            {et.is_loginable && entity.linked_user && (
                <Card title="Linked User" padding="sm">
                    <div className="flex items-start gap-3 text-sm">
                        <User className="mt-0.5 h-4 w-4 shrink-0 text-gray-400"/>
                        <div className="space-y-0.5">
                            {entity.linked_user.email && (
                                <p className="text-gray-900">{entity.linked_user.email}</p>
                            )}
                            {entity.linked_user.mobile && (
                                <p className="text-gray-600">{entity.linked_user.mobile}</p>
                            )}
                            <div className="flex items-center gap-2">
                                <StatusBadge status={entity.linked_user.is_active ? 'active' : 'inactive'}/>
                            </div>
                        </div>
                    </div>
                </Card>
            )}


            <div className="text-xs text-gray-400">
                <Link to={`/network/people/${entity.id}`} className="hover:text-primary hover:underline">
                    View full page →
                </Link>
            </div>


            {showEditForm && (
                <EntityForm entity={entity} onClose={() => setShowEditForm(false)}/>
            )}
            {showTransfer && (
                <TransferDialog entity={entity} onClose={() => setShowTransfer(false)}/>
            )}
            {showChangeType && (
                <ChangeTypeDialog entity={entity} onClose={() => setShowChangeType(false)}/>
            )}
            <ConfirmDialog
                open={showDeactivateConfirm}
                onClose={() => setShowDeactivateConfirm(false)}
                title="Deactivate Entity"
                message={`Are you sure you want to deactivate "${entity.name}"? This will also deactivate the linked user account (if any) and end active relationships.`}
                confirmLabel="Deactivate"
                variant="danger"
                onConfirm={handleDeactivate}
            />
        </div>
    );
}
