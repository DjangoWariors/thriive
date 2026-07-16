import {useEffect, useMemo, useRef} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Target, TrendingUp, IndianRupee, AlertTriangle} from 'lucide-react';
import {targetService} from '../../services/targetService';
import {useDashboard} from '../../hooks/useAchievements';
import {pickDefaultPeriod, usePeriodSelector} from '../../hooks/usePeriodSelector';
import {Card} from '../../components/ui/Card';
import {EmptyState} from '../../components/ui/EmptyState';
import {ProgressBar} from '../../components/ui/ProgressBar';
import {CardGridSkeleton} from '../../components/ui/Skeleton';
import {formatCurrency, formatNumber} from '../../utils/format';
import {cn} from '../../utils/cn';

/** Partner home — MY targets and achievements for a period (own_only data). */
export default function PartnerDashboard() {
    const {selectedPeriodId, setSelectedPeriodId} = usePeriodSelector();

    const {data: periodsResp} = useQuery({
        queryKey: ['targets', 'periods'] as const,
        queryFn: () => targetService.listPeriods(),
    });
    const monthly = useMemo(
        () => (periodsResp?.results ?? []).filter((p) => p.period_type === 'monthly'),
        [periodsResp],
    );
    // Default to the month covering today (shared logic with the admin header).
    const today = new Date().toISOString().slice(0, 10);
    const periodId = selectedPeriodId ?? pickDefaultPeriod(monthly)?.id ?? null;

    const {data, isLoading, isError, refetch} = useDashboard(periodId);

    const selectedPeriod = monthly.find((p) => p.id === periodId) ?? null;
    const periodInProgress = selectedPeriod !== null && selectedPeriod.end_date >= today;

    // Keep the selected month chip visible in the swipeable strip.
    const chipStripRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        chipStripRef.current
            ?.querySelector('[aria-pressed="true"]')
            ?.scrollIntoView({inline: 'center', block: 'nearest'});
    }, [periodId]);

    return (
        <div className="space-y-4 p-4">
            <h1 className="text-lg font-bold text-gray-900">My Performance</h1>

            {monthly.length > 0 && (
                <div ref={chipStripRef} className="-mx-4 overflow-x-auto px-4">
                    <div className="flex w-max gap-2 pb-1">
                        {monthly.map((p) => (
                            <button
                                key={p.id}
                                type="button"
                                aria-pressed={p.id === periodId}
                                onClick={() => setSelectedPeriodId(p.id)}
                                className={cn(
                                    'min-h-11 whitespace-nowrap rounded-full border px-4 text-sm font-medium transition-colors',
                                    p.id === periodId
                                        ? 'border-primary bg-primary text-white'
                                        : 'border-gray-200 bg-white text-gray-600 hover:border-primary/40',
                                )}
                            >
                                {p.name}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {periodId === null ? (
                <Card><EmptyState icon={Target} title="No plan periods yet"
                                  description="Your targets appear here once the company publishes a plan period."/></Card>
            ) : isLoading ? (
                <CardGridSkeleton/>
            ) : isError ? (
                <Card><EmptyState icon={AlertTriangle} title="Couldn't load your performance"
                                  description="Something went wrong while fetching this month's data."
                                  actionLabel="Retry" onAction={() => void refetch()}/></Card>
            ) : !data || data.kpi_cards.length === 0 ? (
                <Card><EmptyState icon={Target} title="No targets for this period"
                                  description="Targets and achievements will appear here once assigned."/></Card>
            ) : (
                <>
                    {periodInProgress && (
                        <p className="rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
                            This month is still in progress — figures update daily and are provisional
                            until the period closes.
                        </p>
                    )}

                    {/* Headline summary */}
                    <div className="grid grid-cols-2 gap-3">
                        <Card>
                            <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                <TrendingUp className="h-3.5 w-3.5"/> Achievement
                            </p>
                            <p className="mt-1 text-2xl font-bold text-gray-900">
                                {parseFloat(data.summary.overall_achievement_pct).toFixed(1)}%
                            </p>
                            <p className="text-xs text-gray-500">
                                pacing to {parseFloat(data.summary.projected_pct).toFixed(0)}%
                            </p>
                        </Card>
                        <Card>
                            <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                                <IndianRupee className="h-3.5 w-3.5"/> Estimated payout
                            </p>
                            <p className="mt-1 text-2xl font-bold text-gray-900">
                                {data.summary.estimated_payout !== null
                                    ? formatCurrency(data.summary.estimated_payout)
                                    : '—'}
                            </p>
                            <p className="text-xs text-gray-500">
                                {data.summary.estimated_payout !== null
                                    ? 'from the latest payout run'
                                    : 'available after the payout run'}
                            </p>
                        </Card>
                    </div>

                    {/* Per-KPI target vs achievement */}
                    <div className="space-y-3">
                        {data.kpi_cards.map((card) => {
                            const pct = Math.min(150, parseFloat(card.pct));
                            return (
                                <Card key={card.id}>
                                    <div className="flex items-baseline justify-between">
                                        <p className="text-sm font-semibold text-gray-900">{card.kpi_name}</p>
                                        <p className="text-sm font-bold text-gray-900">{parseFloat(card.pct).toFixed(1)}%</p>
                                    </div>
                                    <p className="mt-0.5 text-xs text-gray-500">
                                        {formatNumber(card.achieved)} of{' '}
                                        {formatNumber(card.target)} {card.unit}
                                        {card.multiplier !== null && ` · ${parseFloat(card.multiplier)}× slab`}
                                    </p>
                                    <div className="mt-2">
                                        <ProgressBar value={pct} max={100}/>
                                    </div>
                                    {parseFloat(card.gap) > 0 && (
                                        <p className="mt-1 text-[11px] text-gray-400">
                                            Gap {formatNumber(card.gap)} {card.unit} · need{' '}
                                            {formatNumber(card.required_run_rate)}/day to close
                                        </p>
                                    )}
                                </Card>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}
