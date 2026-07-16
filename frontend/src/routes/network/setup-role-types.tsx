import {useState} from 'react';
import {useForm} from 'react-hook-form';
import type {Path} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {notify} from '../../utils/notify';
import {
    Plus, Edit2, ChevronRight, ChevronLeft, Check,
    Settings, GitBranch, Database, Eye, Sparkles, Palette,
    X,
} from 'lucide-react';
import {cn} from '../../utils/cn';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Textarea} from '../../components/ui/Textarea';
import {Badge} from '../../components/ui/Badge';
import {Spinner} from '../../components/ui/Spinner';
import {PageHeader} from '../../components/ui/PageHeader';
import {Stepper, StepIntro, Example} from '../../components/ui/WizardChrome';
import {InfoTooltip} from '../../components/ui/InfoTooltip';
import {BooleanCell} from '../../components/ui/BooleanCell';
import {IconPicker} from '../../components/ui/IconPicker';
import {EntityIcon} from '../../utils/entityIcons';
import {AttributeSchemaBuilder} from '../../components/builders/AttributeSchemaBuilder';
import {useEntityTypes, useCreateEntityType, useUpdateEntityType, useChannels} from '../../hooks/useEntities';
import {useRBAC} from '../../hooks/useRBAC';
import {useRoles} from '../../hooks/useAdmin';
import type {AttributeField, DisplayConfig, EntityType} from '../../types/entity';


interface RoleOption {
    id: number;
    name: string;
    code: string;
}


const wizardSchema = z.object({
    name: z.string().min(1, 'Name is required.'),
    code: z
        .string()
        .min(1, 'Code is required.')
        .regex(/^[a-z0-9_]+$/, 'Code must be lowercase letters, numbers, and underscores only.'),
    description: z.string(),
    level_order: z.number().int().min(1, 'Level order must be at least 1.'),
    allowed_parent_types: z.array(z.string()),
    allowed_child_types: z.array(z.string()),
    attribute_schema: z.array(z.custom<AttributeField>()),
    is_loginable: z.boolean(),
    login_method: z.enum(['password_and_otp', 'otp_only', 'password_only']),
    default_role: z.number().nullable(),
    incentive_eligible: z.boolean(),
    is_leaf: z.boolean(),
    is_root_type: z.boolean(),
    channel_id: z.number().nullable(),
    portal_type: z.enum(['admin', 'partner']),
    icon: z.string(),
    color: z.string(),
    card_fields: z.array(z.string()),
    show_in_tree: z.boolean(),
});

type WizardData = z.infer<typeof wizardSchema>;


const STEP_FIELDS: (keyof WizardData)[][] = [
    ['name', 'code'],
    ['level_order'],
    [],
    [],
    [],
    [],
];

const INITIAL: WizardData = {
    name: '',
    code: '',
    description: '',
    level_order: 1,
    allowed_parent_types: [],
    allowed_child_types: [],
    attribute_schema: [],
    is_loginable: false,
    login_method: 'password_and_otp',
    default_role: null,
    incentive_eligible: false,
    is_leaf: false,
    is_root_type: false,
    channel_id: null,
    portal_type: 'admin',
    icon: '',
    color: '#6B7280',
    card_fields: [],
    show_in_tree: true,
};

const STEPS = [
    {label: 'Basics', icon: Settings},
    {label: 'Placement', icon: GitBranch},
    {label: 'Information', icon: Database},
    {label: 'Abilities', icon: Sparkles},
    {label: 'Appearance', icon: Palette},
    {label: 'Review', icon: Eye},
];

const STEP_HELP: { title: string; body: string }[] = [
    {
        title: "Let's start with the basics",
        body:
            "Think of a role type as a group of people or businesses you treat the same way — like "
            + "Area Sales Manager, Distributor, or Retailer. Give it a name everyone will recognise, and "
            + "we'll build on it from here.",
    },
    {
        title: 'Where does it fit in?',
        body:
            "Tell us roughly how senior this role is and what it can sit next to. A Retailer usually sits "
            + "under a Distributor, for example. Not sure yet? Leave it open — you can tidy this up any time.",
    },
    {
        title: 'What do you want to know about them?',
        body:
            "Add any details you'd like to keep on file for people in this role — say an employee ID or a "
            + "GST number. If a name is all you need, just skip ahead.",
    },
    {
        title: 'What can they do?',
        body:
            "Flip on whatever applies — can they sign in, do they earn incentives "
            + "programs, and which screen should they see. None of this is set in stone; change it whenever.",
    },
    {
        title: 'Make it easy to spot',
        body:
            "Give it an icon and a colour so it stands out in the tree, and pick the details you'd like to "
            + "see at a glance on each card. This is all about looks — it won't change how anything works.",
    },
    {
        title: 'One last look',
        body:
            "Here's everything you've set up. Spot something to fix? Click any step above to jump back. "
            + "Happy with it? Go ahead and save.",
    },
];



function slugify(name: string): string {
    return name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
}

function etToWizard(et: EntityType): WizardData {
    const dc = et.display_config;
    return {
        name: et.name,
        code: et.code,
        description: et.description,
        level_order: et.level_order,
        allowed_parent_types: et.allowed_parent_types,
        allowed_child_types: et.allowed_child_types,
        attribute_schema: et.attribute_schema,
        is_loginable: et.is_loginable,
        login_method: dc.login_method ?? 'password_and_otp',
        default_role: et.default_role,
        incentive_eligible: et.incentive_eligible,
        is_leaf: et.is_leaf,
        is_root_type: et.is_root_type ?? false,
        channel_id: et.channel?.id ?? null,
        portal_type: dc.portal_type ?? 'admin',
        icon: dc.icon ?? '',
        color: dc.color ?? '#6B7280',
        card_fields: dc.card_fields ?? [],
        show_in_tree: dc.show_in_tree ?? true,
    };
}

function buildPayload(d: WizardData): Omit<EntityType, 'id' | 'version' | 'is_current' | 'is_active' | 'created_at' | 'updated_at'> {
    const display_config: DisplayConfig = {
        icon: d.icon || undefined,
        color: d.color,
        show_in_tree: d.show_in_tree,
        portal_type: d.portal_type,
        login_method: d.login_method,
        card_fields: d.card_fields,
    };
    return {
        name: d.name,
        code: d.code,
        description: d.description,
        level_order: d.level_order,
        allowed_parent_types: d.allowed_parent_types,
        allowed_child_types: d.allowed_child_types,
        attribute_schema: d.attribute_schema,
        is_loginable: d.is_loginable,
        incentive_eligible: d.incentive_eligible,
        is_leaf: d.is_leaf,
        is_root_type: d.is_root_type,
        default_role: d.default_role,
        channel: null,
        channel_id: d.channel_id,
        display_config,
        effective_from: new Date().toISOString().split('T')[0] as string,
        effective_to: null,
    };
}


function Toggle({
                    checked,
                    onChange,
                    label,
                    description,
                    hint,
                    disabled,
                }: {
    checked: boolean;
    onChange: (v: boolean) => void;
    label: string;
    description?: string;
    hint?: string;
    disabled?: boolean;
}) {
    return (
        <div className="flex items-start gap-3">
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                disabled={disabled}
                onClick={() => onChange(!checked)}
                className={cn(
                    'relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-primary/30',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    checked ? 'bg-primary' : 'bg-gray-200',
                )}
            >
        <span
            className={cn(
                'inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform',
                checked ? 'translate-x-5' : 'translate-x-0.5',
            )}
        />
            </button>
            <div>
                <p className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
                    {label}
                    {hint && <InfoTooltip content={hint}/>}
                </p>
                {description && <p className="text-xs text-gray-500">{description}</p>}
            </div>
        </div>
    );
}


function ChipPicker({
                        label,
                        options,
                        selected,
                        onChange,
                    }: {
    label: string;
    options: { code: string; name: string }[];
    selected: string[];
    onChange: (v: string[]) => void;
}) {
    function toggle(code: string) {
        onChange(
            selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code],
        );
    }

    return (
        <div>
            <p className="mb-1.5 text-sm font-medium text-gray-700">{label}</p>
            {options.length === 0 ? (
                <p className="text-xs text-gray-400">You haven't set up any other role types yet.</p>
            ) : (
                <div className="flex flex-wrap gap-2">
                    {options.map(({code, name}) => {
                        const active = selected.includes(code);
                        return (
                            <button
                                key={code}
                                type="button"
                                onClick={() => toggle(code)}
                                className={cn(
                                    'rounded-full border px-3 py-1 text-xs transition-colors',
                                    active
                                        ? 'border-primary bg-primary text-white'
                                        : 'border-gray-200 bg-gray-50 text-gray-600 hover:border-primary hover:text-primary',
                                )}
                            >
                                {name}
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}



function Step1Basic({data, update}: { data: WizardData; update: (p: Partial<WizardData>) => void }) {
    return (
        <div className="space-y-4">
            <StepIntro {...STEP_HELP[0]} />
            <div>
                <Input
                    label="Name *"
                    placeholder="e.g. Area Sales Executive"
                    value={data.name}
                    onChange={(e) => {
                        const name = e.target.value;
                        update({name, code: slugify(name)});
                    }}
                />
                <Example>
                    The everyday name people will recognise — something like <strong>Distributor</strong>,{' '}
                    <strong>Retailer</strong>, or <strong>Regional Manager</strong>.
                </Example>
            </div>
            <div>
                <Input
                    label="Short code *"
                    placeholder="e.g. ase"
                    value={data.code}
                    onChange={(e) => update({code: slugify(e.target.value)})}
                    hint="A short tag we use behind the scenes. We've filled it in from the name — no need to touch it."
                />
                <Example>
                    You can usually leave this alone. It only takes lowercase letters, numbers and underscores
                    (e.g. <code className="rounded bg-gray-100 px-1">area_sales_exec</code>).
                </Example>
            </div>
            <Textarea
                label="Description (optional)"
                placeholder="A sentence describing who this type is for…"
                rows={3}
                value={data.description}
                onChange={(e) => update({description: e.target.value})}
                hint="A quick note so your team knows what this role is for. Just for reference."
            />
        </div>
    );
}



function Step2Hierarchy({
                            data,
                            update,
                            typeOptions,
                        }: {
    data: WizardData;
    update: (p: Partial<WizardData>) => void;
    typeOptions: { code: string; name: string }[];
}) {
    return (
        <div className="space-y-5">
            <StepIntro {...STEP_HELP[1]} />

            <div>
                <div className="w-40">
                    <Input
                        label="Level in the network *"
                        type="number"
                        min={1}
                        value={data.level_order}
                        onChange={(e) => update({level_order: parseInt(e.target.value, 10) || 1})}
                        hint="1 = the very top"
                    />
                </div>
                <Example>
                    Lower numbers are higher up. A National Head might be <strong>1</strong>, a Regional
                    Manager <strong>2</strong>, and a Retailer further down at <strong>5</strong> or{' '}
                    <strong>6</strong>.
                </Example>
            </div>

            <div>
                <ChipPicker
                    label="Who can this type sit under?"
                    options={typeOptions}
                    selected={data.allowed_parent_types}
                    onChange={(v) => update({allowed_parent_types: v})}
                />
                <Example>
                    Pick the types allowed directly above this one. Example: a Retailer sits under a{' '}
                    <strong>Distributor</strong>.
                </Example>
            </div>

            <div>
                <ChipPicker
                    label="What can sit under this type?"
                    options={typeOptions}
                    selected={data.allowed_child_types}
                    onChange={(v) => update({allowed_child_types: v})}
                />
                <Example>
                    Pick the types allowed directly below this one. Example: a Distributor can have{' '}
                    <strong>Retailers</strong> beneath it.
                </Example>
            </div>

            <p className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                💡 Still figuring it out? Leave both empty for now — this role can go anywhere, and you can
                add the rules later once things are clearer.
            </p>
        </div>
    );
}



function SchemaFields({data, update}: { data: WizardData; update: (p: Partial<WizardData>) => void }) {
    return (
        <div>
            <div className="mb-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                Each row is one thing you'd like to know. Give it a <strong>Label</strong> (what your team
                sees), pick a <strong>Type</strong> (text, number, date…), tick <strong>Required</strong> if
                it always has to be filled in, and <strong>Unique</strong> if no two people can share the
                same value (like a GST number).
            </div>
            <AttributeSchemaBuilder
                value={data.attribute_schema}
                onChange={(fields) => update({attribute_schema: fields})}
            />
            <Example>
                Common examples: <strong>Employee ID</strong> (text, required, unique),{' '}
                <strong>Date of Joining</strong> (date), <strong>Store Class</strong> (choice: A, B, C, D).
            </Example>
        </div>
    );
}



function CapabilityFields({
                             data,
                             update,
                             roles,
                         }: {
    data: WizardData;
    update: (p: Partial<WizardData>) => void;
    roles: RoleOption[];
}) {
    const {data: channelsResp} = useChannels();
    const channels = channelsResp?.results ?? [];
    return (
        <div className="space-y-5">
            <Toggle
                checked={data.is_loginable}
                onChange={(v) => update({is_loginable: v})}
                label="They can sign in"
                description="Turn this on if these folks get their own account. We'll create the login for you."
            />

            {data.is_loginable && (
                <div className="ml-12 space-y-4 rounded-lg border border-gray-200 border-l-4 border-l-primary bg-gray-50 p-4">
                    <div>
                        <Select
                            label="How do they sign in?"
                            value={data.login_method}
                            onChange={(e) => update({login_method: e.target.value as WizardData['login_method']})}
                            options={[
                                {value: 'password_and_otp', label: 'Password or mobile OTP'},
                                {value: 'otp_only', label: 'Mobile OTP only (no password)'},
                                {value: 'password_only', label: 'Password only'},
                            ]}
                        />
                        <Example>
                            Office folks usually go for a password. Partners out in the field, like retailers,
                            often find a one-time code (OTP) texted to their phone much easier.
                        </Example>
                    </div>
                    <div>
                        <Select
                            label="Default permission set"
                            value={data.default_role?.toString() ?? ''}
                            onChange={(e) =>
                                update({default_role: e.target.value ? parseInt(e.target.value, 10) : null})
                            }
                            placeholder="— choose later —"
                            options={roles.map((r) => ({value: r.id.toString(), label: r.name}))}
                        />
                        <Example>
                            What each new account can see and do to begin with. You can always fine-tune it
                            person by person later.
                        </Example>
                    </div>
                </div>
            )}

            <Toggle
                checked={data.incentive_eligible}
                onChange={(v) => update({incentive_eligible: v})}
                label="They earn sales incentives"
                hint="Incentives are the payouts a role earns for hitting its targets — your own sales force, or channel partners like retailers and distributors."
                description="Turn this on if this role takes part in incentive schemes and can be paid out."
            />
            <Toggle
                checked={data.is_leaf}
                onChange={(v) => update({is_leaf: v})}
                label="This is the last level (nothing sits below it)"
                description="Turn this on when nobody can sit under this role — like a Retailer right at the end of the line."
            />
            <Toggle
                checked={data.is_root_type}
                onChange={(v) => update({is_root_type: v})}
                label="This is the top level (nothing sits above it)"
                description="Turn this on for your most senior role — like a National Sales Manager — so it can never be placed under anyone."
            />

            <div>
                <div className="w-64">
                    <Select
                        label="Which screen do they see?"
                        value={data.portal_type}
                        onChange={(e) => update({portal_type: e.target.value as WizardData['portal_type']})}
                        options={[
                            {value: 'admin', label: 'Office view (full sidebar menu)'},
                            {value: 'partner', label: 'Mobile view (simple bottom tabs)'},
                        ]}
                    />
                </div>
                <Example>
                    Go with <strong>Office view</strong> for managers and staff, or{' '}
                    <strong>Mobile view</strong> for partners on the move, like dealers and retailers.
                </Example>
            </div>

            <div>
                <div className="w-64">
                    <Select
                        label="Restrict to a channel (optional)"
                        value={data.channel_id === null ? '' : String(data.channel_id)}
                        onChange={(e) =>
                            update({channel_id: e.target.value ? parseInt(e.target.value, 10) : null})
                        }
                        placeholder="— any channel —"
                        options={channels.map((c) => ({value: String(c.id), label: c.name}))}
                    />
                </div>
                <Example>
                    For most roles, just leave this blank. Only pick a channel when the role lives in one
                    part of your business — like a “Modern Trade Distributor”.
                </Example>
            </div>
        </div>
    );
}



function AppearanceFields({data, update}: { data: WizardData; update: (p: Partial<WizardData>) => void }) {
    const schemaKeys = data.attribute_schema.map((f) => ({key: f.key, label: f.label || f.key}));

    return (
        <div className="space-y-5">
            <div className="flex gap-4">
                <div className="flex-1">
                    <label className="mb-1 block text-sm font-medium text-gray-700">Icon</label>
                    <IconPicker value={data.icon} onChange={(name) => update({icon: name})}/>
                    <p className="mt-1 text-xs text-gray-400">This shows next to the role wherever it appears. Search and pick one you like.</p>
                </div>
                <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">Colour</label>
                    <div className="flex items-center gap-2">
                        <input
                            type="color"
                            value={data.color}
                            onChange={(e) => update({color: e.target.value})}
                            className="h-9 w-12 cursor-pointer rounded border border-gray-200 p-0.5"
                        />
                        <input
                            type="text"
                            value={data.color}
                            onChange={(e) => update({color: e.target.value})}
                            className="w-24 rounded border border-gray-200 bg-gray-50 px-2 py-2 font-mono text-xs
                         focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                        />
                    </div>
                </div>
            </div>

            <Toggle
                checked={data.show_in_tree}
                onChange={(v) => update({show_in_tree: v})}
                label="Show it in the tree"
                description="Leave this on so the role turns up when you're browsing. Switch it off to tuck it out of sight."
            />

            <div>
                <p className="mb-2 text-sm font-medium text-gray-700">
                    What to show at a glance{' '}
                    <span className="font-normal text-gray-400 text-xs">
            (the quick info that sits under each name in the tree)
          </span>
                </p>
                {schemaKeys.length === 0 ? (
                    <p className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                        Nothing to choose yet — pop back to the previous step, add a few details, then come
                        here to pick the ones worth highlighting.
                    </p>
                ) : (
                    <div className="flex flex-wrap gap-2">
                        {schemaKeys.map(({key, label}) => {
                            const active = data.card_fields.includes(key);
                            return (
                                <button
                                    key={key}
                                    type="button"
                                    onClick={() =>
                                        update({
                                            card_fields: active
                                                ? data.card_fields.filter((k) => k !== key)
                                                : [...data.card_fields, key],
                                        })
                                    }
                                    className={cn(
                                        'rounded-full border px-3 py-1 text-xs transition-colors',
                                        active
                                            ? 'border-primary bg-primary text-white'
                                            : 'border-gray-200 bg-gray-50 text-gray-600 hover:border-primary hover:text-primary',
                                    )}
                                >
                                    {label}
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}


function StepInformation({data, update}: { data: WizardData; update: (p: Partial<WizardData>) => void }) {
    return (
        <div className="space-y-4">
            <StepIntro {...STEP_HELP[2]} />
            <SchemaFields data={data} update={update}/>
        </div>
    );
}

function StepAbilities({
                           data,
                           update,
                           roles,
                       }: {
    data: WizardData;
    update: (p: Partial<WizardData>) => void;
    roles: RoleOption[];
}) {
    return (
        <div className="space-y-5">
            <StepIntro {...STEP_HELP[3]} />
            <CapabilityFields data={data} update={update} roles={roles}/>
        </div>
    );
}

function StepAppearance({data, update}: { data: WizardData; update: (p: Partial<WizardData>) => void }) {
    return (
        <div className="space-y-4">
            <StepIntro {...STEP_HELP[4]} />
            <AppearanceFields data={data} update={update}/>
        </div>
    );
}


function Step4Review({data, typeOptions}: { data: WizardData; typeOptions: { code: string; name: string }[] }) {
    const [jsonOpen, setJsonOpen] = useState(false);
    const payload = buildPayload(data);
    const nameFor = (code: string) => typeOptions.find((t) => t.code === code)?.name ?? code;

    const row = (label: string, value: React.ReactNode) => (
        <div key={label} className="flex gap-2 py-1.5 border-b border-gray-50 last:border-0">
            <span className="w-40 shrink-0 text-xs text-gray-500">{label}</span>
            <span className="text-sm text-gray-900">{value}</span>
        </div>
    );

    const yesNo = (v: boolean) => (v ? 'Yes' : 'No');

    return (
        <div className="space-y-4">
            <StepIntro {...STEP_HELP[5]} />
            <div className="rounded-lg border border-gray-200 bg-white px-4 py-2">
                {row('Name', <strong>{data.name || <span className="text-danger">— not set —</span>}</strong>)}
                {row('Short code', <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">{data.code}</code>)}
                {row('Description', data.description || <span className="text-gray-400">—</span>)}
                {row('Level in network', data.level_order)}
                {row(
                    'Can sit under',
                    data.allowed_parent_types.length > 0 ? (
                        <span className="flex flex-wrap gap-1">
              {data.allowed_parent_types.map((c) => (
                  <Badge key={c} variant="info">{nameFor(c)}</Badge>
              ))}
            </span>
                    ) : (
                        <span className="text-gray-400">Anywhere</span>
                    ),
                )}
                {row(
                    'Can contain',
                    data.allowed_child_types.length > 0 ? (
                        <span className="flex flex-wrap gap-1">
              {data.allowed_child_types.map((c) => (
                  <Badge key={c} variant="info">{nameFor(c)}</Badge>
              ))}
            </span>
                    ) : (
                        <span className="text-gray-400">Anything</span>
                    ),
                )}
                {row('Information fields', `${data.attribute_schema.length} field(s)`)}
                {row('Can log in', yesNo(data.is_loginable))}
                {data.is_loginable && row('Sign-in method', data.login_method.replace(/_/g, ' '))}
                {row('Earns incentives', yesNo(data.incentive_eligible))}
                {row('Last level (nothing below)', yesNo(data.is_leaf))}
                {row('Top level (nothing above)', yesNo(data.is_root_type))}
                {row('Screen layout', data.portal_type === 'partner' ? 'Mobile view' : 'Office view')}
                {row('Colour', (
                    <span className="flex items-center gap-2">
            <span
                className="inline-block h-4 w-4 rounded-sm border border-gray-200"
                style={{background: data.color}}
            />
                        {data.color}
          </span>
                ))}
            </div>

            <details open={jsonOpen} onToggle={(e) => setJsonOpen((e.target as HTMLDetailsElement).open)}>
                <summary className="cursor-pointer text-xs font-medium text-gray-500 hover:text-gray-700 select-none">
                    {jsonOpen ? '▾' : '▸'} Advanced: technical preview
                </summary>
                <pre className="mt-2 overflow-auto rounded-lg bg-gray-900 p-4 text-xs text-green-400 max-h-60">
          {JSON.stringify(payload, null, 2)}
        </pre>
            </details>
        </div>
    );
}


interface WizardProps {
    editing: EntityType | null;
    typeOptions: { code: string; name: string }[];
    onClose: () => void;
}

function EntityTypeWizard({editing, typeOptions, onClose}: WizardProps) {
    const [step, setStep] = useState(0);

    const form = useForm<WizardData>({
        resolver: zodResolver(wizardSchema),
        defaultValues: editing ? etToWizard(editing) : INITIAL,
        mode: 'onChange',
    });


    const data = form.watch();

    const {data: rolesResponse} = useRoles();
    const roles: RoleOption[] = rolesResponse?.results ?? [];

    const createType = useCreateEntityType();
    const updateType = useUpdateEntityType();
    const isPending = createType.isPending || updateType.isPending;

    function update(partial: Partial<WizardData>) {
        for (const [key, value] of Object.entries(partial)) {
            form.setValue(key as Path<WizardData>, value as never, {
                shouldValidate: false,
                shouldDirty: true,
            });
        }
    }

    const stepError =
        STEP_FIELDS[step]
            .map((f) => form.formState.errors[f]?.message)
            .find((m): m is string => Boolean(m)) ?? null;

    // Jump to any step. Going forward validates the current step first so users
    // can't skip past required fields; going back is always allowed.
    async function goToStep(target: number) {
        if (target === step) return;
        if (target > step) {
            const ok = await form.trigger(STEP_FIELDS[step]);
            if (!ok) return;
        }
        setStep(target);
    }

    const onValid = (values: WizardData) => {
        const payload = buildPayload(values);

        if (editing) {
            updateType.mutate(
                {id: editing.id, payload},
                {
                    onSuccess: () => {
                        notify.success('New version saved.');
                        onClose();
                    },
                    onError: () => notify.error('Failed to save. Check all fields and try again.'),
                },
            );
        } else {
            createType.mutate(payload, {
                onSuccess: () => {
                    notify.success(`Role type "${values.name}" created.`);
                    onClose();
                },
                onError: () => notify.error('Failed to create. Check all fields and try again.'),
            });
        }
    };

    // If a hidden field fails validation on submit, jump to the step that owns it.
    const onInvalid = (errors: Record<string, unknown>) => {
        const firstBad = STEP_FIELDS.findIndex((fields) => fields.some((f) => f in errors));
        if (firstBad >= 0) setStep(firstBad);
        notify.error('Please fix the highlighted fields.');
    };

    const handleSubmit = form.handleSubmit(onValid, onInvalid);

    const isLast = step === STEPS.length - 1;

    return (

        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
        >

            <div
                className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >

                <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
                    <div className="flex items-center gap-3">
                        <h1 className="text-lg font-semibold text-gray-900">
                            {editing ? 'Edit Role Type' : 'Create Role Type'}
                        </h1>
                        {editing && (
                            <Badge variant="purple">v{editing.version}</Badge>
                        )}
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                        aria-label="Close"
                    >
                        <X className="h-5 w-5"/>
                    </button>
                </div>


                <div className="border-b border-gray-100 bg-gray-50 px-6 py-3">
                    <Stepper steps={STEPS} current={step} onStepClick={goToStep} />
                </div>


                <div className="flex-1 overflow-y-auto px-6 py-6">
                    <div className="mx-auto max-w-2xl">
                        {step === 0 && <Step1Basic data={data} update={update}/>}
                        {step === 1 && <Step2Hierarchy data={data} update={update} typeOptions={typeOptions}/>}
                        {step === 2 && <StepInformation data={data} update={update}/>}
                        {step === 3 && <StepAbilities data={data} update={update} roles={roles}/>}
                        {step === 4 && <StepAppearance data={data} update={update}/>}
                        {step === 5 && <Step4Review data={data} typeOptions={typeOptions}/>}

                        {stepError && (
                            <p className="mt-3 text-sm text-danger">{stepError}</p>
                        )}
                    </div>
                </div>


                <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
                    <Button variant="ghost" onClick={onClose}>Cancel</Button>

                    <div className="flex items-center gap-3">
                        {step > 0 && (
                            <Button variant="outline" icon={<ChevronLeft className="h-4 w-4"/>} onClick={() => goToStep(step - 1)}>
                                Back
                            </Button>
                        )}
                        {!isLast ? (
                            <Button iconRight={<ChevronRight className="h-4 w-4"/>} onClick={() => goToStep(step + 1)}>
                                Next
                            </Button>
                        ) : (
                            <Button
                                onClick={handleSubmit}
                                loading={isPending}
                                icon={<Check className="h-4 w-4"/>}
                            >
                                {editing ? 'Save as New Version' : 'Create Role Type'}
                            </Button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}


export default function EntityTypesPage() {
    const [wizardOpen, setWizardOpen] = useState(false);
    const [editTarget, setEditTarget] = useState<EntityType | null>(null);

    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const {data, isLoading, isError} = useEntityTypes();
    const entityTypes = data?.results ?? [];
    const typeOptions = entityTypes.map((et) => ({code: et.code, name: et.name}));

    function openCreate() {
        setEditTarget(null);
        setWizardOpen(true);
    }

    function openEdit(et: EntityType) {
        setEditTarget(et);
        setWizardOpen(true);
    }

    function closeWizard() {
        setWizardOpen(false);
        setEditTarget(null);
    }

    return (
        <div className="">
            <PageHeader
                title="Role Types"
                description="The different kinds of people and partners you work with — and what each one can do. Set this up once, and everyone you add later just slots right in."
                actions={writable && (
                    <Button icon={<Plus className="h-4 w-4"/>} onClick={openCreate}>
                        Create Role Type
                    </Button>
                )}
            />

            {/* Table */}
            <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
                {isLoading && (
                    <div className="flex items-center justify-center py-16">
                        <Spinner size="lg"/>
                    </div>
                )}

                {isError && (
                    <div className="py-12 text-center text-sm text-danger">
                        Failed to load entity types. Please refresh.
                    </div>
                )}

                {!isLoading && !isError && (
                    <table className="w-full text-sm">
                        <thead>
                        <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium text-gray-500">
                            <th className="px-4 py-3 w-16">Level</th>
                            <th className="px-4 py-3 w-32">Code</th>
                            <th className="px-4 py-3">Name</th>
                            <th className="px-4 py-3 w-20 text-center">Login</th>
                            <th className="px-4 py-3 w-20 text-center">Incentive</th>
                            <th className="px-4 py-3 w-16 text-center">Leaf</th>
                            <th className="px-4 py-3 w-24">Channel</th>
                            {writable && <th className="px-4 py-3 w-20 text-right">Actions</th>}
                        </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                        {entityTypes.length === 0 && (
                            <tr>
                                <td colSpan={writable ? 9 : 8} className="py-12 text-center text-sm text-gray-400">
                                    Nothing here yet. Hit "Create Role Type" to set up your first one.
                                </td>
                            </tr>
                        )}
                        {entityTypes.map((et) => (
                            <tr key={et.id} className="hover:bg-gray-50 transition-colors">
                                <td className="px-4 py-3">
                    <span
                        className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600">
                      {et.level_order}
                    </span>
                                </td>
                                <td className="px-4 py-3">
                                    <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
                                        {et.code}
                                    </code>
                                </td>
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <span
                                            className="shrink-0"
                                            style={{color: et.display_config.color ?? '#6B7280'}}
                                        >
                                            <EntityIcon name={et.display_config.icon} className="h-4 w-4"/>
                                        </span>
                                        <span className="font-medium text-gray-900">{et.name}</span>
                                        <span className="text-xs text-gray-400">v{et.version}</span>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-center">
                                    <div className="flex justify-center">
                                        <BooleanCell value={et.is_loginable} trueLabel="Can log in" falseLabel="No login"/>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-center">
                                    <div className="flex justify-center">
                                        <BooleanCell value={et.incentive_eligible} trueLabel="Earns incentives" falseLabel="No incentives"/>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-center">
                                    <div className="flex justify-center">
                                        <BooleanCell value={et.is_leaf} trueLabel="Bottom of chain" falseLabel="Has children"/>
                                    </div>
                                </td>
                                <td className="px-4 py-3">
                                    {et.channel !== null ? (
                                        <Badge variant="default">{et.channel.name}</Badge>
                                    ) : (
                                        <span className="text-gray-300 text-xs">—</span>
                                    )}
                                </td>
                                {writable && (
                                    <td className="px-4 py-3 text-right">
                                        <button
                                            type="button"
                                            onClick={() => openEdit(et)}
                                            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-gray-500
                                 hover:bg-gray-100 hover:text-primary transition-colors"
                                        >
                                            <Edit2 className="h-3.5 w-3.5"/>
                                            Edit
                                        </button>
                                    </td>
                                )}
                            </tr>
                        ))}
                        </tbody>
                    </table>
                )}
            </div>


            {wizardOpen && (
                <EntityTypeWizard
                    editing={editTarget}
                    typeOptions={typeOptions}
                    onClose={closeWizard}
                />
            )}
        </div>
    );
}
