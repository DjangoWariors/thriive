import {useEffect, useState} from 'react';
import {Link} from 'react-router';
import {useForm, Controller} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Plus, Pencil, UserX, UserCheck, Search, Users as UsersIcon, Upload, Download, UserCog, X} from 'lucide-react';
import {
    useUsers,
    useRoles,
    useDepartments,
    useCreateUser,
    useUpdateUser,
    useDeactivateUser,
    useReactivateUser,
} from '../../hooks/useAdmin';
import {useEntityTypes} from '../../hooks/useEntities';
import {useRBAC} from '../../hooks/useRBAC';
import type {AdminUserPayload, UserListParams} from '../../types/admin';
import type {User} from '../../types/auth';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Avatar} from '../../components/ui/Avatar';
import {Modal} from '../../components/ui/Modal';
import {EmptyState} from '../../components/ui/EmptyState';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {Pagination} from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {UserDetailDrawer} from '../../components/admin/UserDetailDrawer';
import {UserBulkImportDialog} from '../../components/admin/UserBulkImportDialog';
import {BulkRolesDialog} from '../../components/admin/BulkRolesDialog';
import {adminService} from '../../services/adminService';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {formatRelative} from '../../utils/format';
import {cn} from '../../utils/cn';


const userSchema = z
    .object({
        first_name: z.string().min(1, 'First name is required'),
        last_name: z.string(),
        email: z.string(),
        mobile: z.string(),
        employee_id: z.string(),
        designation: z.string(),
        department: z.string(),
        password: z.string(),
        role_ids: z.array(z.number()),
    })
    .refine((d) => Boolean(d.email.trim() || d.mobile.trim() || d.employee_id.trim()), {
        message: 'Provide at least one of email, mobile, or employee ID.',
        path: ['email'],
    });

type UserFormValues = z.infer<typeof userSchema>;

type StatusFilter = 'active' | 'inactive' | 'all';

export default function UsersPage() {
    const [search, setSearch] = useState('');
    const [role, setRole] = useState('');
    const [status, setStatus] = useState<StatusFilter>('active');
    const [entityType, setEntityType] = useState('');
    const [department, setDepartment] = useState('');
    const [page, setPage] = useState(1);
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<User | null>(null);
    const [deactivating, setDeactivating] = useState<User | null>(null);
    const [viewing, setViewing] = useState<User | null>(null);
    const [importOpen, setImportOpen] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [rolesOpen, setRolesOpen] = useState(false);

    const {canWrite} = useRBAC();
    const writable = canWrite('user_management');


    const onFilter = <T, >(setter: (v: T) => void) => (value: T) => {
        setter(value);
        setPage(1);
    };

    const {data: rolesResp} = useRoles();
    const {data: typesResp} = useEntityTypes();
    const {data: departments} = useDepartments();

    const params: UserListParams = {
        page,
        status,
        ...(search ? {search} : {}),
        ...(role ? {role} : {}),
        ...(entityType ? {entity_type: entityType} : {}),
        ...(department ? {department} : {}),
    };
    const {data: usersResp, isLoading} = useUsers(params);
    const deactivate = useDeactivateUser();
    const reactivate = useReactivateUser();

    const users = usersResp?.results ?? [];


    useEffect(() => {
        setSelectedIds(new Set());
    }, [page, status, search, role, entityType, department]);

    const allOnPageSelected = users.length > 0 && users.every((u) => selectedIds.has(u.id));
    const toggleOne = (id: number) =>
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    const toggleAllOnPage = () =>
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (allOnPageSelected) users.forEach((u) => next.delete(u.id));
            else users.forEach((u) => next.add(u.id));
            return next;
        });
    const checkedUserIds = Array.from(selectedIds);

    const roleOptions = [
        {value: '', label: 'All roles'},
        ...(rolesResp?.results ?? []).map((r) => ({value: r.code, label: r.name})),
    ];
    const typeOptions = [
        {value: '', label: 'All entity types'},
        ...(typesResp?.results ?? []).map((t) => ({value: t.code, label: t.name})),
    ];
    const deptOptions = [
        {value: '', label: 'All departments'},
        ...(departments ?? []).map((d) => ({value: d, label: d})),
    ];
    const statusOptions: { value: StatusFilter; label: string }[] = [
        {value: 'active', label: 'Active'},
        {value: 'inactive', label: 'Inactive'},
        {value: 'all', label: 'All statuses'},
    ];

    const openCreate = () => {
        setEditing(null);
        setFormOpen(true);
    };
    const openEdit = (u: User) => {
        setEditing(u);
        setFormOpen(true);
    };

    const confirmDeactivate = () => {
        if (!deactivating) return;
        deactivate.mutate(deactivating.id, {
            onSuccess: () => {
                notify.success(`${deactivating.first_name} deactivated`);
                setDeactivating(null);
            },
            onError: (e) => notify.error(apiErrorMessage(e, 'Could not deactivate user')),
        });
    };

    const handleReactivate = (u: User) => {
        reactivate.mutate(u.id, {
            onSuccess: () => notify.success(`${u.first_name} reactivated`),
            onError: (e) => notify.error(apiErrorMessage(e, 'Could not reactivate user')),
        });
    };

    const handleExport = async () => {
        setExporting(true);
        try {

            const filters: UserListParams = {...params};
            delete filters.page;
            const blob = await adminService.exportUsers(filters);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'users.csv';
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            notify.error(apiErrorMessage(e, 'Could not export users'));
        } finally {
            setExporting(false);
        }
    };

    return (
        <div className="p-6">
            <PageHeader
                title="Users"
                description="Manage user accounts and role assignments."
                actions={<>
                    <Button
                        variant="outline"
                        onClick={handleExport}
                        loading={exporting}
                        icon={<Download className="h-4 w-4"/>}
                    >
                        Export
                    </Button>
                    {writable && (
                        <Button
                            variant="outline"
                            onClick={() => setImportOpen(true)}
                            icon={<Upload className="h-4 w-4"/>}
                        >
                            Import
                        </Button>
                    )}
                    {writable && (
                        <Button onClick={openCreate} icon={<Plus className="h-4 w-4"/>}>
                            Create User
                        </Button>
                    )}
                </>}
            />

            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Input
                    placeholder="Search by name, email, mobile…"
                    value={search}
                    onChange={(e) => onFilter(setSearch)(e.target.value)}
                    leftIcon={<Search className="h-4 w-4"/>}
                />
                <Select
                    options={roleOptions}
                    value={role}
                    onChange={(e) => onFilter(setRole)(e.target.value)}
                />
                <Select
                    options={typeOptions}
                    value={entityType}
                    onChange={(e) => onFilter(setEntityType)(e.target.value)}
                />
                <Select
                    options={deptOptions}
                    value={department}
                    onChange={(e) => onFilter(setDepartment)(e.target.value)}
                />
                <Select
                    options={statusOptions}
                    value={status}
                    onChange={(e) => onFilter(setStatus)(e.target.value as StatusFilter)}
                />
            </div>

            {writable && checkedUserIds.length > 0 && (
                <div
                    className="mb-3 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary-50 px-3 py-2">
                    <span className="text-sm font-medium text-primary">{checkedUserIds.length} selected</span>
                    <div className="ml-auto flex items-center gap-1">
                        <Button size="sm" variant="outline" onClick={() => setRolesOpen(true)}
                                icon={<UserCog className="h-4 w-4"/>}>
                            Assign roles
                        </Button>
                        <button
                            type="button"
                            title="Clear selection"
                            onClick={() => setSelectedIds(new Set())}
                            className="rounded-lg p-1 text-gray-400 hover:text-gray-600"
                        >
                            <X className="h-4 w-4"/>
                        </button>
                    </div>
                </div>
            )}

            {isLoading ? (
                <TableSkeleton/>
            ) : users.length === 0 ? (
                <Card>
                    <EmptyState
                        icon={UsersIcon}
                        title="No users found"
                        description="Create the first user to get started."
                    />
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={users}
                        rowKey={(u) => u.id}
                        onRowClick={(u) => setViewing(u)}
                        columns={[
                            {header: (
                                <input
                                    type="checkbox"
                                    checked={allOnPageSelected}
                                    onChange={toggleAllOnPage}
                                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary/30"
                                    aria-label="Select all on page"
                                />
                            ), render: (u) => (
                                <span onClick={(e) => e.stopPropagation()}>
                                    <input
                                        type="checkbox"
                                        checked={selectedIds.has(u.id)}
                                        onChange={() => toggleOne(u.id)}
                                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary/30"
                                        aria-label={`Select ${u.first_name}`}
                                    />
                                </span>
                            )},
                            {header: 'Name', render: (u) => (
                                <div className="flex items-center gap-3">
                                    <Avatar name={`${u.first_name} ${u.last_name}`.trim() || u.email || '?'}
                                            size="sm"/>
                                    <span className="font-medium text-gray-900">
                                        {`${u.first_name} ${u.last_name}`.trim() || '—'}
                                    </span>
                                </div>
                            )},
                            {header: 'Email', render: (u) => <span className="text-gray-600">{u.email || '—'}</span>},
                            {header: 'Mobile', render: (u) => <span className="text-gray-600">{u.mobile || '—'}</span>},
                            {header: 'Employee Id', render: (u) => <span className="text-gray-600">{u.employee_id || '—'}</span>},
                            {header: 'Entity', render: (u) => (
                                u.entity_info ? (
                                    <Link
                                        to={`/network/people/${u.entity_info.id}`}
                                        onClick={(e) => e.stopPropagation()}
                                        className="text-primary hover:underline"
                                    >
                                        {u.entity_info.name}
                                    </Link>
                                ) : (
                                    <span className="text-gray-400">—</span>
                                )
                            )},
                            {header: 'Roles', render: (u) => (
                                <div className="flex flex-wrap gap-1">
                                    {u.active_roles.length > 0 ? (
                                        u.active_roles.map((r) => (
                                            <Badge key={r.code} variant="info">
                                                {r.name}
                                            </Badge>
                                        ))
                                    ) : (
                                        <span className="text-gray-400">—</span>
                                    )}
                                </div>
                            )},
                            {header: 'Status', render: (u) => (
                                u.is_active === false
                                    ? <Badge variant="default">Inactive</Badge>
                                    : <Badge variant="success">Active</Badge>
                            )},
                            {header: 'Last Login', render: (u) => (
                                <span className="text-gray-600">{u.last_login ? formatRelative(u.last_login) : 'Never'}</span>
                            )},
                            {header: 'Actions', align: 'right', render: (u) => (
                                <div className="flex justify-end gap-1">
                                    {writable && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Edit ${u.first_name}`}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                openEdit(u);
                                            }}
                                        >
                                            <Pencil className="h-4 w-4"/>
                                        </Button>
                                    )}
                                    {writable && (u.is_active === false ? (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Reactivate ${u.first_name}`}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleReactivate(u);
                                            }}
                                        >
                                            <UserCheck className="h-4 w-4 text-success"/>
                                        </Button>
                                    ) : (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Deactivate ${u.first_name}`}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setDeactivating(u);
                                            }}
                                        >
                                            <UserX className="h-4 w-4 text-danger"/>
                                        </Button>
                                    ))}
                                </div>
                            )},
                        ]}
                    />
                    <Pagination count={usersResp?.count ?? 0} page={page} onPageChange={setPage}/>
                </Card>
            )}

            <UserDetailDrawer
                user={viewing}
                open={viewing !== null}
                onClose={() => setViewing(null)}
                onEdit={writable ? (u) => {
                    setViewing(null);
                    openEdit(u);
                } : undefined}
            />

            {importOpen && <UserBulkImportDialog onClose={() => setImportOpen(false)}/>}

            {rolesOpen && (
                <BulkRolesDialog
                    userIds={checkedUserIds}
                    onClose={() => setRolesOpen(false)}
                    onDone={() => setSelectedIds(new Set())}
                />
            )}

            <Modal
                open={formOpen}
                onClose={() => setFormOpen(false)}
                title={editing ? 'Edit User' : 'Create User'}
                size="2xl"
            >
                <UserForm key={editing?.id ?? 'new'} existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deactivating !== null}
                onClose={() => setDeactivating(null)}
                onConfirm={confirmDeactivate}
                title="Deactivate user"
                message={`Deactivate ${deactivating?.first_name ?? ''} ${deactivating?.last_name ?? ''}? They will no longer be able to log in. This is a soft delete.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </div>
    );
}



function UserForm({existing, onDone}: { existing: User | null; onDone: () => void }) {
    const {data: rolesResp} = useRoles();
    const roles = rolesResp?.results ?? [];
    const create = useCreateUser();
    const update = useUpdateUser();
    const [serverError, setServerError] = useState<string | null>(null);

    const form = useForm<UserFormValues>({
        resolver: zodResolver(userSchema),
        defaultValues: {
            first_name: existing?.first_name ?? '',
            last_name: existing?.last_name ?? '',
            email: existing?.email ?? '',
            mobile: existing?.mobile ?? '',
            employee_id: existing?.employee_id ?? '',
            designation: existing?.designation ?? '',
            department: existing?.department ?? '',
            password: '',
            role_ids: [],
        },
    });

    const {
        register,
        handleSubmit,
        control,
        setValue,
        formState: {errors},
    } = form;


    useEffect(() => {
        if (existing && roles.length > 0) {
            const codes = new Set(existing.active_roles.map((r) => r.code));
            setValue(
                'role_ids',
                roles.filter((r) => codes.has(r.code)).map((r) => r.id),
            );
        }
    }, [existing, roles, setValue]);

    const onSubmit = handleSubmit((values) => {
        setServerError(null);

        const payload: AdminUserPayload = {
            first_name: values.first_name.trim(),
            last_name: values.last_name.trim(),
            email: values.email.trim() || null,
            mobile: values.mobile.trim() || null,
            employee_id: values.employee_id.trim() || null,
            designation: values.designation.trim(),
            department: values.department.trim(),
            role_ids: values.role_ids,
        };
        if (values.password) payload.password = values.password;

        const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save user'));

        if (existing) {
            update.mutate(
                {id: existing.id, payload},
                {
                    onSuccess: () => {
                        notify.success('User updated');
                        onDone();
                    },
                    onError,
                },
            );
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('User created');
                    onDone();
                },
                onError,
            });
        }
    });

    const pending = create.isPending || update.isPending;

    return (
        <form onSubmit={onSubmit} className="space-y-6">
            <FormSection title="Identity">
                <div className="grid grid-cols-2 gap-4">
                    <Input
                        label="First name"
                        placeholder="e.g. Deepa"
                        {...register('first_name')}
                        error={errors.first_name?.message}
                    />
                    <Input label="Last name" placeholder="e.g. Sharma" {...register('last_name')} />
                </div>
            </FormSection>

            <FormSection
                title="Contact & login"
                hint="Provide at least one of email, mobile, or employee ID — it becomes the login identifier."
            >
                <div className="grid grid-cols-3 gap-4">
                    <Input
                        label="Email"
                        type="email"
                        placeholder="name@company.com"
                        {...register('email')}
                        error={errors.email?.message}
                    />
                    <Input label="Mobile" placeholder="9876543210" {...register('mobile')} />
                    <Input label="Employee ID" placeholder="EMP001" {...register('employee_id')} />
                </div>
            </FormSection>

            <FormSection title="Organization">
                <div className="grid grid-cols-2 gap-4">
                    <Input
                        label="Designation"
                        placeholder="e.g. Area Sales Executive"
                        {...register('designation')}
                    />
                    <Input label="Department" placeholder="e.g. Sales" {...register('department')} />
                </div>
            </FormSection>

            <FormSection title="Security">
                <Input
                    label={existing ? 'Reset password' : 'Password'}
                    type="password"
                    placeholder="••••••••"
                    {...register('password')}
                    hint={existing ? 'Leave blank to keep current.' : 'Leave blank for OTP-only login.'}
                />
            </FormSection>

            <FormSection title="Roles">
                {roles.length === 0 ? (
                    <p className="text-sm text-gray-400">No roles available — create roles first.</p>
                ) : (
                    <Controller
                        control={control}
                        name="role_ids"
                        render={({field}) => (
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                                {roles.map((r) => {
                                    const checked = field.value.includes(r.id);
                                    return (
                                        <label
                                            key={r.id}
                                            className={cn(
                                                'flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors',
                                                checked
                                                    ? 'border-primary bg-primary-50 text-primary'
                                                    : 'border-gray-200 text-gray-800 hover:bg-gray-50',
                                            )}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={checked}
                                                onChange={() =>
                                                    field.onChange(
                                                        checked
                                                            ? field.value.filter((id) => id !== r.id)
                                                            : [...field.value, r.id],
                                                    )
                                                }
                                                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                                            />
                                            <span>{r.name}</span>
                                        </label>
                                    );
                                })}
                            </div>
                        )}
                    />
                )}
            </FormSection>

            {serverError && (
                <p className="rounded-lg bg-danger-50 px-3 py-2 text-sm text-danger">{serverError}</p>
            )}

            <div
                className="sticky bottom-0 -mx-6 -mb-4 flex justify-end gap-3 border-t border-gray-100 bg-white px-6 pb-4 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>
                    Cancel
                </Button>
                <Button type="submit" loading={pending}>
                    {existing ? 'Save changes' : 'Create user'}
                </Button>
            </div>
        </form>
    );
}


function FormSection({
                         title,
                         hint,
                         children,
                     }: {
    title: string;
    hint?: string;
    children: React.ReactNode;
}) {
    return (
        <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h3>
            {hint && <p className="mb-3 mt-0.5 text-xs text-gray-500">{hint}</p>}
            <div className={hint ? '' : 'mt-3'}>{children}</div>
        </section>
    );
}
