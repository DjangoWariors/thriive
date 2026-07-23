import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Plus, Pencil, Trash2, CloudUpload, PlugZap} from 'lucide-react';
import {reportService} from '../../services/reportService';
import type {DeliveryTarget, DeliveryTargetKind, DeliveryTargetPayload} from '../../types/reports';
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
import {apiErrorMessage} from '../../utils/apiError';

const KEY = ['reports', 'delivery-targets'] as const;

export function DeliveryTargetsTab() {
    const qc = useQueryClient();
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<DeliveryTarget | null>(null);
    const [deleting, setDeleting] = useState<DeliveryTarget | null>(null);
    const [testingId, setTestingId] = useState<number | null>(null);

    const {data, isLoading} = useQuery({queryKey: KEY, queryFn: () => reportService.listDeliveryTargets()});
    const remove = useMutation({
        mutationFn: (id: number) => reportService.deleteDeliveryTarget(id),
        onSuccess: () => void qc.invalidateQueries({queryKey: KEY}),
    });
    const targets = data?.results ?? [];

    async function runTest(t: DeliveryTarget) {
        setTestingId(t.id);
        try {
            const result = await reportService.testDeliveryTarget(t.id);
            if (result.ok) notify.success(`Connected — wrote ${result.written}`);
            else notify.error(result.error ?? 'Connection failed');
        } catch (e) {
            notify.error(apiErrorMessage(e, 'Connection failed'));
        } finally {
            setTestingId(null);
        }
    }

    return (
        <>
            <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-sm text-gray-500">
                    Where scheduled extracts are pushed — the client's data lake (S3) or an SFTP drop.
                </p>
                <Button icon={<Plus className="h-4 w-4"/>} onClick={() => {
                    setEditing(null);
                    setFormOpen(true);
                }}>
                    Add Target
                </Button>
            </div>

            <HowThisWorks storageKey="delivery-targets-help" className="mb-6">
                A report schedule with delivery = “Delivery target” generates one extract per run and pushes
                the file here — achievements, KPI actuals or payout summaries flowing nightly into the
                client's data lake. Connection details live in this record; the secret itself is read from
                an environment variable on this server (name it below), never stored in the database.
                Lake systems that prefer pull can use <code>/api/v1/reports/datasets/&#123;code&#125;/</code> instead.
            </HowThisWorks>

            {isLoading ? (
                <TableSkeleton/>
            ) : targets.length === 0 ? (
                <Card>
                    <EmptyState icon={CloudUpload} title="No delivery targets yet"
                                description="Add an S3 bucket or SFTP drop to start pushing scheduled extracts."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={targets}
                        rowKey={(t) => t.id}
                        columns={[
                            {header: 'Code', render: (t) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{t.code}</code>
                            )},
                            {header: 'Name', render: (t) => <span className="font-medium text-gray-900">{t.name}</span>},
                            {header: 'Kind', render: (t) => (
                                <Badge variant={t.kind === 's3' ? 'info' : 'purple'}>{t.kind.toUpperCase()}</Badge>
                            )},
                            {header: 'Destination', render: (t) => (
                                <span className="text-gray-600">
                                    {t.kind === 's3'
                                        ? `s3://${String(t.config.bucket ?? '?')}/${String(t.config.prefix ?? '')}`
                                        : `${String(t.config.host ?? '?')}:${String(t.config.port ?? 22)}${String(t.config.path ?? '')}`}
                                </span>
                            )},
                            {header: 'Secret env var', render: (t) => (
                                <span className="text-gray-500">
                                    {t.credential_env ? <code className="text-xs">{t.credential_env}</code> : '—'}
                                </span>
                            )},
                            {header: 'Actions', align: 'right', render: (t) => (
                                <div className="flex justify-end gap-1">
                                    <Button variant="outline" size="sm" loading={testingId === t.id}
                                            icon={<PlugZap className="h-3.5 w-3.5"/>}
                                            onClick={() => void runTest(t)}>
                                        Test
                                    </Button>
                                    <Button variant="ghost" size="sm" aria-label={`Edit ${t.code}`} onClick={() => {
                                        setEditing(t);
                                        setFormOpen(true);
                                    }}>
                                        <Pencil className="h-4 w-4"/>
                                    </Button>
                                    <Button variant="ghost" size="sm" aria-label={`Deactivate ${t.code}`}
                                            onClick={() => setDeleting(t)}>
                                        <Trash2 className="h-4 w-4 text-danger"/>
                                    </Button>
                                </div>
                            )},
                        ]}
                    />
                </Card>
            )}

            <Modal open={formOpen} onClose={() => setFormOpen(false)}
                   title={editing ? `Edit ${editing.code}` : 'Add Delivery Target'} size="lg">
                <TargetForm existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={() => {
                    if (!deleting) return;
                    remove.mutate(deleting.id, {
                        onSuccess: () => {
                            notify.success(`${deleting.code} deactivated`);
                            setDeleting(null);
                        },
                        onError: (e) => {
                            notify.error(apiErrorMessage(e, 'Could not deactivate — schedules may still use it'));
                            setDeleting(null);
                        },
                    });
                }}
                title="Deactivate delivery target"
                message={`Deactivate ${deleting?.code ?? ''}? Schedules pointing at it will stop delivering.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </>
    );
}

function TargetForm({existing, onDone}: { existing: DeliveryTarget | null; onDone: () => void }) {
    const qc = useQueryClient();
    const [kind, setKind] = useState<DeliveryTargetKind>(existing?.kind ?? 's3');
    const [code, setCode] = useState(existing?.code ?? '');
    const [name, setName] = useState(existing?.name ?? '');
    const [credentialEnv, setCredentialEnv] = useState(existing?.credential_env ?? '');
    const cfg = existing?.config ?? {};
    const [bucket, setBucket] = useState(String(cfg.bucket ?? ''));
    const [prefix, setPrefix] = useState(String(cfg.prefix ?? ''));
    const [region, setRegion] = useState(String(cfg.region ?? ''));
    const [accessKeyId, setAccessKeyId] = useState(String(cfg.access_key_id ?? ''));
    const [host, setHost] = useState(String(cfg.host ?? ''));
    const [port, setPort] = useState(String(cfg.port ?? '22'));
    const [path, setPath] = useState(String(cfg.path ?? ''));
    const [username, setUsername] = useState(String(cfg.username ?? ''));
    const [serverError, setServerError] = useState<string | null>(null);

    const save = useMutation({
        mutationFn: (payload: DeliveryTargetPayload) =>
            existing
                ? reportService.updateDeliveryTarget(existing.id, payload)
                : reportService.createDeliveryTarget(payload),
        onSuccess: () => {
            void qc.invalidateQueries({queryKey: KEY});
            notify.success(existing ? 'Target updated' : 'Target created');
            onDone();
        },
        onError: (e) => setServerError(apiErrorMessage(e, 'Could not save target')),
    });

    const submit = () => {
        setServerError(null);
        const config = kind === 's3'
            ? {bucket, prefix, region, ...(accessKeyId ? {access_key_id: accessKeyId} : {})}
            : {host, port: Number(port) || 22, path, username};
        save.mutate({code: code.trim(), name: name.trim(), kind, config, credential_env: credentialEnv.trim()});
    };

    const valid = code.trim() && name.trim() && (kind === 's3' ? bucket.trim() : host.trim());

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" value={name} onChange={(e) => setName(e.target.value)}
                       placeholder="e.g. Client data lake"/>
                <Input label="Code" value={code} disabled={!!existing}
                       onChange={(e) => setCode(e.target.value.toUpperCase().replace(/\s+/g, '_'))}
                       hint={existing ? 'Code cannot be changed.' : 'Unique identifier.'} placeholder="LAKE"/>
                <Select label="Kind" value={kind} onChange={(e) => setKind(e.target.value as DeliveryTargetKind)}
                        options={[{value: 's3', label: 'Amazon S3'}, {value: 'sftp', label: 'SFTP'}]}/>
                <Input label="Secret env var" value={credentialEnv}
                       onChange={(e) => setCredentialEnv(e.target.value)}
                       hint="Name of the environment variable on this server holding the secret."
                       placeholder="THRIIVE_LAKE_SECRET"/>
            </div>

            {kind === 's3' ? (
                <div className="grid grid-cols-2 gap-4 rounded-lg border border-gray-200 p-4">
                    <Input label="Bucket" value={bucket} onChange={(e) => setBucket(e.target.value)}
                           placeholder="client-data-lake"/>
                    <Input label="Prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)}
                           placeholder="thriive/extracts"/>
                    <Input label="Region" value={region} onChange={(e) => setRegion(e.target.value)}
                           placeholder="ap-south-1"/>
                    <Input label="Access key id (optional)" value={accessKeyId}
                           onChange={(e) => setAccessKeyId(e.target.value)}
                           hint="Leave blank to use the EC2 instance role."/>
                </div>
            ) : (
                <div className="grid grid-cols-2 gap-4 rounded-lg border border-gray-200 p-4">
                    <Input label="Host" value={host} onChange={(e) => setHost(e.target.value)}
                           placeholder="sftp.client.com"/>
                    <Input label="Port" type="number" value={port} onChange={(e) => setPort(e.target.value)}/>
                    <Input label="Remote path" value={path} onChange={(e) => setPath(e.target.value)}
                           placeholder="/inbound/thriive"/>
                    <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)}/>
                </div>
            )}

            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button onClick={submit} loading={save.isPending} disabled={!valid}>
                    {existing ? 'Save changes' : 'Create target'}
                </Button>
            </div>
        </div>
    );
}
