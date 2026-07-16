import {useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {ChevronDown, ChevronRight, IndianRupee} from 'lucide-react';
import {incentiveService} from '../../services/incentiveService';
import {targetService} from '../../services/targetService';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Select} from '../../components/ui/Select';
import {Spinner} from '../../components/ui/Spinner';
import {EmptyState} from '../../components/ui/EmptyState';
import {StatusBadge} from '../../components/ui/StatusBadge';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {formatCurrency} from '../../utils/format';

/** Partner payouts — MY payouts only (backend enforces own_only), newest first. */
export default function PartnerPayouts() {
    const [openId, setOpenId] = useState<number | null>(null);
    const [periodFilter, setPeriodFilter] = useState('');
    const {data, isLoading} = useQuery({
        queryKey: ['incentives', 'payouts', 'own'] as const,
        queryFn: () => incentiveService.listPayouts({page_size: 50}),
    });
    const {data: periodsResp} = useQuery({
        queryKey: ['targets', 'periods'] as const,
        queryFn: () => targetService.listPeriods(),
    });
    const periodById = useMemo(
        () => new Map((periodsResp?.results ?? []).map((p) => [p.id, p])),
        [periodsResp],
    );
    const payouts = data?.results ?? [];

    // Group by period, newest period first (payouts within keep API order).
    const groups = useMemo(() => {
        const filtered = periodFilter
            ? payouts.filter((p) => String(p.target_period) === periodFilter)
            : payouts;
        const byPeriod = new Map<number, typeof filtered>();
        for (const p of filtered) {
            const list = byPeriod.get(p.target_period) ?? [];
            list.push(p);
            byPeriod.set(p.target_period, list);
        }
        return Array.from(byPeriod.entries()).sort(([a], [b]) => {
            const pa = periodById.get(a)?.start_date ?? '';
            const pb = periodById.get(b)?.start_date ?? '';
            return pb.localeCompare(pa) || b - a;
        });
    }, [payouts, periodFilter, periodById]);

    const periodOptions = useMemo(() => {
        const ids = Array.from(new Set(payouts.map((p) => p.target_period)));
        ids.sort((a, b) => {
            const pa = periodById.get(a)?.start_date ?? '';
            const pb = periodById.get(b)?.start_date ?? '';
            return pb.localeCompare(pa) || b - a;
        });
        return [
            {value: '', label: 'All periods'},
            ...ids.map((id) => ({value: String(id), label: periodById.get(id)?.name ?? `Period ${id}`})),
        ];
    }, [payouts, periodById]);

    return (
        <div className="space-y-4 p-4">
            <div className="flex items-center justify-between gap-3">
                <h1 className="text-lg font-bold text-gray-900">My Payouts</h1>
                {payouts.length > 0 && (
                    <div className="w-40">
                        <Select aria-label="Filter by period" value={periodFilter}
                                onChange={(e) => setPeriodFilter(e.target.value)}
                                options={periodOptions}/>
                    </div>
                )}
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : payouts.length === 0 ? (
                <Card><EmptyState icon={IndianRupee} title="No payouts yet"
                                  description="Your incentive payouts appear here after each payout run."/></Card>
            ) : (
                <div className="space-y-4">
                    {groups.map(([periodId, rows]) => (
                        <section key={periodId}>
                            <h2 className="sticky top-0 z-10 -mx-4 bg-gray-50/95 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 backdrop-blur">
                                {periodById.get(periodId)?.name ?? `Period ${periodId}`}
                            </h2>
                            <div className="mt-2 space-y-3">
                                {rows.map((p) => (
                        <Card key={p.id} padding="none">
                            <button type="button" className="flex w-full items-center justify-between p-4 text-left"
                                    aria-expanded={openId === p.id}
                                    onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                                <div>
                                    <p className="text-sm font-semibold text-gray-900">{p.scheme_code}</p>
                                    <div className="mt-1 flex items-center gap-2">
                                        <StatusBadge status={p.run_status}/>
                                        {p.gatekeeper_status === 'failed' && <Badge variant="danger">Gate failed</Badge>}
                                        {p.gatekeeper_status === 'exempted' && <Badge variant="purple">Exempted</Badge>}
                                        {p.has_exception && <Badge variant="purple">Exception</Badge>}
                                    </div>
                                </div>
                                <div className="flex items-center gap-2">
                                    <div className="text-right">
                                        <p className="text-lg font-bold text-gray-900">{formatCurrency(p.total_payout)}</p>
                                        <p className="text-[11px] text-gray-500">
                                            {parseFloat(p.total_multiplier).toFixed(2)}× weighted multiplier
                                        </p>
                                    </div>
                                    {openId === p.id
                                        ? <ChevronDown className="h-4 w-4 text-gray-400"/>
                                        : <ChevronRight className="h-4 w-4 text-gray-400"/>}
                                </div>
                            </button>
                            {openId === p.id && <PayoutLines payoutId={p.id}/>}
                        </Card>
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            )}
        </div>
    );
}

function PayoutLines({payoutId}: { payoutId: number }) {
    const {data: detail, isLoading} = useQuery({
        queryKey: ['incentives', 'payout', payoutId] as const,
        queryFn: () => incentiveService.getPayout(payoutId),
    });

    if (isLoading) return <div className="flex justify-center py-4"><Spinner/></div>;
    if (!detail) return null;

    return (
        <div className="border-t border-gray-100 px-4 py-3">
            {detail.gate_results.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5">
                    {detail.gate_results.map((g) => (
                        <span key={g.kpi_code}
                              className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                                  g.passed ? 'border-success-100 bg-success-50 text-success'
                                           : 'border-danger-100 bg-danger-50 text-danger'}`}>
                            {g.passed ? '✓' : '✗'} {g.kpi_code} {parseFloat(g.achievement_pct)}%
                        </span>
                    ))}
                </div>
            )}
            <div className="space-y-2">
                {detail.line_items.map((line) => (
                    <div key={line.id} className="flex items-center justify-between text-sm">
                        <div>
                            <p className="font-medium text-gray-800">{line.kpi_code}</p>
                            <p className="text-[11px] text-gray-400">
                                {parseFloat(line.achievement_pct).toFixed(1)}% ·{' '}
                                {parseFloat(line.applied_multiplier)}× · weight {parseFloat(line.weightage)}%
                            </p>
                        </div>
                        <p className="font-semibold text-gray-900">{formatCurrency(line.line_payout)}</p>
                    </div>
                ))}
            </div>
            <p className="mt-3 border-t border-gray-100 pt-2 text-xs text-gray-500">
                Variable pay {formatCurrency(detail.variable_pay_amount)} → eligible{' '}
                {formatCurrency(detail.eligible_vp)} → final <strong>{formatCurrency(detail.total_payout)}</strong>
            </p>
        </div>
    );
}
