import {useState} from 'react';
import {Plus, Trash2, KeyRound, Copy} from 'lucide-react';
import {useApiKeys, useIssueApiKey, useRevokeApiKey, useUsers} from '../../hooks/useAdmin';
import type {ApiKey, ApiKeyIssued} from '../../types/admin';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Modal} from '../../components/ui/Modal';
import {Badge} from '../../components/ui/Badge';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {notify} from '../../utils/notify';
import {formatRelative} from '../../utils/format';
import {apiErrorMessage} from '../../utils/apiError';

export function ApiKeysTab() {
    const [formOpen, setFormOpen] = useState(false);
    const [revoking, setRevoking] = useState<ApiKey | null>(null);

    const {data, isLoading} = useApiKeys();
    const revoke = useRevokeApiKey();
    const keys = data?.results ?? [];

    const confirmRevoke = () => {
        if (!revoking) return;
        revoke.mutate(revoking.id, {
            onSuccess: () => {
                notify.success(`Key ${revoking.key_prefix}… revoked`);
                setRevoking(null);
            },
            onError: (e) => {
                notify.error(apiErrorMessage(e, 'Could not revoke key'));
                setRevoking(null);
            },
        });
    };

    return (
        <>
            <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-sm text-gray-500">
                    Machine credentials for external systems (DMS, SFA, agency trackers) that push data into Thriive.
                </p>
                <Button icon={<Plus className="h-4 w-4"/>} onClick={() => setFormOpen(true)}>
                    Issue Key
                </Button>
            </div>

            <HowThisWorks storageKey="api-keys-help" className="mb-6">
                Each integration gets its own key, tied to a service-account user whose role decides what it may
                push (grant it <em>Integration Data Push</em>). The system sends the key in an{' '}
                <code>X-API-Key</code> header. The secret is shown once at issue time — store it in the source
                system's vault. Lost or leaked? Revoke here and issue a new one; nothing else changes.
            </HowThisWorks>

            {isLoading ? (
                <TableSkeleton/>
            ) : keys.length === 0 ? (
                <Card>
                    <EmptyState icon={KeyRound} title="No API keys yet"
                                description="Issue a key to let an external system push transactions or metric values."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={keys}
                        rowKey={(k) => k.id}
                        columns={[
                            {header: 'Name', render: (k) => <span className="font-medium text-gray-900">{k.name}</span>},
                            {header: 'Key', render: (k) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
                                    {k.key_prefix}.••••••••
                                </code>
                            )},
                            {header: 'Service account', render: (k) => <span className="text-gray-600">{k.user_display}</span>},
                            {header: 'Expires', render: (k) => (
                                <span className="text-gray-600">
                                    {k.expires_at ? new Date(k.expires_at).toLocaleDateString() : <Badge variant="default">Never</Badge>}
                                </span>
                            )},
                            {header: 'Last used', render: (k) => (
                                <span className="text-gray-500">
                                    {k.last_used_at ? formatRelative(k.last_used_at) : 'Never'}
                                </span>
                            )},
                            {header: 'Actions', align: 'right', render: (k) => (
                                <div className="flex justify-end">
                                    <Button variant="ghost" size="sm" aria-label={`Revoke ${k.name}`}
                                            onClick={() => setRevoking(k)}>
                                        <Trash2 className="h-4 w-4 text-danger"/>
                                    </Button>
                                </div>
                            )},
                        ]}
                    />
                </Card>
            )}

            <Modal open={formOpen} onClose={() => setFormOpen(false)} title="Issue API key" size="lg">
                <IssueKeyForm onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={revoking !== null}
                onClose={() => setRevoking(null)}
                onConfirm={confirmRevoke}
                title="Revoke API key"
                message={`Revoke "${revoking?.name ?? ''}" (${revoking?.key_prefix ?? ''}…)? The source system will get 401s immediately. This cannot be undone.`}
                confirmLabel="Revoke"
                variant="danger"
            />
        </>
    );
}

function IssueKeyForm({onDone}: { onDone: () => void }) {
    const issue = useIssueApiKey();
    const [name, setName] = useState('');
    const [userId, setUserId] = useState('');
    const [expiresAt, setExpiresAt] = useState('');
    const [search, setSearch] = useState('');
    const [issued, setIssued] = useState<ApiKeyIssued | null>(null);
    const [serverError, setServerError] = useState<string | null>(null);

    const {data: usersResp} = useUsers(search ? {search} : undefined);
    const users = usersResp?.results ?? [];

    function submit() {
        setServerError(null);
        issue.mutate(
            {
                name: name.trim(),
                user: Number(userId),
                ...(expiresAt ? {expires_at: new Date(expiresAt).toISOString()} : {}),
            },
            {
                onSuccess: (key) => setIssued(key),
                onError: (e) => setServerError(apiErrorMessage(e, 'Could not issue key')),
            },
        );
    }

    if (issued) {
        return (
            <div className="space-y-4">
                <p className="text-sm text-gray-600">
                    Copy the key now — <strong>it will never be shown again</strong>. Store it in the source
                    system's secret vault.
                </p>
                <div className="flex items-center gap-2 rounded-lg border border-warning-100 bg-warning-50 px-4 py-3">
                    <code className="flex-1 overflow-x-auto text-sm font-medium text-gray-900">{issued.key}</code>
                    <Button variant="outline" size="sm" icon={<Copy className="h-3.5 w-3.5"/>}
                            onClick={() => {
                                void navigator.clipboard.writeText(issued.key).then(
                                    () => notify.success('Key copied'),
                                    () => notify.error('Could not copy'),
                                );
                            }}>
                        Copy
                    </Button>
                </div>
                <p className="text-xs text-gray-500">
                    Send it as <code>X-API-Key: {issued.key_prefix}.…</code> on every request.
                </p>
                <div className="flex justify-end border-t border-gray-100 pt-4">
                    <Button onClick={onDone}>Done</Button>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <Input label="Name" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="e.g. DMS nightly sync" hint="What system uses this key."/>
            <div className="space-y-2">
                <Input label="Service account" value={search} onChange={(e) => setSearch(e.target.value)}
                       placeholder="Search users by name or email…"
                       hint="The key acts as this user — its role decides what the key may push."/>
                {users.length > 0 && (
                    <Select aria-label="Service account user" value={userId} onChange={(e) => setUserId(e.target.value)}
                            options={[
                                {value: '', label: 'Select a user…'},
                                ...users.map((u) => ({
                                    value: String(u.id),
                                    label: `${u.first_name} ${u.last_name}`.trim() || u.email || `User ${u.id}`,
                                })),
                            ]}/>
                )}
            </div>
            <Input label="Expires (optional)" type="date" value={expiresAt}
                   onChange={(e) => setExpiresAt(e.target.value)} hint="Leave blank for no expiry."/>
            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button onClick={submit} loading={issue.isPending} disabled={!name.trim() || !userId}>
                    Issue key
                </Button>
            </div>
        </div>
    );
}
