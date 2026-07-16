import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Check, UserX, X} from 'lucide-react';
import {adminService} from '../../services/adminService';
import {
    useCreateDelegation,
    useDelegations,
    useEndDelegation,
    useWorkflowDefinitions,
} from '../../hooks/useWorkflows';
import {useAuthStore} from '../../stores/authStore';
import type {ApprovalDelegation} from '../../types/workflow';
import type {User} from '../../types/auth';
import {Button} from '../ui/Button';
import {Input} from '../ui/Input';
import {Select} from '../ui/Select';
import {Modal} from '../ui/Modal';
import {Badge} from '../ui/Badge';
import {Spinner} from '../ui/Spinner';
import {Textarea} from '../ui/Textarea';
import {EmptyState} from '../ui/EmptyState';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';

function userLabel(u: User): string {
    return `${u.first_name} ${u.last_name}`.trim() || u.email || `User #${u.id}`;
}

export function DelegationsDialog({open, onClose}: {open: boolean; onClose: () => void}) {
    const [creating, setCreating] = useState(false);
    const {data, isLoading} = useDelegations(open);
    const endDelegation = useEndDelegation();
    const me = useAuthStore((s) => s.user);

    const rows = data?.results ?? [];

    return (
        <Modal open={open} onClose={onClose} title="Approval delegations" size="lg">
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <p className="text-sm text-gray-500">
                        Out-of-office cover: your delegate can act on approvals routed to you within the window.
                    </p>
                    {!creating && (
                        <Button size="sm" onClick={() => setCreating(true)}>New delegation</Button>
                    )}
                </div>

                {creating && (
                    <DelegationForm onDone={() => setCreating(false)}/>
                )}

                {isLoading ? (
                    <div className="flex justify-center py-8"><Spinner/></div>
                ) : rows.length === 0 ? (
                    <EmptyState icon={UserX} title="No delegations"
                                description="Delegations you give or receive appear here."/>
                ) : (
                    <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                        {rows.map((d) => (
                            <DelegationRow
                                key={d.id}
                                delegation={d}
                                isMine={me?.id === d.delegator}
                                onEnd={() =>
                                    endDelegation.mutate(d.id, {
                                        onSuccess: () => notify.success('Delegation ended'),
                                        onError: (e) => notify.error(apiErrorMessage(e, 'Could not end delegation')),
                                    })
                                }
                                ending={endDelegation.isPending}
                            />
                        ))}
                    </ul>
                )}
            </div>
        </Modal>
    );
}


function DelegationRow({delegation: d, isMine, onEnd, ending}: {
    delegation: ApprovalDelegation;
    isMine: boolean;
    onEnd: () => void;
    ending: boolean;
}) {
    return (
        <li className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
                <p className="truncate text-sm text-gray-900">
                    <span className="font-medium">{d.delegator_name ?? `User #${d.delegator}`}</span>
                    {' → '}
                    <span className="font-medium">{d.delegate_name ?? `User #${d.delegate}`}</span>
                </p>
                <p className="mt-0.5 text-xs text-gray-500">
                    {d.start_date} to {d.end_date}
                    {d.reason ? ` · ${d.reason}` : ''}
                </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                <Badge variant={d.scope === 'all' || !d.scope ? 'info' : 'purple'}>
                    {d.scope === 'all' || !d.scope ? 'All workflows' : d.scope}
                </Badge>
                {isMine && (
                    <Button variant="ghost" size="sm" loading={ending} onClick={onEnd}
                            aria-label="End delegation">
                        <X className="h-4 w-4 text-danger"/>
                    </Button>
                )}
            </div>
        </li>
    );
}


function DelegationForm({onDone}: {onDone: () => void}) {
    const [delegate, setDelegate] = useState<{id: number; label: string} | null>(null);
    const [scope, setScope] = useState('all');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [reason, setReason] = useState('');
    const [serverError, setServerError] = useState<string | null>(null);

    const {data: defs} = useWorkflowDefinitions();
    const create = useCreateDelegation();

    const submit = () => {
        if (!delegate) return;
        setServerError(null);
        create.mutate(
            {delegate: delegate.id, scope, start_date: startDate, end_date: endDate,
             reason: reason.trim() || undefined},
            {
                onSuccess: () => {
                    notify.success('Delegation created');
                    onDone();
                },
                onError: (e) => setServerError(apiErrorMessage(e, 'Could not create delegation')),
            },
        );
    };

    const valid = delegate !== null && startDate && endDate && startDate <= endDate;

    return (
        <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
            <UserPicker value={delegate} onChange={setDelegate}/>
            <div className="grid grid-cols-2 gap-3">
                <Select
                    label="Scope"
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    options={[
                        {value: 'all', label: 'All workflows'},
                        ...(defs?.results ?? []).map((d) => ({value: d.code, label: d.name})),
                    ]}
                />
                <div/>
                <Input label="From" type="date" value={startDate}
                       onChange={(e) => setStartDate(e.target.value)}/>
                <Input label="To" type="date" value={endDate}
                       onChange={(e) => setEndDate(e.target.value)}/>
            </div>
            <Textarea label="Reason (optional)" rows={2} value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="e.g. Annual leave"/>
            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={onDone}>Cancel</Button>
                <Button size="sm" onClick={submit} loading={create.isPending} disabled={!valid}>
                    Create delegation
                </Button>
            </div>
        </div>
    );
}


/** Search-driven delegate picker via the users API; falls back to manual id
 * entry when the caller lacks user_management. */
function UserPicker({value, onChange}: {
    value: {id: number; label: string} | null;
    onChange: (v: {id: number; label: string} | null) => void;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);

    const term = q.trim();
    const {data, isError, isLoading} = useQuery({
        queryKey: ['workflows', 'delegate-search', term],
        queryFn: () => adminService.listUsers({search: term, status: 'active'}),
        enabled: term.length > 1,
        retry: false,
    });

    if (isError) {
        // No user_management permission — accept a raw user id instead of a search.
        return (
            <Input label="Delegate user ID" type="number" value={value ? String(value.id) : ''}
                   onChange={(e) => {
                       const id = Number(e.target.value);
                       onChange(id > 0 ? {id, label: `User #${id}`} : null);
                   }}
                   hint="You don't have access to user search — ask an admin for the user's ID."/>
        );
    }

    if (value) {
        return (
            <div className="space-y-1">
                <label className="text-xs font-medium text-gray-600">Delegate</label>
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <span className="flex min-w-0 items-center gap-2 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-success"/>
                        <span className="truncate font-medium text-gray-900">{value.label}</span>
                    </span>
                    <button type="button" onClick={() => onChange(null)}
                            className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                            aria-label="Clear delegate">
                        <X className="h-4 w-4"/>
                    </button>
                </div>
            </div>
        );
    }

    const results = term.length > 1 ? (data?.results ?? []) : [];

    return (
        <div className="relative space-y-1">
            <label className="text-xs font-medium text-gray-600">Delegate</label>
            <input
                type="text"
                placeholder="Search a person by name or email…"
                value={q}
                onChange={(e) => {
                    setQ(e.target.value);
                    setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onBlur={() => setTimeout(() => setOpen(false), 150)}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
                   focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            {open && term.length > 1 && (
                <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                    {isLoading && <div className="flex justify-center py-2"><Spinner size="sm"/></div>}
                    {!isLoading && results.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">No matching users.</p>
                    )}
                    {results.map((u) => (
                        <button
                            key={u.id}
                            type="button"
                            onMouseDown={() => {
                                onChange({id: u.id, label: userLabel(u)});
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="flex-1 truncate">{userLabel(u)}</span>
                            <span className="text-xs text-gray-500">{u.email}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
