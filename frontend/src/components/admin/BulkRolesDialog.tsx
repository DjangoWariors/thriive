import {useState} from 'react';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {useRoles, useBulkAssignRoles} from '../../hooks/useAdmin';
import type {BulkRolesResult} from '../../types/admin';
import {notify} from '../../utils/notify';
import {cn} from '../../utils/cn';

interface Props {
    userIds: number[];
    onClose: () => void;
    onDone: () => void;
}

export function BulkRolesDialog({userIds, onClose, onDone}: Props) {
    const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
    const [mode, setMode] = useState<'add' | 'replace'>('add');
    const [errors, setErrors] = useState<BulkRolesResult['errors']>([]);

    const {data: rolesResp} = useRoles();
    const roles = rolesResp?.results ?? [];
    const assignMutation = useBulkAssignRoles();

    const toggleCode = (code: string) =>
        setSelectedCodes((prev) =>
            prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
        );

    const canSubmit = selectedCodes.length > 0;

    function handleSubmit() {
        setErrors([]);
        assignMutation.mutate(
            {user_ids: userIds, role_codes: selectedCodes, mode},
            {
                onSuccess: (res) => {
                    if (res.status === 'validation_failed') {
                        setErrors(res.errors ?? []);
                        return;
                    }
                    notify.success(`Roles assigned to ${res.updated ?? userIds.length} user(s).`);
                    onDone();
                    onClose();
                },
                onError: () => notify.error('Bulk role assignment failed unexpectedly.'),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Assign Roles — ${userIds.length} user${userIds.length === 1 ? '' : 's'}`}
            size="md"
            footer={
                <>
                    <Button variant="outline" onClick={onClose}>Cancel</Button>
                    <Button onClick={handleSubmit} loading={assignMutation.isPending} disabled={!canSubmit}>
                        Apply
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                {/* Mode */}
                <div className="flex overflow-hidden rounded-lg border border-gray-200 text-sm">
                    {(['add', 'replace'] as const).map((m) => (
                        <button
                            key={m}
                            type="button"
                            onClick={() => setMode(m)}
                            className={cn(
                                'flex-1 px-3 py-1.5 font-medium transition-colors',
                                mode === m ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50',
                            )}
                        >
                            {m === 'add' ? 'Add to existing' : 'Replace all'}
                        </button>
                    ))}
                </div>
                <p className="text-xs text-gray-400">
                    {mode === 'add'
                        ? 'Selected roles are added; existing roles are kept.'
                        : 'Selected roles become each user’s exact role set.'}
                </p>


                <div className="space-y-1">
                    {roles.map((r) => (
                        <label
                            key={r.code}
                            className={cn(
                                'flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors',
                                selectedCodes.includes(r.code)
                                    ? 'border-primary bg-primary-50 text-primary'
                                    : 'border-gray-200 text-gray-700 hover:bg-gray-50',
                            )}
                        >
                            <input
                                type="checkbox"
                                checked={selectedCodes.includes(r.code)}
                                onChange={() => toggleCode(r.code)}
                                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary/30"
                            />
                            <span className="flex-1 font-medium">{r.name}</span>
                            <span className="font-mono text-xs text-gray-500">{r.code}</span>
                        </label>
                    ))}
                </div>

                {errors && errors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            Nothing was changed — {errors.length} error(s):
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
