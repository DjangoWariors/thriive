import {Fragment, useState} from 'react';
import {useForm, Controller} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Plus, Pencil, Trash2, Shield, Lock} from 'lucide-react';
import {useRoles, useCreateRole, useUpdateRole, useDeleteRole, usePermissionCatalog} from '../../hooks/useAdmin';
import {useRBAC} from '../../hooks/useRBAC';
import type {PermissionCatalog, Role, RolePayload} from '../../types/admin';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Textarea} from '../../components/ui/Textarea';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Modal} from '../../components/ui/Modal';
import {Spinner} from '../../components/ui/Spinner';
import {EmptyState} from '../../components/ui/EmptyState';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';

function buildPermissions(existing: Role | null, catalog: PermissionCatalog): Record<string, string> {
    const out: Record<string, string> = {};
    for (const group of catalog.groups) {
        for (const res of group.resources) {
            const current = existing?.permissions?.[res.code];
            out[res.code] = current && res.levels.includes(current) ? current : 'none';
        }
    }
    return out;
}


const roleSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    code: z.string().min(1, 'Code is required'),
    description: z.string(),
    permissions: z.record(z.string()),
});

type RoleFormValues = z.infer<typeof roleSchema>;

export default function RolesPage() {
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<Role | null>(null);
    const [deleting, setDeleting] = useState<Role | null>(null);

    const {canWrite} = useRBAC();
    const writable = canWrite('role_management');

    const {data: rolesResp, isLoading} = useRoles();
    const del = useDeleteRole();

    const roles = rolesResp?.results ?? [];

    const confirmDelete = () => {
        if (!deleting) return;
        del.mutate(deleting.id, {
            onSuccess: () => {
                notify.success(`Role "${deleting.name}" deleted`);
                setDeleting(null);
            },
            onError: (e) => notify.error(apiErrorMessage(e, 'Could not delete role')),
        });
    };

    return (
        <div className="p-6">
            <PageHeader
                title="Roles"
                description="Define roles and their permission matrix."
                actions={<>{writable && (
                    <Button
                        onClick={() => {
                            setEditing(null);
                            setFormOpen(true);
                        }}
                        icon={<Plus className="h-4 w-4"/>}
                    >
                        Create Role
                    </Button>
                )}</>}
            />

            {isLoading ? (
                <TableSkeleton/>
            ) : roles.length === 0 ? (
                <Card>
                    <EmptyState
                        icon={Shield}
                        title="No roles yet"
                        description="Create a role to define its permission matrix."
                    />
                </Card>
            ) : (
                <Card padding="none">
                    <table className="w-full text-left text-sm">
                        <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
                        <tr>
                            <th className="px-4 py-3">Name</th>
                            <th className="px-4 py-3">Code</th>
                            <th className="px-4 py-3">Description</th>
                            <th className="px-4 py-3">Type</th>
                            {writable && <th className="px-4 py-3 text-right">Actions</th>}
                        </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                        {roles.map((r) => (
                            <tr key={r.id} className="hover:bg-gray-50">
                                <td className="px-4 py-3 font-medium text-gray-900">{r.name}</td>
                                <td className="px-4 py-3">
                                    <code
                                        className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{r.code}</code>
                                </td>
                                <td className="max-w-xs truncate px-4 py-3 text-gray-600">{r.description || '—'}</td>
                                <td className="px-4 py-3">
                                    {r.is_system_role ? (
                                        <Badge variant="purple">
                                            <Lock className="mr-1 inline h-3 w-3"/>
                                            System
                                        </Badge>
                                    ) : (
                                        <Badge variant="default">Custom</Badge>
                                    )}
                                </td>
                                {writable && (
                                    <td className="px-4 py-3">
                                        <div className="flex justify-end gap-1">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => {
                                                    setEditing(r);
                                                    setFormOpen(true);
                                                }}
                                            >
                                                <Pencil className="h-4 w-4"/>
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => setDeleting(r)}
                                                disabled={r.is_system_role}
                                                title={r.is_system_role ? 'System roles cannot be deleted' : 'Delete role'}
                                            >
                                                <Trash2 className="h-4 w-4 text-danger"/>
                                            </Button>
                                        </div>
                                    </td>
                                )}
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </Card>
            )}

            <Modal
                open={formOpen}
                onClose={() => setFormOpen(false)}
                title={editing ? `Edit Role: ${editing.name}` : 'Create Role'}
                size="3xl"
            >
                <RoleForm existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={confirmDelete}
                title="Delete role"
                message={`Delete role "${deleting?.name ?? ''}"? Users assigned this role will lose its permissions. This cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
            />
        </div>
    );
}


function RoleForm({existing, onDone}: { existing: Role | null; onDone: () => void }) {
    const {data: catalog, isLoading} = usePermissionCatalog();
    if (isLoading || !catalog) {
        return (
            <div className="flex justify-center py-10">
                <Spinner size="lg"/>
            </div>
        );
    }
    return <RoleFormInner existing={existing} onDone={onDone} catalog={catalog}/>;
}


function RoleFormInner({existing, onDone, catalog}: {
    existing: Role | null;
    onDone: () => void;
    catalog: PermissionCatalog;
}) {
    const create = useCreateRole();
    const update = useUpdateRole();
    const [serverError, setServerError] = useState<string | null>(null);

    const allCodes = catalog.groups.flatMap((g) => g.resources.map((r) => r.code));

    const form = useForm<RoleFormValues>({
        resolver: zodResolver(roleSchema),
        defaultValues: {
            name: existing?.name ?? '',
            code: existing?.code ?? '',
            description: existing?.description ?? '',
            permissions: buildPermissions(existing, catalog),
        },
    });

    const {
        register,
        handleSubmit,
        control,
        formState: {errors},
    } = form;

    const onSubmit = handleSubmit((values) => {
        setServerError(null);
        const payload: RolePayload = {
            name: values.name.trim(),
            code: values.code.trim(),
            description: values.description.trim(),
            permissions: values.permissions,
        };

        const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save role'));

        if (existing) {
            update.mutate(
                {id: existing.id, payload},
                {
                    onSuccess: () => {
                        notify.success('Role updated');
                        onDone();
                    },
                    onError,
                },
            );
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('Role created');
                    onDone();
                },
                onError,
            });
        }
    });

    const pending = create.isPending || update.isPending;

    return (
        <form onSubmit={onSubmit} className="space-y-5">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" {...register('name')} error={errors.name?.message}
                       placeholder="Area Sales Manager"/>
                <Input
                    label="Code"
                    {...register('code')}
                    error={errors.code?.message}
                    placeholder="asm"
                    disabled={!!existing}
                    hint={existing ? 'Code cannot be changed.' : undefined}
                />
            </div>
            <Textarea label="Description" rows={2} {...register('description')} />

            <Controller
                control={control}
                name="permissions"
                render={({field}) => (
                    <div>
                        <div className="mb-2 flex items-center justify-between">
                            <p className="text-sm font-medium text-gray-700">Permission matrix</p>
                            <div className="flex gap-2">
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => field.onChange(Object.fromEntries(allCodes.map((c) => [c, 'none'])))}
                                >
                                    Set all None
                                </Button>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => field.onChange(Object.fromEntries(allCodes.map((c) => [c, 'full'])))}
                                >
                                    Set all Full
                                </Button>
                            </div>
                        </div>

                        <div className="overflow-x-auto rounded-lg border border-gray-200">
                            <table className="w-full text-left text-xs">
                                <thead className="bg-gray-50 text-gray-500">
                                <tr>
                                    <th className="sticky left-0 bg-gray-50 px-3 py-2 font-semibold">Resource</th>
                                    {catalog.levels.map((lvl) => (
                                        <th key={lvl} className="px-2 py-2 text-center font-medium">
                                            {catalog.level_labels[lvl] ?? lvl}
                                        </th>
                                    ))}
                                </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                {catalog.groups.map((group) => (
                                    <Fragment key={group.group}>
                                        <tr className="bg-gray-100">
                                            <td
                                                colSpan={catalog.levels.length + 1}
                                                className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                                            >
                                                {group.group}
                                            </td>
                                        </tr>
                                        {group.resources.map((res) => (
                                            <tr key={res.code} className="hover:bg-gray-50">
                                                <td className="sticky left-0 bg-white px-3 py-2 font-medium text-gray-800">
                                                    {res.label}
                                                </td>
                                                {catalog.levels.map((lvl) => (
                                                    <td key={lvl} className="px-2 py-2 text-center">
                                                        {res.levels.includes(lvl) ? (
                                                            <input
                                                                type="radio"
                                                                name={`perm-${res.code}`}
                                                                checked={field.value[res.code] === lvl}
                                                                onChange={() => field.onChange({...field.value, [res.code]: lvl})}
                                                                className="h-4 w-4 border-gray-300 text-primary focus:ring-primary"
                                                            />
                                                        ) : null}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </Fragment>
                                ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            />

            {serverError && <p className="text-sm text-danger">{serverError}</p>}

            <div
                className="sticky bottom-0 -mx-6 -mb-4 flex justify-end gap-3 border-t border-gray-100 bg-white px-6 pb-4 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>
                    Cancel
                </Button>
                <Button type="submit" loading={pending}>
                    {existing ? 'Save changes' : 'Create role'}
                </Button>
            </div>
        </form>
    );
}
