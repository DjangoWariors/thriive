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
import {formatDate} from '../../utils/format';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';

function userLabel(u: User): string {
    return `${u.first_name} ${u.last_name}`.trim() || u.email || `User #${u.id}`;
}

export function isActiveNow(d: ApprovalDelegation): boolean {
    const today = new Date().toISOString().slice(0, 10);
    return d.is_active && d.start_date <= today && d.end_date >= today;
}

export function DelegationsDialog({open, onClose}: {open: boolean; onClose: () => void}) {
    const [creating, setCreating] = useState(false);
    const {data, isLoading} = useDelegations(open);
    const me = useAuthStore((s) => s.user);

    const rows = data?.results ?? [];
    const given = rows.filter((d) => d.delegator === me?.id);
    const received = rows.filter((d) => d.delegate === me?.id && d.delegator !== me?.id);
    // An admin's list may include third-party delegations — show them, clearly labelled.
    const others = rows.filter((d) => d.delegator !== me?.id && d.delegate !== me?.id);

    return (
        <Modal open={open} onClose={onClose} title="Out-of-office cover" size="lg">
            <div className="space-y-5">
                <div className="flex items-start justify-between gap-4">
                    <p className="text-sm text-gray-500">
                        Going on leave? Pick a person to act on approvals sent to you while you're
                        away. Your pending items appear in their Approvals list for the dates you
                        choose, and every decision is recorded under their name.
                    </p>
                    {!creating && (
                        <Button size="sm" className="shrink-0" onClick={() => setCreating(true)}>
                            Set up cover
                        </Button>
                    )}
                </div>

                {creating && <DelegationForm onDone={() => setCreating(false)}/>}

                {isLoading ? (
                    <div className="flex justify-center py-8"><Spinner/></div>
                ) : rows.length === 0 ? (
                    <EmptyState icon={UserX} title="No cover arranged"
                                description="When you set up cover — or someone asks you to cover for them — it appears here."/>
                ) : (
                    <div className="space-y-5">
                        <DelegationSection
                            title="Covering for you"
                            hint="These people can act on your approvals."
                            rows={given}
                            render={(d) => (
                                <><span className="font-medium">{d.delegate_name ?? `User #${d.delegate}`}</span>
                                {' '}can act on your approvals</>
                            )}
                            canEnd
                        />
                        <DelegationSection
                            title="You're covering for"
                            hint="Their pending approvals show up in your Approvals list."
                            rows={received}
                            render={(d) => (
                                <>You can act for{' '}
                                <span className="font-medium">{d.delegator_name ?? `User #${d.delegator}`}</span></>
                            )}
                        />
                        <DelegationSection
                            title="Other delegations"
                            hint="Cover arrangements between other people (visible to you as an admin)."
                            rows={others}
                            render={(d) => (
                                <><span className="font-medium">{d.delegate_name ?? `User #${d.delegate}`}</span>
                                {' '}covers for{' '}
                                <span className="font-medium">{d.delegator_name ?? `User #${d.delegator}`}</span></>
                            )}
                        />
                    </div>
                )}
            </div>
        </Modal>
    );
}


function DelegationSection({title, hint, rows, render, canEnd = false}: {
    title: string;
    hint: string;
    rows: ApprovalDelegation[];
    render: (d: ApprovalDelegation) => React.ReactNode;
    canEnd?: boolean;
}) {
    const endDelegation = useEndDelegation();
    if (rows.length === 0) return null;
    return (
        <section>
            <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
            <p className="mb-2 text-xs text-gray-500">{hint}</p>
            <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                {rows.map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-3 px-4 py-3">
                        <div className="min-w-0">
                            <p className="truncate text-sm text-gray-900">{render(d)}</p>
                            <p className="mt-0.5 text-xs text-gray-500">
                                {formatDate(d.start_date)} – {formatDate(d.end_date)}
                                {d.reason ? ` · ${d.reason}` : ''}
                                {d.scope && d.scope !== 'all' ? ` · only ${d.scope} approvals` : ''}
                            </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                            {isActiveNow(d) && <Badge variant="success">Active now</Badge>}
                            {canEnd && (
                                <Button variant="ghost" size="sm"
                                        loading={endDelegation.isPending}
                                        aria-label="End this cover"
                                        onClick={() =>
                                            endDelegation.mutate(d.id, {
                                                onSuccess: () => notify.success('Cover ended'),
                                                onError: (e) => notify.error(apiErrorMessage(e, 'Could not end the cover')),
                                            })
                                        }>
                                    <span className="inline-flex items-center gap-1 text-danger">
                                        <X className="h-4 w-4"/> End
                                    </span>
                                </Button>
                            )}
                        </div>
                    </li>
                ))}
            </ul>
        </section>
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
                    notify.success('Cover set up');
                    onDone();
                },
                onError: (e) => setServerError(apiErrorMessage(e, 'Could not set up the cover')),
            },
        );
    };

    const valid = delegate !== null && startDate && endDate && startDate <= endDate;

    return (
        <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
            <UserPicker value={delegate} onChange={setDelegate}/>
            <div className="grid grid-cols-2 gap-3">
                <Input label="Away from" type="date" value={startDate}
                       onChange={(e) => setStartDate(e.target.value)}/>
                <Input label="Away until" type="date" value={endDate}
                       hint="Last day of cover — included"
                       onChange={(e) => setEndDate(e.target.value)}/>
            </div>
            <Textarea label="Reason (optional)" rows={2} value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="e.g. Annual leave"/>
            <div>
                <Select
                    label="Applies to"
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    options={[
                        {value: 'all', label: 'All approvals (recommended)'},
                        ...(defs?.results ?? []).map((d) => ({value: d.code, label: `Only: ${d.name}`})),
                    ]}
                />
                <p className="mt-1 text-xs text-gray-500">
                    Leave on “All approvals” unless the cover should be limited to one approval type.
                </p>
            </div>
            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={onDone}>Cancel</Button>
                <Button size="sm" onClick={submit} loading={create.isPending} disabled={!valid}>
                    Set up cover
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
            <Input label="Who will cover for you? (user ID)" type="number" value={value ? String(value.id) : ''}
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
                <label className="text-xs font-medium text-gray-600">Who will cover for you?</label>
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <span className="flex min-w-0 items-center gap-2 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-success"/>
                        <span className="truncate font-medium text-gray-900">{value.label}</span>
                    </span>
                    <button type="button" onClick={() => onChange(null)}
                            className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                            aria-label="Clear person">
                        <X className="h-4 w-4"/>
                    </button>
                </div>
            </div>
        );
    }

    const results = term.length > 1 ? (data?.results ?? []) : [];

    return (
        <div className="relative space-y-1">
            <label className="text-xs font-medium text-gray-600">Who will cover for you?</label>
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
