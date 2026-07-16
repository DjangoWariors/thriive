import { useState } from 'react';
import { Pencil, Trash2, Copy } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Spinner } from '../ui/Spinner';
import { Select } from '../ui/Select';
import { InfoTooltip } from '../ui/InfoTooltip';
import { useKpi, useKpiVersions } from '../../hooks/useKpi';
import { describeKpi } from '../../routes/kpi/describeKpi';
import { kpiFormula } from '../../routes/kpi/kpiFormula';
import type { KpiType, KPIDefinition } from '../../types/kpi';

const TYPE_LABEL: Record<KpiType, string> = {
    value: 'Total amount',
    count: 'Count',
    count_distinct: 'Unique count',
    ratio: 'Ratio',
    growth: 'Growth',
    composite: 'Blended',
    boolean: 'Met / not-met',
    external: 'External feed',
};

function Detail({ label, value }: { label: string; value: string }) {
    return (
        <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
            <p className="text-sm text-gray-800">{value || '—'}</p>
        </div>
    );
}

export function KpiDetailDrawer({
    id,
    onClose,
    onEdit,
    onRetire,
    onDuplicate,
    canWrite,
}: {
    id: number | null;
    onClose: () => void;
    onEdit: (id: number) => void;
    onRetire: (kpi: { id: number; code: string; name: string }) => void;
    onDuplicate?: (id: number) => void;
    canWrite: boolean;
}) {
    const { data: kpi, isLoading } = useKpi(id);
    const { data: versions } = useKpiVersions(id);

    return (
        <Modal
            open={id !== null}
            onClose={onClose}
            title={kpi ? kpi.name : 'KPI'}
            description={kpi ? kpi.code : undefined}
            size="2xl"
            footer={
                canWrite && kpi ? (
                    <>
                        <Button variant="ghost" icon={<Trash2 className="h-4 w-4 text-danger" />} onClick={() => onRetire(kpi)}>
                            Retire
                        </Button>
                        {onDuplicate && (
                            <Button variant="outline" icon={<Copy className="h-4 w-4" />} onClick={() => onDuplicate(kpi.id)}>
                                Duplicate
                            </Button>
                        )}
                        <Button icon={<Pencil className="h-4 w-4" />} onClick={() => onEdit(kpi.id)}>
                            Edit
                        </Button>
                    </>
                ) : undefined
            }
        >
            {isLoading || !kpi ? (
                <div className="flex justify-center py-12"><Spinner size="lg" /></div>
            ) : (
                <div className="space-y-5">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Formula</p>
                        <p className="mt-0.5 font-mono text-sm text-gray-800">{kpiFormula(kpi)}</p>
                        <p className="mt-2 text-xs font-medium uppercase tracking-wide text-gray-400">What this KPI measures</p>
                        <p className="mt-0.5 text-sm text-gray-700">{describeKpi(kpi)}</p>
                    </div>

                    {kpi.description && <p className="text-sm text-gray-600">{kpi.description}</p>}

                    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                        <Detail label="Type" value={TYPE_LABEL[kpi.kpi_type]} />
                        <Detail label="Category" value={kpi.category} />
                        <Detail label="Unit" value={kpi.unit} />
                        <Detail label="Decimals" value={String(kpi.decimal_places)} />
                    </div>

                    <div>
                        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                            Scope
                            <InfoTooltip content="Roles and channels this KPI is scoped to. 'All roles · all channels' = no restriction." />
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                            {kpi.applicable_entity_types.length === 0 && kpi.channel_filter.length === 0 ? (
                                <Badge variant="default">All roles · all channels</Badge>
                            ) : (
                                <>
                                    {kpi.applicable_entity_types.map((t) => <Badge key={t} variant="info">{t}</Badge>)}
                                    {kpi.channel_filter.map((c) => <Badge key={c} variant="purple">{c}</Badge>)}
                                </>
                            )}
                        </div>
                    </div>

                    <VersionHistory versions={versions ?? []} />
                </div>
            )}
        </Modal>
    );
}

function VersionHistory({ versions }: { versions: KPIDefinition[] }) {
    const [comparing, setComparing] = useState(false);
    const sorted = [...versions].sort((a, b) => b.version - a.version);
    const [left, setLeft] = useState<number | null>(null);
    const [right, setRight] = useState<number | null>(null);

    // Default the two compare slots to the latest two versions once data is available.
    const leftV = sorted.find((v) => v.version === left) ?? sorted[0];
    const rightV = sorted.find((v) => v.version === right) ?? sorted[1] ?? sorted[0];
    const options = sorted.map((v) => ({ value: String(v.version), label: `v${v.version}${v.is_current ? ' (current)' : ''}` }));

    return (
        <div>
            <div className="mb-1.5 flex items-center justify-between">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                    Version history
                    <InfoTooltip content="Every edit creates a new version; older versions are kept so past targets, achievements and payouts stay reproducible. Each line shows what that version measured." />
                </p>
                {versions.length > 1 && (
                    <button
                        type="button"
                        onClick={() => setComparing((c) => !c)}
                        className="text-xs font-medium text-primary hover:underline"
                    >
                        {comparing ? 'Hide compare' : 'Compare versions'}
                    </button>
                )}
            </div>

            {comparing && versions.length > 1 ? (
                <div className="grid grid-cols-2 gap-3">
                    {[
                        { v: leftV, set: setLeft, val: String(leftV?.version ?? '') },
                        { v: rightV, set: setRight, val: String(rightV?.version ?? '') },
                    ].map(({ v, set, val }, i) => (
                        <div key={i} className="rounded-lg border border-gray-200 p-3">
                            <Select aria-label={`Version to compare (${i === 0 ? 'left' : 'right'})`} value={val} onChange={(e) => set(Number(e.target.value))} options={options} />
                            <p className="mt-2 text-xs text-gray-500">
                                {v?.effective_from} → {v?.effective_to ?? 'now'}
                            </p>
                            <p className="mt-1 text-sm text-gray-700">{v ? describeKpi(v) : '—'}</p>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                    {sorted.map((v) => (
                        <div key={v.version} className="px-3 py-2 text-sm">
                            <div className="flex items-center justify-between">
                                <span className="flex items-center gap-2">
                                    <Badge variant={v.is_current ? 'success' : 'default'}>v{v.version}</Badge>
                                    {v.is_current && <span className="text-xs text-success">current</span>}
                                </span>
                                <span className="text-xs text-gray-500">
                                    {v.effective_from} → {v.effective_to ?? 'now'}
                                </span>
                            </div>
                            <p className="mt-1 text-xs text-gray-500">{describeKpi(v)}</p>
                        </div>
                    ))}
                    {sorted.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">Just this version so far.</p>
                    )}
                </div>
            )}
        </div>
    );
}
