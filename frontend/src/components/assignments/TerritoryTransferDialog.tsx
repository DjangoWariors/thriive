import {useState} from 'react';
import {ArrowRightLeft} from 'lucide-react';
import {useTransferAssignment} from '../../hooks/useAssignments';
import {EntityCombobox, type EntitySelection} from '../entity/EntityCombobox';
import {GeoNodeCombobox, type GeoSelection} from '../entity/GeoNodeCombobox';
import {Button} from '../ui/Button';
import {Input} from '../ui/Input';
import {Modal} from '../ui/Modal';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {PinnedField} from './PinnedField';

const TODAY = new Date().toISOString().slice(0, 10);

/** Hand ONE territory to a new owner (the AssignmentService.transfer primitive).
 * Pin the scope (`fixedScope`) when launched from a territory panel or a
 * person's owned-territory row; the person-level wizard is TransferDialog. */
export function TerritoryTransferDialog({geoTypeCode, fixedScope, onClose}: {
    geoTypeCode: string;
    fixedScope?: GeoSelection;
    onClose: () => void;
}) {
    const transfer = useTransferAssignment();
    const [scope, setScope] = useState<GeoSelection | null>(fixedScope ?? null);
    const [newAssignee, setNewAssignee] = useState<EntitySelection | null>(null);
    const [from, setFrom] = useState(TODAY);
    const [reason, setReason] = useState('');

    const submit = () => {
        if (!scope || !newAssignee) {
            notify.error('Please choose a territory and who should take it over.');
            return;
        }
        transfer.mutate(
            {scope_id: scope.id, new_assignee_id: newAssignee.id, effective_from: from, reason},
            {
                onSuccess: () => {
                    notify.success('Done — the new owner takes over on the date you picked.');
                    onClose();
                },
                onError: (err) => notify.error(apiErrorMessage(err, "Sorry, we couldn't hand that over")),
            },
        );
    };

    return (
        <Modal open onClose={onClose} title="Transfer territory">
            <div className="space-y-4">
                <p className="text-sm text-gray-500">
                    The territory itself — its outlets and its targets — doesn't budge; only who's in charge
                    changes. We'll close out the current owner the day before, and the new one picks up from
                    your chosen date.
                </p>
                {fixedScope ? (
                    <PinnedField label="Which territory are you handing over?"
                                 name={fixedScope.name} code={fixedScope.code}/>
                ) : (
                    <GeoNodeCombobox
                        typeCode={geoTypeCode}
                        label="Which territory are you handing over?"
                        value={scope}
                        onChange={setScope}
                    />
                )}
                <EntityCombobox label="Who's taking it over?" value={newAssignee} onChange={setNewAssignee}/>
                <Input
                    type="date"
                    label="Starting from"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                />
                <Input label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)}/>
                <div className="flex justify-end gap-2">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button onClick={submit} disabled={transfer.isPending}>
                        <ArrowRightLeft className="h-4 w-4"/> Hand it over
                    </Button>
                </div>
            </div>
        </Modal>
    );
}
