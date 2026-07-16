import {useState} from 'react';
import {AlertTriangle} from 'lucide-react';
import {notify} from '../../utils/notify';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Textarea} from '../ui/Textarea';
import {useBulkDeactivateEntities} from '../../hooks/useEntities';
import type {BulkOpResult} from '../../types/entity';

interface Props {
    ids: number[];
    onClose: () => void;
    onDone: () => void;
}

export function BulkDeactivateDialog({ids, onClose, onDone}: Props) {
    const [reason, setReason] = useState('');
    const [cascade, setCascade] = useState(false);
    const [errors, setErrors] = useState<BulkOpResult['errors']>([]);

    const deactivateMutation = useBulkDeactivateEntities();
    const canSubmit = reason.trim().length > 0;

    function handleSubmit() {
        setErrors([]);
        deactivateMutation.mutate(
            {entity_ids: ids, reason: reason.trim(), cascade},
            {
                onSuccess: (res) => {
                    if (res.status === 'validation_failed') {
                        setErrors(res.errors ?? []);
                        return;
                    }
                    notify.success(`${res.deactivated ?? ids.length} entities deactivated.`);
                    onDone();
                    onClose();
                },
                onError: () => notify.error('Bulk deactivate failed unexpectedly.'),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Deactivate ${ids.length} ${ids.length === 1 ? 'Entity' : 'Entities'}`}
            size="lg"
            footer={
                <>
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button variant="danger" onClick={handleSubmit} loading={deactivateMutation.isPending}
                            disabled={!canSubmit}>
                        Deactivate
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                <div className="flex items-start gap-2 rounded-lg bg-warning-50 px-3 py-2 text-sm text-warning">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0"/>
                    <span>
            Deactivating <strong>{ids.length}</strong> {ids.length === 1 ? 'entity' : 'entities'}.
            Linked user accounts are disabled and open relationships are ended. This is a soft delete.
          </span>
                </div>

                <Textarea
                    label="Reason *"
                    placeholder="Store closed, partner churned, etc."
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={2}
                />

                <label className="flex items-center gap-2 text-sm text-gray-700">
                    <input
                        type="checkbox"
                        checked={cascade}
                        onChange={(e) => setCascade(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary/30"
                    />
                    Cascade — also deactivate each entity&apos;s entire subtree
                </label>
                {!cascade && (
                    <p className="text-xs text-gray-400">
                        Without cascade, an entity with active children not in your selection is rejected.
                    </p>
                )}

                {errors && errors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            Nothing was deactivated
                            — {errors.length} {errors.length === 1 ? 'entity' : 'entities'} blocked:
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
