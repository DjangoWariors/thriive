import {useState} from 'react';
import {RotateCcw} from 'lucide-react';
import {notify} from '../../utils/notify';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Textarea} from '../ui/Textarea';
import {useBulkReactivateEntities} from '../../hooks/useEntities';
import type {BulkOpResult} from '../../types/entity';

interface Props {
    ids: number[];
    onClose: () => void;
    onDone: () => void;
}

export function BulkReactivateDialog({ids, onClose, onDone}: Props) {
    const [reason, setReason] = useState('');
    const [errors, setErrors] = useState<BulkOpResult['errors']>([]);

    const reactivateMutation = useBulkReactivateEntities();

    function handleSubmit() {
        setErrors([]);
        reactivateMutation.mutate(
            {entity_ids: ids, reason: reason.trim() || undefined},
            {
                onSuccess: (res) => {
                    if (res.status === 'validation_failed') {
                        setErrors(res.errors ?? []);
                        return;
                    }
                    notify.success(`${res.reactivated ?? ids.length} entities reactivated.`);
                    onDone();
                    onClose();
                },
                onError: () => notify.error('Bulk reactivate failed unexpectedly.'),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Reactivate ${ids.length} ${ids.length === 1 ? 'Entity' : 'Entities'}`}
            size="lg"
            footer={
                <>
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button variant="primary" icon={<RotateCcw className="h-4 w-4"/>}
                            onClick={handleSubmit} loading={reactivateMutation.isPending}>
                        Reactivate
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                <div className="rounded-lg bg-success-50 px-4 py-3 text-sm text-success">
                    Reactivating <strong>{ids.length}</strong> {ids.length === 1 ? 'entity' : 'entities'}{' '}
                    (status → active). Linked user accounts are re-enabled. Parents are reactivated
                    first; a child whose parent stays inactive is reported below.
                </div>

                <Textarea
                    label="Reason"
                    placeholder="Reopened, returned to network, etc. (optional)"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={2}
                />

                {errors && errors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            Nothing was reactivated — {errors.length}{' '}
                            {errors.length === 1 ? 'entity' : 'entities'} blocked:
                        </p>
                        <ul className="space-y-1">
                            {errors.map((e) => (
                                <li key={e.id} className="text-xs text-danger">
                                    <span className="font-medium">#{e.id}:</span> {e.errors.join(', ')}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </Modal>
    );
}
