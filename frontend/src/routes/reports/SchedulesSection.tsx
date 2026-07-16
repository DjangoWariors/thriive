import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {CalendarClock, Pencil, Play, Plus, Trash2} from 'lucide-react';
import {reportService} from '../../services/reportService';
import type {
    DeliveryTarget,
    ReportDefinition,
    ReportFormat,
    ReportSchedule,
    ReportSchedulePayload,
    ScheduleDelivery,
} from '../../types/reports';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Modal} from '../../components/ui/Modal';
import {Badge} from '../../components/ui/Badge';
import {EmptyState} from '../../components/ui/EmptyState';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';
import {formatRelative} from '../../utils/format';
import {ParamField, buildParameters} from './ParamField';

const KEY = ['reports', 'schedules'] as const;

const DOW_OPTIONS = [
    {value: '1', label: 'Monday'}, {value: '2', label: 'Tuesday'},
    {value: '3', label: 'Wednesday'}, {value: '4', label: 'Thursday'},
    {value: '5', label: 'Friday'}, {value: '6', label: 'Saturday'},
    {value: '0', label: 'Sunday'},
];

const DELIVERY_OPTIONS: {value: ScheduleDelivery; label: string}[] = [
    {value: 'both', label: 'In-app + email'},
    {value: 'in_app', label: 'In-app only'},
    {value: 'email', label: 'Email only'},
    {value: 'target', label: 'Delivery target (S3 / SFTP)'},
];

type Frequency = 'daily' | 'weekly' | 'monthly';

function frequencyOf(s: ReportSchedule): Frequency {
    if (s.cron_day_of_month !== '*') return 'monthly';
    if (s.cron_day_of_week !== '*') return 'weekly';
    return 'daily';
}

function cadenceLabel(s: ReportSchedule): string {
    const time = `${s.cron_hour.padStart(2, '0')}:${s.cron_minute.padStart(2, '0')}`;
    const freq = frequencyOf(s);
    if (freq === 'monthly') return `Monthly on day ${s.cron_day_of_month} at ${time}`;
    if (freq === 'weekly') {
        const dow = DOW_OPTIONS.find((d) => d.value === s.cron_day_of_week)?.label ?? s.cron_day_of_week;
        return `Weekly on ${dow} at ${time}`;
    }
    return `Daily at ${time}`;
}

export function SchedulesSection({definitions}: {definitions: ReportDefinition[]}) {
    const qc = useQueryClient();
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<ReportSchedule | null>(null);
    const [deleting, setDeleting] = useState<ReportSchedule | null>(null);
    const [runningId, setRunningId] = useState<number | null>(null);

    const {data, isLoading} = useQuery({queryKey: KEY, queryFn: () => reportService.listSchedules()});
    const invalidate = () => void qc.invalidateQueries({queryKey: KEY});

    const toggle = useMutation({
        mutationFn: (id: number) => reportService.toggleSchedule(id),
        onSuccess: invalidate,
        onError: (e) => notify.error(apiErrorMessage(e, 'Could not toggle schedule')),
    });
    const remove = useMutation({
        mutationFn: (id: number) => reportService.deleteSchedule(id),
        onSuccess: invalidate,
    });

    const rows = data?.results ?? [];

    async function runNow(s: ReportSchedule) {
        setRunningId(s.id);
        try {
            const result = await reportService.runScheduleNow(s.id);
            notify.success(`Ran "${s.name}" — delivered to ${result.delivered} of ${result.recipients} recipient(s).`);
            invalidate();
            void qc.invalidateQueries({queryKey: ['reports', 'executions']});
        } catch (e) {
            notify.error(apiErrorMessage(e, 'Run failed'));
        } finally {
            setRunningId(null);
        }
    }

    return (
        <>
            <div className="mb-3 flex items-center justify-between">
                <p className="text-sm text-gray-500">
                    Recurring reports run on a fixed cadence and deliver to each recipient in their own access scope.
                </p>
                <Button icon={<Plus className="h-4 w-4"/>} onClick={() => {
                    setEditing(null);
                    setFormOpen(true);
                }}>
                    New Schedule
                </Button>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : rows.length === 0 ? (
                <Card>
                    <EmptyState icon={CalendarClock} title="No schedules yet"
                                description="Create a schedule to generate and deliver a report automatically."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={rows}
                        rowKey={(s) => s.id}
                        columns={[
                            {header: 'Name', render: (s) => <span className="font-medium text-gray-900">{s.name}</span>},
                            {header: 'Report', render: (s) => <span className="text-gray-600">{s.definition_name}</span>},
                            {header: 'Cadence', render: (s) => <span className="text-gray-600">{cadenceLabel(s)}</span>},
                            {header: 'Format', render: (s) => <span className="uppercase text-gray-600">{s.format}</span>},
                            {header: 'Delivery', render: (s) => (
                                <Badge variant={s.delivery === 'target' ? 'purple' : 'info'}>
                                    {s.delivery === 'target' ? (s.delivery_target_code ?? 'target') : s.delivery}
                                </Badge>
                            )},
                            {header: 'Status', render: (s) => (
                                <button
                                    type="button"
                                    onClick={() => toggle.mutate(s.id)}
                                    title={s.is_enabled ? 'Click to pause' : 'Click to enable'}
                                >
                                    <Badge variant={s.is_enabled ? 'success' : 'default'}>
                                        {s.is_enabled ? 'Enabled' : 'Paused'}
                                    </Badge>
                                </button>
                            )},
                            {header: 'Last Run', render: (s) => (
                                <span className="text-gray-600">
                                    {s.last_run_at ? formatRelative(s.last_run_at) : '—'}
                                </span>
                            )},
                            {header: 'Actions', align: 'right', render: (s) => (
                                <div className="flex justify-end gap-1">
                                    <Button variant="outline" size="sm" loading={runningId === s.id}
                                            icon={<Play className="h-3.5 w-3.5"/>}
                                            onClick={() => void runNow(s)}>
                                        Run now
                                    </Button>
                                    <Button variant="ghost" size="sm" aria-label={`Edit ${s.name}`} onClick={() => {
                                        setEditing(s);
                                        setFormOpen(true);
                                    }}>
                                        <Pencil className="h-4 w-4"/>
                                    </Button>
                                    <Button variant="ghost" size="sm" aria-label={`Delete ${s.name}`}
                                            onClick={() => setDeleting(s)}>
                                        <Trash2 className="h-4 w-4 text-danger"/>
                                    </Button>
                                </div>
                            )},
                        ]}
                    />
                </Card>
            )}

            <Modal open={formOpen} onClose={() => setFormOpen(false)}
                   title={editing ? `Edit "${editing.name}"` : 'New Report Schedule'} size="lg">
                <ScheduleForm key={editing?.id ?? 'new'} existing={editing}
                              definitions={definitions} onDone={() => setFormOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={() => {
                    if (!deleting) return;
                    remove.mutate(deleting.id, {
                        onSuccess: () => {
                            notify.success(`"${deleting.name}" deleted`);
                            setDeleting(null);
                        },
                        onError: (e) => {
                            notify.error(apiErrorMessage(e, 'Could not delete schedule'));
                            setDeleting(null);
                        },
                    });
                }}
                title="Delete schedule"
                message={`Delete "${deleting?.name ?? ''}"? Future runs will stop; past executions are kept.`}
                confirmLabel="Delete"
                variant="danger"
            />
        </>
    );
}


function ScheduleForm({existing, definitions, onDone}: {
    existing: ReportSchedule | null;
    definitions: ReportDefinition[];
    onDone: () => void;
}) {
    const qc = useQueryClient();
    const [name, setName] = useState(existing?.name ?? '');
    const [definitionCode, setDefinitionCode] = useState(existing?.definition_code ?? '');
    const [format, setFormat] = useState<ReportFormat>(existing?.format ?? 'xlsx');
    const [frequency, setFrequency] = useState<Frequency>(existing ? frequencyOf(existing) : 'daily');
    const [hour, setHour] = useState(existing?.cron_hour ?? '6');
    const [minute, setMinute] = useState(existing?.cron_minute ?? '0');
    const [dayOfWeek, setDayOfWeek] = useState(
        existing && existing.cron_day_of_week !== '*' ? existing.cron_day_of_week : '1');
    const [dayOfMonth, setDayOfMonth] = useState(
        existing && existing.cron_day_of_month !== '*' ? existing.cron_day_of_month : '1');
    const [delivery, setDelivery] = useState<ScheduleDelivery>(existing?.delivery ?? 'both');
    const [deliveryTarget, setDeliveryTarget] = useState<string>(
        existing?.delivery_target != null ? String(existing.delivery_target) : '');
    const [roleCodes, setRoleCodes] = useState((existing?.recipients.roles ?? []).join(', '));
    const [paramValues, setParamValues] = useState<Record<string, string>>(() => {
        const out: Record<string, string> = {};
        for (const [k, v] of Object.entries(existing?.parameters ?? {})) out[k] = String(v);
        return out;
    });
    const [serverError, setServerError] = useState<string | null>(null);

    const definition = definitions.find((d) => d.code === definitionCode) ?? null;

    // Delivery-target listing needs system_admin; fetch lazily and degrade to an empty list.
    const {data: targetsData} = useQuery({
        queryKey: ['reports', 'delivery-targets'],
        queryFn: () => reportService.listDeliveryTargets(),
        enabled: delivery === 'target',
        retry: false,
    });
    const targets: DeliveryTarget[] = targetsData?.results ?? [];

    const save = useMutation({
        mutationFn: (payload: ReportSchedulePayload) =>
            existing
                ? reportService.updateSchedule(existing.id, payload)
                : reportService.createSchedule(payload),
        onSuccess: () => {
            void qc.invalidateQueries({queryKey: KEY});
            notify.success(existing ? 'Schedule updated' : 'Schedule created');
            onDone();
        },
        onError: (e) => setServerError(apiErrorMessage(e, 'Could not save schedule')),
    });

    const submit = () => {
        setServerError(null);
        if (!definition) return;
        const roles = roleCodes.split(',').map((r) => r.trim()).filter(Boolean);
        save.mutate({
            name: name.trim(),
            definition_code: definition.code,
            parameters: buildScheduleParameters(definition, paramValues),
            format,
            cron_minute: String(Number(minute) || 0),
            cron_hour: String(Number(hour) || 0),
            cron_day_of_week: frequency === 'weekly' ? dayOfWeek : '*',
            cron_day_of_month: frequency === 'monthly' ? dayOfMonth : '*',
            cron_month_of_year: '*',
            recipients: roles.length > 0 ? {roles} : {},
            delivery,
            delivery_target: delivery === 'target' && deliveryTarget ? Number(deliveryTarget) : null,
        });
    };

    const valid = name.trim() && definition
        && (delivery !== 'target' || deliveryTarget !== '');

    const formatOptions = (definition?.default_formats ?? ['xlsx']).map(
        (f) => ({value: f, label: f.toUpperCase()}));

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" value={name} onChange={(e) => setName(e.target.value)}
                       placeholder="e.g. Monthly payout register"/>
                <Select label="Report" value={definitionCode} placeholder="Select a report…"
                        onChange={(e) => setDefinitionCode(e.target.value)}
                        options={definitions.map((d) => ({value: d.code, label: d.name}))}/>
            </div>

            {definition && definition.param_schema.length > 0 && (
                <div className="grid grid-cols-2 gap-4 rounded-lg border border-gray-200 p-4">
                    {definition.param_schema.map((field) =>
                        field.key === 'period' ? (
                            <Select
                                key={field.key}
                                label={field.label}
                                options={[
                                    {value: 'current', label: 'Current period (at run time)'},
                                    {value: 'last_month', label: 'Last closed month'},
                                ]}
                                value={paramValues.period ?? 'current'}
                                onChange={(e) => setParamValues((p) => ({...p, period: e.target.value}))}
                            />
                        ) : (
                            <ParamField
                                key={field.key}
                                field={field}
                                value={paramValues[field.key] ?? ''}
                                onChange={(v) => setParamValues((p) => ({...p, [field.key]: v}))}
                            />
                        ),
                    )}
                </div>
            )}

            <div className="grid grid-cols-2 gap-4">
                <Select label="Frequency" value={frequency}
                        onChange={(e) => setFrequency(e.target.value as Frequency)}
                        options={[
                            {value: 'daily', label: 'Daily'},
                            {value: 'weekly', label: 'Weekly'},
                            {value: 'monthly', label: 'Monthly'},
                        ]}/>
                {frequency === 'weekly' && (
                    <Select label="Day of week" value={dayOfWeek}
                            onChange={(e) => setDayOfWeek(e.target.value)} options={DOW_OPTIONS}/>
                )}
                {frequency === 'monthly' && (
                    <Input label="Day of month" type="number" min={1} max={28} value={dayOfMonth}
                           onChange={(e) => setDayOfMonth(e.target.value)}
                           hint="1–28 so the run never skips a short month."/>
                )}
                <Input label="Hour (IST)" type="number" min={0} max={23} value={hour}
                       onChange={(e) => setHour(e.target.value)}/>
                <Input label="Minute" type="number" min={0} max={59} value={minute}
                       onChange={(e) => setMinute(e.target.value)}/>
                <Select label="Format" value={format}
                        onChange={(e) => setFormat(e.target.value as ReportFormat)}
                        options={formatOptions}/>
                <Select label="Delivery" value={delivery}
                        onChange={(e) => setDelivery(e.target.value as ScheduleDelivery)}
                        options={DELIVERY_OPTIONS}/>
            </div>

            {delivery === 'target' ? (
                <div>
                    <Select label="Delivery target" value={deliveryTarget} placeholder="Select a target…"
                            onChange={(e) => setDeliveryTarget(e.target.value)}
                            options={targets.map((t) => ({value: String(t.id), label: `${t.name} (${t.code})`}))}/>
                    <p className="mt-1 text-xs text-gray-400">
                        {targets.length === 0
                            ? 'No delivery targets available — configure them under Admin › Delivery Targets.'
                            : 'One extract per run is generated in your scope and pushed here.'}
                    </p>
                </div>
            ) : (
                <Input label="Recipient role codes" value={roleCodes}
                       onChange={(e) => setRoleCodes(e.target.value)}
                       placeholder="finance, national_head"
                       hint="Comma-separated role codes. Each recipient gets the report in THEIR access scope; users without the report's permission are skipped."/>
            )}

            {serverError && <p className="text-sm text-danger">{serverError}</p>}
            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button onClick={submit} loading={save.isPending} disabled={!valid}>
                    {existing ? 'Save changes' : 'Create schedule'}
                </Button>
            </div>
        </div>
    );
}

/** Like buildParameters, but keeps the relative 'period' token (current/last_month) as a string. */
function buildScheduleParameters(
    definition: ReportDefinition,
    values: Record<string, string>,
): Record<string, unknown> {
    const raw = {...values};
    const period = raw.period;
    delete raw.period;
    const parameters = buildParameters(definition.param_schema.filter((f) => f.key !== 'period'), raw);
    if (definition.param_schema.some((f) => f.key === 'period')) {
        parameters.period = period || 'current';
    }
    return parameters;
}
