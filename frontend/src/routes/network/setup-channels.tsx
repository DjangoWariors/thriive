import {useState} from 'react';
import {useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Plus, Pencil, Trash2, Route} from 'lucide-react';
import {
    useChannels,
    useCreateChannel,
    useUpdateChannel,
    useDeactivateChannel,
} from '../../hooks/useEntities';
import {useRBAC} from '../../hooks/useRBAC';
import type {Channel, CreateChannelPayload} from '../../types/entity';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Card} from '../../components/ui/Card';
import {Modal} from '../../components/ui/Modal';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';


function slugify(value: string): string {
    return value.toUpperCase().trim().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

const channelSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    code: z.string().min(1, 'Code is required').regex(/^[A-Z0-9_]+$/, 'Use A–Z, 0–9, underscore'),
    description: z.string(),
});

type ChannelFormValues = z.infer<typeof channelSchema>;


export default function ChannelsPage() {
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<Channel | null>(null);
    const [deleting, setDeleting] = useState<Channel | null>(null);

    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const {data: resp, isLoading} = useChannels();
    const deactivate = useDeactivateChannel();
    const channels = resp?.results ?? [];

    const confirmDelete = () => {
        if (!deleting) return;
        deactivate.mutate(deleting.id, {
            onSuccess: () => {
                notify.success(`${deleting.code} deactivated`);
                setDeleting(null);
            },
            onError: (e) => {
                notify.error(apiErrorMessage(e, 'Could not deactivate channel'));
                setDeleting(null);
            },
        });
    };

    return (
        <div className="">
            <PageHeader
                title="Sales Channels"
                description="The ways your products reach customers — like General Trade, Modern Trade or Rural. You can sort people and schemes by channel."
                actions={<>{writable && (
                    <Button
                        icon={<Plus className="h-4 w-4"/>}
                        onClick={() => {
                            setEditing(null);
                            setFormOpen(true);
                        }}
                    >
                        Add Channel
                    </Button>
                )}</>}
            />

            <HowThisWorks storageKey="channels-help" className="mb-6">
                A channel is just the path your products take to reach the customer — General Trade (the
                corner shops), Modern Trade (the supermarkets), Rural, and so on. Tag your role types and
                incentive schemes with a channel and the right rules follow the right part of your network.
                Most businesses get by with only a handful.
            </HowThisWorks>

            {isLoading ? (
                <TableSkeleton/>
            ) : channels.length === 0 ? (
                <Card>
                    <EmptyState icon={Route} title="No channels yet"
                                description="Add your first one to start sorting your network by how products reach customers."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={channels}
                        rowKey={(c) => c.id}
                        columns={[
                            {header: 'Code', render: (c) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{c.code}</code>
                            )},
                            {header: 'Name', render: (c) => <span className="font-medium text-gray-900">{c.name}</span>},
                            {header: 'Description', render: (c) => <span className="text-gray-600">{c.description || '—'}</span>},
                            ...(writable ? [{
                                header: 'Actions', align: 'right' as const,
                                render: (c: Channel) => (
                                    <div className="flex justify-end gap-1">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Edit ${c.code}`}
                                            onClick={() => {
                                                setEditing(c);
                                                setFormOpen(true);
                                            }}
                                        >
                                            <Pencil className="h-4 w-4"/>
                                        </Button>
                                        <Button variant="ghost" size="sm" aria-label={`Deactivate ${c.code}`}
                                                onClick={() => setDeleting(c)}>
                                            <Trash2 className="h-4 w-4 text-danger"/>
                                        </Button>
                                    </div>
                                ),
                            }] : []),
                        ]}
                    />
                </Card>
            )}

            <Modal
                open={formOpen}
                onClose={() => setFormOpen(false)}
                title={editing ? `Edit ${editing.code}` : 'Add Channel'}
                size="md"
            >
                <ChannelForm existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={confirmDelete}
                title="Deactivate channel"
                message={`Deactivate ${deleting?.code ?? ''} (${deleting?.name ?? ''})? Channels still used by entities or types cannot be removed.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </div>
    );
}


function ChannelForm({existing, onDone}: {existing: Channel | null; onDone: () => void}) {
    const create = useCreateChannel();
    const update = useUpdateChannel();
    const [serverError, setServerError] = useState<string | null>(null);
    const [codeEdited, setCodeEdited] = useState(existing !== null);

    const {
        register,
        handleSubmit,
        setValue,
        formState: {errors},
    } = useForm<ChannelFormValues>({
        resolver: zodResolver(channelSchema),
        defaultValues: {
            name: existing?.name ?? '',
            code: existing?.code ?? '',
            description: existing?.description ?? '',
        },
    });

    const onSubmit = handleSubmit((values) => {
        setServerError(null);
        const payload: CreateChannelPayload = {
            name: values.name.trim(),
            code: values.code.trim(),
            description: values.description.trim(),
        };
        const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save channel'));

        if (existing) {
            // Code is immutable once created.
            update.mutate(
                {id: existing.id, payload: {name: payload.name, description: payload.description}},
                {
                    onSuccess: () => {
                        notify.success('Channel updated');
                        onDone();
                    },
                    onError,
                },
            );
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('Channel created');
                    onDone();
                },
                onError,
            });
        }
    });

    const pending = create.isPending || update.isPending;

    return (
        <form onSubmit={onSubmit} className="space-y-4">
            <Input
                label="Name"
                {...register('name', {
                    onChange: (e) => {
                        if (!codeEdited) setValue('code', slugify(e.target.value));
                    },
                })}
                error={errors.name?.message}
                placeholder="e.g. Modern Trade"
            />
            <Input
                label="Code"
                {...register('code', {onChange: () => setCodeEdited(true)})}
                error={errors.code?.message}
                disabled={!!existing}
                hint={existing ? 'Code cannot be changed.' : 'Auto-filled from name — edit if needed.'}
            />
            <Input label="Description" {...register('description')} placeholder="Optional"/>

            {serverError && <p className="text-sm text-danger">{serverError}</p>}

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button type="submit" loading={pending}>
                    {existing ? 'Save changes' : 'Create channel'}
                </Button>
            </div>
        </form>
    );
}
