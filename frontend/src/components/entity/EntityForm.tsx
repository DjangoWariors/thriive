import {useEffect, useMemo, useState} from 'react';
import {z} from 'zod';
import {notify} from '../../utils/notify';
import {X, Check, LogIn, Award} from 'lucide-react';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Input} from '../ui/Input';
import {Select} from '../ui/Select';
import {Badge} from '../ui/Badge';
import {Spinner} from '../ui/Spinner';
import {cn} from '../../utils/cn';
import {apiErrorMessage} from '../../utils/apiError';
import {
    useBlueprint,
    useCreateEntity,
    useUpdateEntity,
    useEntitySearch,
    useChannels,
    useGeographyTypes,
} from '../../hooks/useEntities';
import {GeoNodeCombobox, type GeoSelection} from './GeoNodeCombobox';
import type {
    AttributeField,
    CreateEntityPayload,
    Entity,
    EntityListItem,
    EntityType,
    UpdateEntityPayload,
} from '../../types/entity';


export function buildZodSchema(
    fields: AttributeField[],
): z.ZodObject<Record<string, z.ZodTypeAny>> {
    const shape: Record<string, z.ZodTypeAny> = {};

    for (const f of fields) {
        let v: z.ZodTypeAny;

        if (f.type === 'integer') {
            let n = z.coerce.number().int();
            if (f.min !== undefined) n = n.min(f.min);
            if (f.max !== undefined) n = n.max(f.max);
            v = n;
        } else if (f.type === 'decimal') {
            v = z.string().regex(/^\d+(\.\d+)?$/, 'Enter a valid decimal number');
        } else if (f.type === 'date') {
            v = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use YYYY-MM-DD format');
        } else if (f.type === 'boolean') {
            v = z.boolean();
        } else if (f.type === 'choice') {
            const opts = f.options ?? [];
            v = opts.length > 0 ? z.enum(opts as [string, ...string[]]) : z.string();
        } else if (f.type === 'email') {
            v = z.string().email('Enter a valid email');
        } else if (f.type === 'phone') {
            v = z.string().min(7, 'Phone must be at least 7 characters');
        } else {
            let s = z.string();
            if (f.min !== undefined) s = s.min(f.min);
            if (f.max !== undefined) s = s.max(f.max);
            if (f.pattern) s = s.regex(new RegExp(f.pattern), 'Invalid format');
            v = s;
        }

        shape[f.key] = f.required ? v : v.optional();
    }

    return z.object(shape);
}


function Section({
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
            {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
            <div className="mt-3">{children}</div>
        </section>
    );
}


export function TypePicker({
                        blueprint,
                        selectedId,
                        onSelect,
                    }: {
    blueprint: EntityType[];
    selectedId: number;
    onSelect: (id: number) => void;
}) {
    return (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {blueprint.map((et) => {
                const selected = et.id === selectedId;
                const color = et.display_config.color ?? '#6B7280';
                return (
                    <button
                        key={et.id}
                        type="button"
                        onClick={() => onSelect(et.id)}
                        className={cn(
                            'flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors',
                            selected
                                ? 'border-primary bg-primary-50 ring-1 ring-primary'
                                : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50',
                        )}
                    >
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{background: color}}/>
                        <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-gray-900">{et.name}</span>
              <span className="block text-xs text-gray-400">Level {et.level_order}</span>
            </span>
                        {selected && <Check className="h-4 w-4 shrink-0 text-primary"/>}
                    </button>
                );
            })}
        </div>
    );
}

function CapabilityHints({et}: { et: EntityType }) {
    const flags = [
        et.is_loginable && {icon: LogIn, label: 'Creates a login account'},
        et.incentive_eligible && {icon: Award, label: 'Incentive eligible'},
    ].filter(Boolean) as { icon: typeof LogIn; label: string }[];

    if (flags.length === 0 && !et.description) return null;

    return (
        <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2.5">
            {et.description && <p className="text-xs text-gray-500">{et.description}</p>}
            {flags.length > 0 && (
                <div className={cn('flex flex-wrap gap-1.5', et.description && 'mt-2')}>
                    {flags.map(({icon: Icon, label}) => (
                        <span
                            key={label}
                            className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs text-gray-600 ring-1 ring-gray-200"
                        >
              <Icon className="h-3 w-3 text-primary"/>
                            {label}
            </span>
                    ))}
                </div>
            )}
        </div>
    );
}



export function ParentSearch({
                          allowedTypes,
                          allowedTypeLabels,
                          value,
                          onChange,
                      }: {
    allowedTypes: string[];
    allowedTypeLabels: string[];
    value: EntityListItem | null;
    onChange: (item: EntityListItem | null) => void;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);

    const {data: results, isLoading} = useEntitySearch(q);
    const filtered = (results ?? []).filter(
        (r) =>
            allowedTypes.length === 0 ||
            (r.entity_type_code && allowedTypes.includes(r.entity_type_code)),
    );


    if (value) {
        return (
            <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
        <span className="flex min-w-0 items-center gap-2 text-sm">
          <Check className="h-4 w-4 shrink-0 text-success"/>
          <span className="truncate font-medium text-gray-900">{value.name}</span>
            {(value.entity_type_name ?? value.entity_type_code) && (
                <span className="text-xs text-gray-500">{value.entity_type_name ?? value.entity_type_code}</span>
            )}
        </span>
                <button
                    type="button"
                    onClick={() => onChange(null)}
                    className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                    aria-label="Clear parent"
                >
                    <X className="h-4 w-4"/>
                </button>
            </div>
        );
    }

    return (
        <div className="relative w-full">
            <input
                type="text"
                placeholder="Search by name…"
                value={q}
                onChange={(e) => {
                    setQ(e.target.value);
                    setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onBlur={() => setTimeout(() => setOpen(false), 150)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                   focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            {allowedTypeLabels.length > 0 && (
                <p className="mt-1 text-xs text-gray-400">
                    Can report to: {allowedTypeLabels.join(', ')}
                </p>
            )}
            {open && q.length > 0 && (
                <div
                    className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                    {isLoading && (
                        <div className="flex justify-center py-2">
                            <Spinner size="sm"/>
                        </div>
                    )}
                    {!isLoading && filtered.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">No matching entities.</p>
                    )}
                    {filtered.map((r) => (
                        <button
                            key={r.id}
                            type="button"
                            onMouseDown={() => {
                                onChange(r);
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="flex-1 truncate">{r.name}</span>
                            <span className="text-xs text-gray-500">{r.entity_type_name ?? r.entity_type_code}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}



export function AttrField({
                       field,
                       value,
                       error,
                       onChange,
                   }: {
    field: AttributeField;
    value: unknown;
    error?: string;
    onChange: (v: unknown) => void;
}) {
    const strVal = value !== undefined && value !== null ? String(value) : '';
    const label = (
        <>
            {field.label}
            {field.required && <span className="ml-0.5 text-danger">*</span>}
        </>
    );

    if (field.type === 'boolean') {
        return (
            <div>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(e) => onChange(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 accent-primary"
                    />
                    <span className="font-medium text-gray-700">{label}</span>
                </label>
                {error && <p className="mt-0.5 text-xs text-danger">{error}</p>}
            </div>
        );
    }

    if (field.type === 'choice' && field.options) {
        return (
            <Select
                label={`${field.label}${field.required ? ' *' : ''}`}
                value={strVal}
                onChange={(e) => onChange(e.target.value)}
                placeholder="— select —"
                options={field.options.map((o) => ({value: o, label: o}))}
                error={error}
            />
        );
    }

    if (field.type === 'date') {
        return (
            <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
                <input
                    type="date"
                    value={strVal}
                    onChange={(e) => onChange(e.target.value)}
                    className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                     focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                {error && <p className="mt-0.5 text-xs text-danger">{error}</p>}
            </div>
        );
    }

    const inputType =
        field.type === 'email' ? 'email' :
            field.type === 'phone' ? 'tel' :
                field.type === 'integer' || field.type === 'decimal' ? 'number' :
                    'text';

    return (
        <Input
            label={`${field.label}${field.required ? ' *' : ''}`}
            type={inputType}
            value={strVal}
            onChange={(e) => onChange(e.target.value)}
            error={error}
        />
    );
}



function CoverageSection({
    channelId,
    onChannel,
    onGeoNode,
}: {
    channelId: number | null;
    onChannel: (id: number | null) => void;
    onGeoNode: (id: number | null) => void;
}) {
    const {data: channelsResp} = useChannels();
    const {data: geoTypesResp} = useGeographyTypes();
    const channels = channelsResp?.results ?? [];
    const geoTypes = geoTypesResp?.results ?? [];

    const [geoTypeCode, setGeoTypeCode] = useState<string>('');
    const effectiveGeoType = geoTypeCode || (geoTypes[0]?.code ?? '');
    const [geoSel, setGeoSel] = useState<GeoSelection | null>(null);

    return (
        <div className="grid grid-cols-2 gap-4">
            <Select
                label="Channel"
                value={channelId === null ? '' : String(channelId)}
                onChange={(e) => onChannel(e.target.value === '' ? null : Number(e.target.value))}
                placeholder="— none —"
                options={channels.map((c) => ({value: String(c.id), label: c.name}))}
            />
            <div className="space-y-2">
                {geoTypes.length > 1 && (
                    <Select
                        label="Geography"
                        value={effectiveGeoType}
                        onChange={(e) => {
                            setGeoTypeCode(e.target.value);
                            setGeoSel(null);
                            onGeoNode(null);
                        }}
                        options={geoTypes.map((t) => ({value: t.code, label: t.name}))}
                    />
                )}
                <GeoNodeCombobox
                    label={geoTypes.length > 1 ? 'Territory' : 'Territory (geography)'}
                    typeCode={effectiveGeoType}
                    value={geoSel}
                    onChange={(node) => {
                        setGeoSel(node);
                        onGeoNode(node?.id ?? null);
                    }}
                />
            </div>
        </div>
    );
}


/** Edit-mode coverage: channel stays editable; owned territories are shown read-only
 *  because a territory change IS a transfer and must go through the Transfer dialog. */
function EditCoverage({channelId, onChannel, entity}: {
    channelId: number | null;
    onChannel: (id: number | null) => void;
    entity: Entity;
}) {
    const {data: channelsResp} = useChannels();
    const channels = channelsResp?.results ?? [];

    return (
        <div className="grid grid-cols-2 gap-4">
            <Select
                label="Channel"
                value={channelId === null ? '' : String(channelId)}
                onChange={(e) => onChannel(e.target.value === '' ? null : Number(e.target.value))}
                placeholder="— none —"
                options={channels.map((c) => ({value: String(c.id), label: c.name}))}
            />
            <div>
                <p className="mb-1 block text-sm font-medium text-gray-700">Areas they look after</p>
                {entity.owned_scopes.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-gray-200 px-3 py-2 text-sm text-gray-400">
                        No territory yet — assign one from their card’s Territories owned section.
                    </p>
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        {entity.owned_scopes.map((s) => (
                            <span
                                key={s.id}
                                className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700"
                            >
                                {s.name}
                                <span className="text-gray-400">since {s.since}</span>
                            </span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}


const LOGIN_METHOD_NOTE: Record<string, string> = {
    otp_only: 'This person signs in with a mobile OTP — provide a mobile number.',
    password_only: 'This person signs in with email / employee ID and a password.',
    password_and_otp: 'This person can sign in with a password or a mobile OTP.',
};



interface Props {
    entity?: Entity;
    initialEntityTypeId?: number;
    onClose: () => void;
}

export function EntityForm({entity, initialEntityTypeId, onClose}: Props) {
    const isEdit = entity !== undefined;

    const {data: blueprint = []} = useBlueprint();
    const createMutation = useCreateEntity();
    const updateMutation = useUpdateEntity();

    const [selectedTypeId, setSelectedTypeId] = useState<number>(
        entity?.entity_type.id ?? initialEntityTypeId ?? (blueprint[0]?.id ?? 0),
    );

    const currentET: EntityType | undefined = useMemo(
        () => blueprint.find((t) => t.id === selectedTypeId),
        [blueprint, selectedTypeId],
    );

    const [name, setName] = useState(entity?.name ?? '');
    const [code, setCode] = useState(entity?.code ?? '');

    const [attrs, setAttrs] = useState<Record<string, unknown>>(entity?.attributes ?? {});
    const [attrErrors, setAttrErrors] = useState<Record<string, string>>({});
    const [basicErrors, setBasicErrors] = useState<{ name?: string; code?: string }>({});
    const [parent, setParent] = useState<EntityListItem | null>(null);

    const loginMethod = currentET?.display_config.login_method ?? 'otp_only';
    const [loginEmail, setLoginEmail] = useState(entity?.linked_user?.email ?? '');
    const [loginMobile, setLoginMobile] = useState(entity?.linked_user?.mobile ?? '');
    const [loginPassword, setLoginPassword] = useState('');

    const [channelId, setChannelId] = useState<number | null>(entity?.channel?.id ?? null);
    // Create only: opens an owner assignment. On edit, coverage is read-only —
    // changing a territory is a transfer (effective-dated + audited), not a field edit.
    const [geoNodeId, setGeoNodeId] = useState<number | null>(null);


    function handleNameChange(value: string) {
        setName(value);
        if (basicErrors.name) setBasicErrors((e) => ({...e, name: undefined}));
    }

    useEffect(() => {
        if (!isEdit) {
            setAttrs({});
            setAttrErrors({});
        }
    }, [selectedTypeId, isEdit]);

    useEffect(() => {
        if (!isEdit && selectedTypeId === 0 && blueprint.length > 0) {
            setSelectedTypeId(blueprint[0]!.id);
        }
    }, [blueprint, isEdit, selectedTypeId]);


    const allowedParentLabels = useMemo(() => {
        if (!currentET) return [];
        const byCode = new Map(blueprint.map((t) => [t.code, t.name]));
        return currentET.allowed_parent_types.map((c) => byCode.get(c) ?? c);
    }, [currentET, blueprint]);

    function validateAndSubmit() {
        if (!currentET) return;


        const nextBasic: { name?: string; code?: string } = {};
        if (!name.trim()) nextBasic.name = 'Name is required';
        setBasicErrors(nextBasic);


        const schema = buildZodSchema(currentET.attribute_schema);
        const parsed = schema.safeParse(attrs);
        if (!parsed.success) {
            const errs: Record<string, string> = {};
            for (const issue of parsed.error.issues) {
                const key = issue.path[0];
                if (typeof key === 'string') errs[key] = issue.message;
            }
            setAttrErrors(errs);
        } else {
            setAttrErrors({});
        }

        if (Object.keys(nextBasic).length > 0 || !parsed.success) return;

        if (isEdit && entity) {

            const data: UpdateEntityPayload = {
                name: name.trim(),
                attributes: parsed.data,
                channel_id: channelId,
                ...(currentET.is_loginable
                    ? {email: loginEmail.trim() || null, mobile: loginMobile.trim() || null}
                    : {}),
                ...(currentET.is_loginable && loginPassword ? {password: loginPassword} : {}),
            };
            updateMutation.mutate(
                {id: entity.id, data},
                {
                    onSuccess: () => {
                        notify.success('Entity updated.');
                        onClose();
                    },
                    onError: (err) => notify.error(apiErrorMessage(err, 'Could not update entity.')),
                },
            );
        } else {
            const payload: CreateEntityPayload = {
                entity_type_id: currentET.id,
                name: name.trim(),
                code: code.trim(),
                parent_id: parent?.id ?? null,
                attributes: parsed.data,
                channel_id: channelId,
                owned_scope_ids: geoNodeId !== null ? [geoNodeId] : [],
                effective_from: new Date().toISOString().split('T')[0] as string,
                ...(currentET.is_loginable && loginEmail ? {email: loginEmail} : {}),
                ...(currentET.is_loginable && loginMobile ? {mobile: loginMobile} : {}),
                ...(currentET.is_loginable && loginPassword ? {password: loginPassword} : {}),
            };
            createMutation.mutate(payload, {
                onSuccess: () => {
                    notify.success(`${name} created.`);
                    onClose();
                },
                onError: (err) => {
                    notify.error(apiErrorMessage(err, 'Could not create entity.'));
                },
            });
        }
    }

    const isPending = createMutation.isPending || updateMutation.isPending;

    if (blueprint.length === 0) {
        return (
            <Modal open onClose={onClose} title={isEdit ? 'Edit Entity' : 'Create Entity'}>
                <div className="flex items-center justify-center py-8"><Spinner/></div>
            </Modal>
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={isEdit ? `Edit: ${entity.name}` : 'Create Entity'}
            description={isEdit ? undefined : 'Add a new node to the hierarchy.'}
            size="2xl"
            footer={
                <>
                    <Button variant="outline" onClick={onClose}>Cancel</Button>
                    <Button onClick={validateAndSubmit} loading={isPending}>
                        {isEdit ? 'Save Changes' : 'Create Entity'}
                    </Button>
                </>
            }
        >
            <div className="space-y-6">

                {!isEdit ? (
                    <Section title="Entity Type" hint="What kind of node are you adding?">
                        <TypePicker
                            blueprint={blueprint}
                            selectedId={selectedTypeId}
                            onSelect={setSelectedTypeId}
                        />
                        {currentET && <CapabilityHints et={currentET}/>}
                    </Section>
                ) : (
                    <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">
            <span
                className="h-2.5 w-2.5 rounded-full"
                style={{background: entity.entity_type.display_config.color ?? '#6B7280'}}
            />
                        Type: <strong className="text-gray-900">{entity.entity_type.name}</strong>
                    </div>
                )}


                <Section title="Basics">
                    <div className="grid grid-cols-2 gap-4">
                        <Input
                            label="Name *"
                            value={name}
                            onChange={(e) => handleNameChange(e.target.value)}
                            error={basicErrors.name}
                            placeholder={currentET ? `Name of this ${currentET.name}` : 'Name'}
                        />
                        <Input
                            label="Code"
                            value={code}
                            disabled={isEdit}
                            onChange={(e) => {
                                setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''));
                                if (basicErrors.code) setBasicErrors((er) => ({...er, code: undefined}));
                            }}
                            error={basicErrors.code}
                            placeholder={currentET && !isEdit ? `${currentET.code.toUpperCase()}-0001` : undefined}
                            hint={isEdit
                                ? 'Code cannot be changed.'
                                : `Leave blank to auto-generate (${currentET ? currentET.code.toUpperCase() : 'ROLE'}-0001). The location label updates automatically on transfer.`}
                        />
                    </div>
                </Section>


                {currentET && !isEdit && (
                    <Section title="Placement" hint="Leave the parent empty to create a top-level entity.">
                        <ParentSearch
                            allowedTypes={currentET.allowed_parent_types}
                            allowedTypeLabels={allowedParentLabels}
                            value={parent}
                            onChange={setParent}
                        />
                    </Section>
                )}


                {currentET && !isEdit && (
                    <Section title="Coverage" hint="Route-to-market channel and the territory this entity will own from day one.">
                        <CoverageSection
                            channelId={channelId}
                            onChannel={setChannelId}
                            onGeoNode={setGeoNodeId}
                        />
                    </Section>
                )}

                {currentET && isEdit && entity && (
                    <Section
                        title="Coverage"
                        hint="Territory changes are transfers — use the Transfer action so they're effective-dated and audited."
                    >
                        <EditCoverage channelId={channelId} onChannel={setChannelId} entity={entity}/>
                    </Section>
                )}


                {currentET && currentET.attribute_schema.length > 0 && (
                    <Section title="Details">
                        <div className="grid grid-cols-2 gap-4">
                            {currentET.attribute_schema.map((field) => (
                                <AttrField
                                    key={field.key}
                                    field={field}
                                    value={attrs[field.key]}
                                    error={attrErrors[field.key]}
                                    onChange={(v) => setAttrs((prev) => ({...prev, [field.key]: v}))}
                                />
                            ))}
                        </div>
                    </Section>
                )}


                {currentET?.is_loginable && (
                    <Section
                        title="Login account"
                        hint={LOGIN_METHOD_NOTE[loginMethod] ?? undefined}
                    >
                        <div className="grid grid-cols-2 gap-4">
                            <Input
                                label="Email"
                                type="email"
                                value={loginEmail}
                                onChange={(e) => setLoginEmail(e.target.value)}
                            />
                            <Input
                                label="Mobile"
                                type="tel"
                                value={loginMobile}
                                onChange={(e) => setLoginMobile(e.target.value)}
                            />
                        </div>
                        {loginMethod !== 'otp_only' && (
                            <div className="mt-4">
                                <Input
                                    label="Password"
                                    type="password"
                                    value={loginPassword}
                                    onChange={(e) => setLoginPassword(e.target.value)}
                                    hint={isEdit ? 'Leave blank to keep current password.' : 'Leave blank to let them set it later.'}
                                />
                            </div>
                        )}
                        <p className="mt-3 flex items-center gap-1.5 text-xs text-gray-400">
                            <Badge variant="info">Auto</Badge>
                            {isEdit && entity.linked_user
                                ? 'This entity is linked to a user account.'
                                : 'A user account will be created and linked to this entity.'}
                        </p>
                    </Section>
                )}
            </div>
        </Modal>
    );
}
