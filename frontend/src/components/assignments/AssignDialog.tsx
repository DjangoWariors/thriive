import {useState} from 'react';
import {UserCheck} from 'lucide-react';
import {useCreateAssignment} from '../../hooks/useAssignments';
import {EntityCombobox, type EntitySelection} from '../entity/EntityCombobox';
import {GeoNodeCombobox, type GeoSelection} from '../entity/GeoNodeCombobox';
import {Button} from '../ui/Button';
import {Input} from '../ui/Input';
import {Modal} from '../ui/Modal';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {PinnedField} from './PinnedField';

const TODAY = new Date().toISOString().slice(0, 10);

/** Open an owner assignment. Pin either side (`fixedAssignee` from a person's
 * card, `fixedScope` from a territory's panel) and only the other is asked for. */
export function AssignDialog({geoTypeCode, fixedAssignee, fixedScope, onClose}: {
    geoTypeCode: string;
    fixedAssignee?: EntitySelection;
    fixedScope?: GeoSelection;
    onClose: () => void;
}) {
    const create = useCreateAssignment();
    const [assignee, setAssignee] = useState<EntitySelection | null>(fixedAssignee ?? null);
    const [scope, setScope] = useState<GeoSelection | null>(fixedScope ?? null);
    const [from, setFrom] = useState(TODAY);
    const [reason, setReason] = useState('');

    const submit = () => {
        if (!assignee || !scope) {
            notify.error('Please choose both a person and a territory.');
            return;
        }
        create.mutate(
            {assignee_id: assignee.id, scope_id: scope.id, effective_from: from, reason},
            {
                onSuccess: () => {
                    notify.success("All set — they're now in charge of that territory.");
                    onClose();
                },
                onError: (err) => notify.error(apiErrorMessage(err, "Sorry, we couldn't set that up")),
            },
        );
    };

    return (
        <Modal open onClose={onClose} title="New assignment">
            <div className="space-y-4">
                {fixedAssignee ? (
                    <PinnedField label="Who's taking it on?" name={fixedAssignee.name} code={fixedAssignee.code}/>
                ) : (
                    <EntityCombobox label="Who's taking it on?" value={assignee} onChange={setAssignee}/>
                )}
                {fixedScope ? (
                    <PinnedField label="Which territory?" name={fixedScope.name} code={fixedScope.code}/>
                ) : (
                    <GeoNodeCombobox
                        typeCode={geoTypeCode}
                        label="Which territory?"
                        value={scope}
                        onChange={setScope}
                    />
                )}
                <Input
                    type="date"
                    label="Starting from"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                />
                <Input label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)}/>
                <div className="flex justify-end gap-2">
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button onClick={submit} disabled={create.isPending}>
                        <UserCheck className="h-4 w-4"/> Put them in charge
                    </Button>
                </div>
            </div>
        </Modal>
    );
}
