import {type ReactNode, useMemo, useState} from 'react';
import {AlertTriangle, ArrowRightLeft, Check, MapPin, UserCog, X} from 'lucide-react';
import {notify} from '../../utils/notify';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Textarea} from '../ui/Textarea';
import {Spinner} from '../ui/Spinner';
import {ParentSearch} from './EntityForm';
import {
    useBlueprint,
    useEntitySearch,
    useMoveEntity,
    useTransferImpact,
    useTransferPerson,
} from '../../hooks/useEntities';
import {apiErrorMessage} from '../../utils/apiError';
import {cn} from '../../utils/cn';
import type {Entity, EntityListItem, TransferPersonPayload} from '../../types/entity';

interface Props {
    entity: Entity;
    onClose: () => void;
}

type Operation = 'move' | 'transfer';
type Destination = 'new_seat' | 'occupy_vacant';
type Handover = 'keep' | 'successor' | 'release';

const TODAY = new Date().toISOString().split('T')[0] as string;

export function TransferDialog({entity, onClose}: Props) {
    const [op, setOp] = useState<Operation>('transfer');
    const [destination, setDestination] = useState<Destination>('new_seat');
    const [handover, setHandover] = useState<Handover>('keep');

    // Shared
    const [reason, setReason] = useState('');
    const [effectiveDate, setEffectiveDate] = useState(TODAY);

    // Destination pickers
    const [newParent, setNewParent] = useState<EntityListItem | null>(null);
    const [vacantSeat, setVacantSeat] = useState<EntityListItem | null>(null);
    // Territory successor + optional team handling
    const [successor, setSuccessor] = useState<EntityListItem | null>(null);
    const [reassign, setReassign] = useState<EntityListItem | null>(null);

    const moveMutation = useMoveEntity();
    const transferMutation = useTransferPerson();
    const pending = moveMutation.isPending || transferMutation.isPending;

    // What this transfer touches — territories + team, straight from the backend.
    const {data: impact} = useTransferImpact(entity.id);
    const {data: seatImpact} = useTransferImpact(
        destination === 'occupy_vacant' ? (vacantSeat?.id ?? null) : null,
    );
    const territories = impact?.owned_territories ?? [];
    const seatTerritories = seatImpact?.owned_territories ?? [];

    const {data: blueprint = []} = useBlueprint();
    const allowedCodes = entity.entity_type.allowed_parent_types;
    const allowedLabels = useMemo(() => {
        const byCode = new Map(blueprint.map((t) => [t.code, t.name]));
        return allowedCodes.map((c) => byCode.get(c) ?? c);
    }, [blueprint, allowedCodes]);

    const hasReports = entity.children_count > 0;
    const teamWord = entity.children_count === 1 ? 'team member' : 'team members';
    const currentManager = entity.parent_info?.name ?? 'their current manager';
    const managerHint = allowedLabels.length > 0
        ? `You can choose a ${allowedLabels.join(' or ')}.`
        : undefined;

    const canSubmit =
        reason.trim().length > 0 &&
        (op === 'move'
            ? newParent !== null
            : (destination === 'new_seat' ? newParent !== null : vacantSeat !== null) &&
              (territories.length === 0 || handover !== 'successor' || successor !== null));

    // The review sentence — the whole change in plain words before it happens.
    const territoryCodes = territories.map((t) => t.code).join(', ');
    const summary = useMemo(() => {
        if (op === 'move') {
            return newParent
                ? `${entity.name} — and everyone under them — will report to ${newParent.name}.`
                : 'Choose the new manager to see a summary.';
        }
        const parts: string[] = [];
        if (destination === 'new_seat') {
            parts.push(newParent
                ? `${entity.name} will report to ${newParent.name}.`
                : 'Choose the new manager to see a summary.');
        } else {
            parts.push(vacantSeat
                ? `${entity.name} fills the open position “${vacantSeat.name}”.`
                : 'Choose the open position to see a summary.');
            if (seatTerritories.length > 0) {
                parts.push(`They take over ${seatTerritories.map((t) => t.code).join(', ')} — those areas come with the position.`);
            }
        }
        if (territories.length > 0) {
            if (handover === 'successor') {
                parts.push(successor
                    ? `Their ${territories.length === 1 ? 'area' : `${territories.length} areas`} (${territoryCodes}) pass to ${successor.name}.`
                    : 'Choose who takes over their areas.');
            } else if (handover === 'release') {
                parts.push(`Their areas (${territoryCodes}) are left open until someone new is chosen.`);
            } else {
                parts.push(`They keep covering ${territoryCodes}.`);
            }
        }
        if (hasReports) {
            parts.push(`Their ${entity.children_count} ${teamWord} stay with ${reassign?.name ?? currentManager}.`);
        }
        return parts.join(' ');
    }, [op, destination, handover, newParent, vacantSeat, successor, reassign, territories,
        seatTerritories, entity.name, entity.children_count, hasReports, teamWord,
        currentManager, territoryCodes]);

    function handleSubmit() {
        if (op === 'move') {
            if (!newParent) return;
            moveMutation.mutate(
                {id: entity.id, data: {new_parent_id: newParent.id, reason: reason.trim(), effective_date: effectiveDate}},
                {
                    onSuccess: () => {
                        notify.success(`${entity.name} was moved to ${newParent.name}.`);
                        onClose();
                    },
                    onError: (e) => notify.error(apiErrorMessage(e, 'We couldn’t move them there. Please choose a different manager and try again.')),
                },
            );
            return;
        }

        const payload: TransferPersonPayload = {
            mode: destination,
            reason: reason.trim(),
            effective_date: effectiveDate,
            territory_handover: territories.length > 0 ? handover : 'keep',
            reassign_reports_to: reassign?.id ?? null,
            ...(destination === 'new_seat'
                ? {new_parent_id: newParent!.id}
                : {target_entity_id: vacantSeat!.id}),
            ...(handover === 'successor' && successor ? {successor_id: successor.id} : {}),
        };

        transferMutation.mutate(
            {id: entity.id, payload},
            {
                onSuccess: () => {
                    notify.success(`${entity.name} was transferred. Everything moved together — position, areas and team handling.`);
                    onClose();
                },
                onError: (e) => notify.error(apiErrorMessage(e, 'We couldn’t finish this transfer. Check the choices above and try again.')),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Transfer ${entity.name}`}
            description={`${entity.entity_type.name}${entity.parent_info ? ` · reports to ${entity.parent_info.name}` : ''}`}
            size="xl"
            footer={
                <>
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button onClick={handleSubmit} loading={pending} disabled={!canSubmit}>
                        {op === 'move' ? 'Move team' : 'Confirm transfer'}
                    </Button>
                </>
            }
        >
            <div className="space-y-5">
                {/* 1 — What kind of move? */}
                <div className="grid grid-cols-2 gap-2">
                    <OpCard
                        active={op === 'transfer'}
                        onClick={() => setOp('transfer')}
                        icon={<UserCog className="h-4 w-4"/>}
                        title="Move this person"
                        subtitle="Same job, new place — their team stays where it is"
                    />
                    <OpCard
                        active={op === 'move'}
                        onClick={() => setOp('move')}
                        icon={<ArrowRightLeft className="h-4 w-4"/>}
                        title="Move the whole team"
                        subtitle="This person and everyone under them move together"
                    />
                </div>

                {op === 'move' ? (
                    <>
                        {hasReports && (
                            <Notice tone="amber" icon={<AlertTriangle className="mt-0.5 h-4 w-4 shrink-0"/>}>
                                Everyone reporting to {entity.name} moves too — that’s{' '}
                                <strong>{entity.children_count}</strong> {teamWord}.
                            </Notice>
                        )}
                        <Field label="Who should they report to now?" hint={managerHint}>
                            <ParentSearch
                                allowedTypes={allowedCodes}
                                allowedTypeLabels={allowedLabels}
                                value={newParent}
                                onChange={setNewParent}
                            />
                        </Field>
                    </>
                ) : (
                    <>
                        {/* 2 — Where do they land? */}
                        <div className="grid grid-cols-2 gap-2">
                            <OpCard
                                active={destination === 'new_seat'}
                                onClick={() => setDestination('new_seat')}
                                title="Set up a new position"
                                subtitle="Place them under a new manager"
                            />
                            <OpCard
                                active={destination === 'occupy_vacant'}
                                onClick={() => setDestination('occupy_vacant')}
                                title="Fill an open position"
                                subtitle="Take over a position that’s currently empty"
                            />
                        </div>

                        {destination === 'new_seat' ? (
                            <Field label="Who will they report to?" hint={managerHint}>
                                <ParentSearch
                                    allowedTypes={allowedCodes}
                                    allowedTypeLabels={allowedLabels}
                                    value={newParent}
                                    onChange={setNewParent}
                                />
                            </Field>
                        ) : (
                            <>
                                <Field label="Which open position?" hint={`Showing open ${entity.entity_type.name} positions`}>
                                    <VacantSeatSearch
                                        typeCode={entity.entity_type.code}
                                        value={vacantSeat}
                                        onChange={setVacantSeat}
                                    />
                                </Field>
                                {seatTerritories.length > 0 && (
                                    <Notice tone="blue" icon={<MapPin className="mt-0.5 h-4 w-4 shrink-0"/>}>
                                        This position already looks after{' '}
                                        <strong>{seatTerritories.map((t) => t.name).join(', ')}</strong> —{' '}
                                        {entity.name} will take those over automatically.
                                    </Notice>
                                )}
                            </>
                        )}

                        {/* 3 — Who takes over their areas? */}
                        {territories.length > 0 && (
                            <div className="space-y-2">
                                <p className="text-sm font-medium text-gray-700">
                                    Who takes over their {territories.length === 1 ? 'area' : 'areas'}?
                                    <span className="ml-2 font-normal text-gray-500">
                                        {territories.map((t) => t.name).join(', ')}
                                    </span>
                                </p>
                                <div className="grid grid-cols-3 gap-2">
                                    <OpCard
                                        active={handover === 'keep'}
                                        onClick={() => setHandover('keep')}
                                        title="They keep them"
                                        subtitle="Coverage doesn’t change"
                                    />
                                    <OpCard
                                        active={handover === 'successor'}
                                        onClick={() => setHandover('successor')}
                                        title="Hand them over"
                                        subtitle="Someone else takes over"
                                    />
                                    <OpCard
                                        active={handover === 'release'}
                                        onClick={() => setHandover('release')}
                                        title="Leave open"
                                        subtitle="Assign someone later"
                                    />
                                </div>
                                {handover === 'successor' && (
                                    <Field
                                        label="Who takes over?"
                                        hint="All their areas pass to this person on the effective date."
                                    >
                                        <ParentSearch allowedTypes={[]} allowedTypeLabels={[]} value={successor} onChange={setSuccessor}/>
                                    </Field>
                                )}
                                {handover === 'release' && (
                                    <Notice tone="amber" icon={<AlertTriangle className="mt-0.5 h-4 w-4 shrink-0"/>}>
                                        Sales keep counting for these areas, but no one is credited for them
                                        until you assign a new owner on <strong>Territory Owners</strong>.
                                    </Notice>
                                )}
                            </div>
                        )}

                        {hasReports && (
                            <Field
                                label="Who will look after their team? (optional)"
                                hint={`Leave blank to keep the team with ${currentManager}. Pick someone else if that doesn’t fit.`}
                            >
                                <ParentSearch allowedTypes={[]} allowedTypeLabels={[]} value={reassign} onChange={setReassign}/>
                            </Field>
                        )}
                    </>
                )}

                {/* 4 — Review */}
                <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <p className="text-sm text-gray-700">
                        <span className="font-medium">Handover date</span>{' '}
                        <input
                            type="date"
                            value={effectiveDate}
                            onChange={(e) => setEffectiveDate(e.target.value)}
                            aria-label="Handover date"
                            className="mx-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-sm
                               focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                        />{' '}
                        — {summary}
                    </p>
                    <p className="text-xs text-gray-500">
                        Sales in any handed-over areas count for the current owner until this date,
                        and for the new owner from this date. Usually today — change it only if the
                        handover really happens on a different day.
                    </p>
                    <Textarea
                        label="Reason for this change"
                        placeholder="e.g. promotion, transfer, or a change of area"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        rows={2}
                    />
                </div>
            </div>
        </Modal>
    );
}


function OpCard({active, onClick, icon, title, subtitle}: {
    active: boolean;
    onClick: () => void;
    icon?: ReactNode;
    title: string;
    subtitle: string;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'rounded-lg border px-3 py-2 text-left transition-colors',
                active ? 'border-primary bg-primary-50 ring-1 ring-primary/20' : 'border-gray-200 bg-white hover:bg-gray-50',
            )}
        >
            <span className={cn('flex items-center gap-1.5 text-sm font-medium', active ? 'text-primary-dark' : 'text-gray-900')}>
                {icon}{title}
            </span>
            <span className="mt-0.5 block text-xs text-gray-500">{subtitle}</span>
        </button>
    );
}

function Field({label, hint, children}: {label: string; hint?: string; children: ReactNode}) {
    return (
        <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
            {children}
            {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
        </div>
    );
}

function Notice({tone, icon, children}: {tone: 'amber' | 'blue'; icon: ReactNode; children: ReactNode}) {
    return (
        <div className={cn(
            'flex items-start gap-2 rounded-lg px-3 py-2 text-sm',
            tone === 'amber' ? 'bg-warning-50 text-warning' : 'bg-blue-50 text-blue-800',
        )}>
            {icon}
            <span>{children}</span>
        </div>
    );
}

/** Search the open positions (no one assigned yet) of the same kind. */
function VacantSeatSearch({typeCode, value, onChange}: {
    typeCode: string;
    value: EntityListItem | null;
    onChange: (item: EntityListItem | null) => void;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);
    const {data: results, isLoading} = useEntitySearch(q, typeCode);
    const vacant = (results ?? []).filter((r) => r.status === 'vacant');

    if (value) {
        return (
            <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <span className="flex min-w-0 items-center gap-2 text-sm">
                    <Check className="h-4 w-4 shrink-0 text-success"/>
                    <span className="truncate font-medium text-gray-900">{value.name}</span>
                </span>
                <button
                    type="button"
                    onClick={() => onChange(null)}
                    className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                    aria-label="Clear selected position"
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
                placeholder="Search open positions by name…"
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
            {open && q.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                    {isLoading && (
                        <div className="flex justify-center py-2"><Spinner size="sm"/></div>
                    )}
                    {!isLoading && vacant.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">No open positions found.</p>
                    )}
                    {vacant.map((r) => (
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
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-gray-500">Open</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
