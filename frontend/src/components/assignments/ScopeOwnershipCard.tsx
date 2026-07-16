import {useState} from 'react';
import {ArrowRightLeft, UserCheck, X} from 'lucide-react';
import {useAssignments, useEndAssignment} from '../../hooks/useAssignments';
import {useRBAC} from '../../hooks/useRBAC';
import type {GeoSelection} from '../entity/GeoNodeCombobox';
import type {Assignment} from '../../types/assignment';
import {Badge} from '../ui/Badge';
import {Button} from '../ui/Button';
import {Card} from '../ui/Card';
import {StatusBadge} from '../ui/StatusBadge';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {AssignDialog} from './AssignDialog';
import {TerritoryTransferDialog} from './TerritoryTransferDialog';

const ROLE_LABEL: Record<string, string> = {
    owner: 'Owner',
    stand_in: 'Stand-in',
    supervisor: 'Supervisor',
};

/** Who looks after this territory, right on the territory's panel — with
 * assign/transfer/end in place, so ownership never needs a page hop. */
export function ScopeOwnershipCard({scope, geoTypeCode}: {scope: GeoSelection; geoTypeCode: string}) {
    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');
    const {data, isLoading} = useAssignments({scope: scope.id, open: true});
    const rows = data?.results ?? [];
    const owner = rows.find((a) => a.role_in_scope === 'owner');

    const [assignOpen, setAssignOpen] = useState(false);
    const [transferOpen, setTransferOpen] = useState(false);

    const endMutation = useEndAssignment();
    const endAssignment = (a: Assignment) => {
        endMutation.mutate(
            {
                id: a.id,
                payload: {effective_to: new Date().toISOString().slice(0, 10), reason: 'Ended from the app'},
            },
            {
                onSuccess: () => notify.success("That's wrapped up — they're no longer in charge of it."),
                onError: (err) => notify.error(apiErrorMessage(err, "Sorry, we couldn't wrap that up")),
            },
        );
    };

    return (
        <Card
            title="Ownership"
            padding="sm"
            actions={
                writable ? (
                    owner ? (
                        <Button size="sm" variant="ghost" icon={<ArrowRightLeft className="h-3.5 w-3.5"/>}
                                onClick={() => setTransferOpen(true)}>
                            Transfer
                        </Button>
                    ) : (
                        <Button size="sm" variant="ghost" icon={<UserCheck className="h-3.5 w-3.5"/>}
                                onClick={() => setAssignOpen(true)}>
                            Assign owner
                        </Button>
                    )
                ) : undefined
            }
        >
            {isLoading ? (
                <p className="text-sm text-gray-400">Loading…</p>
            ) : rows.length === 0 ? (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                    <StatusBadge status="vacant"/>
                    Nobody looks after this place — its numbers roll up to the nearest owned
                    territory above it.
                </div>
            ) : (
                <ul className="space-y-1.5">
                    {rows.map((a) => (
                        <li key={a.id} className="flex items-center gap-2 text-sm">
                            <span className="font-medium text-gray-900">{a.assignee.name}</span>
                            <Badge variant={a.role_in_scope === 'owner' ? 'info' : 'default'}>
                                {ROLE_LABEL[a.role_in_scope] ?? a.role_in_scope}
                            </Badge>
                            <span className="ml-auto text-xs text-gray-400">since {a.effective_from}</span>
                            {writable && (
                                <Button size="sm" variant="ghost"
                                        aria-label={`End assignment for ${a.assignee.name}`}
                                        disabled={endMutation.isPending}
                                        onClick={() => endAssignment(a)}>
                                    <X className="h-3.5 w-3.5"/>
                                </Button>
                            )}
                        </li>
                    ))}
                </ul>
            )}

            {assignOpen && (
                <AssignDialog geoTypeCode={geoTypeCode} fixedScope={scope}
                              onClose={() => setAssignOpen(false)}/>
            )}
            {transferOpen && (
                <TerritoryTransferDialog geoTypeCode={geoTypeCode} fixedScope={scope}
                                         onClose={() => setTransferOpen(false)}/>
            )}
        </Card>
    );
}
