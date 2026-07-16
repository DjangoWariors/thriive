import {useState} from 'react';
import {notify} from '../../utils/notify';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Textarea} from '../ui/Textarea';
import {Spinner} from '../ui/Spinner';
import {useBulkMoveEntities, useEntitySearch} from '../../hooks/useEntities';
import type {EntityListItem, BulkOpResult} from '../../types/entity';

interface Props {
    ids: number[];
    onClose: () => void;
    onDone: () => void;
}

export function BulkMoveDialog({ids, onClose, onDone}: Props) {
    const [searchQ, setSearchQ] = useState('');
    const [newParent, setNewParent] = useState<EntityListItem | null>(null);
    const [reason, setReason] = useState('');
    const [effectiveDate, setEffectiveDate] = useState(
        new Date().toISOString().split('T')[0] as string,
    );
    const [errors, setErrors] = useState<BulkOpResult['errors']>([]);

    const moveMutation = useBulkMoveEntities();
    const {data: searchResults, isLoading: searching} = useEntitySearch(searchQ);
    const candidates = (searchResults ?? []).filter((r) => !ids.includes(r.id));

    const canSubmit = newParent !== null && reason.trim().length > 0;

    function handleSubmit() {
        if (!newParent) return;
        setErrors([]);
        moveMutation.mutate(
            {
                entity_ids: ids,
                new_parent_id: newParent.id,
                reason: reason.trim(),
                effective_date: effectiveDate,
            },
            {
                onSuccess: (res) => {
                    if (res.status === 'validation_failed') {
                        setErrors(res.errors ?? []);
                        return;
                    }
                    notify.success(`${res.moved ?? ids.length} moved to ${newParent.name}.`);
                    onDone();
                    onClose();
                },
                onError: () => notify.error('Something went wrong. Please try again.'),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Move ${ids.length} selected`}
            size="lg"
            footer={
                <>
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button onClick={handleSubmit} loading={moveMutation.isPending} disabled={!canSubmit}>
                        Move {ids.length === 1 ? 'them' : 'all'}
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                <div className="rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-600">
                    Moving <strong>{ids.length}</strong> selected{' '}
                    {ids.length === 1 ? 'person' : 'people'} — each one together with everyone under them —
                    to report to the same new manager.
                </div>

                <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Who should they report to now?</label>
                    <input
                        type="text"
                        placeholder="Search by name…"
                        value={searchQ}
                        onChange={(e) => {
                            setSearchQ(e.target.value);
                            setNewParent(null);
                        }}
                        className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                       focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    {searchQ.length > 0 && (
                        <div
                            className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-sm">
                            {searching && (
                                <div className="flex justify-center py-3"><Spinner size="sm"/></div>
                            )}
                            {!searching && candidates.length === 0 && (
                                <p className="px-3 py-2 text-sm text-gray-400">No matches.</p>
                            )}
                            {candidates.map((r) => (
                                <button
                                    key={r.id}
                                    type="button"
                                    onClick={() => {
                                        setNewParent(r);
                                        setSearchQ(r.name);
                                    }}
                                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                                >
                                    <span className="flex-1">{r.name}</span>
                                    <span className="text-xs text-gray-500">{r.entity_type_name ?? r.entity_type_code}</span>
                                </button>
                            ))}
                        </div>
                    )}
                    {newParent && <p className="mt-1 text-xs text-success">✓ Selected: {newParent.name}</p>}
                    <p className="mt-1 text-xs text-gray-400">
                        We’ll check each one can sit under the new manager. Any that can’t are listed below.
                    </p>
                </div>

                <Textarea
                    label="Reason for this change"
                    placeholder="e.g. reorganization or a change of area"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={2}
                />

                <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">When does this start?</label>
                    <input
                        type="date"
                        value={effectiveDate}
                        onChange={(e) => setEffectiveDate(e.target.value)}
                        className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                       focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                </div>

                {errors && errors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            Nothing was moved — {errors.length} couldn’t be placed there:
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
