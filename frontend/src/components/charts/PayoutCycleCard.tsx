import { useNavigate } from 'react-router';
import { CalendarClock } from 'lucide-react';
import { useCycles } from '../../hooks/useIncentives';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { StatusBadge } from '../ui/StatusBadge';
import { Skeleton } from '../ui/Skeleton';
import { formatCurrency } from '../../utils/format';

/** Month-close status for the selected period. Render only for `final_payout` holders —
 * this component owns its query, so an unauthorized user never triggers the request. */
export function PayoutCycleCard({ periodId }: { periodId: number }) {
  const navigate = useNavigate();
  const { data, isLoading } = useCycles({ period: periodId });
  const cycle = data?.results?.[0] ?? null;

  return (
    <Card padding="md">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">Payout Cycle</p>
          <p className="text-[11px] uppercase tracking-wide text-gray-500">
            {cycle?.period_name ?? 'Month-close'}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate('/incentives/cycles')}>
          Open workspace →
        </Button>
      </div>

      {isLoading ? (
        <div className="mt-3 space-y-3" aria-busy="true">
          <Skeleton variant="rect" height={28} />
          <Skeleton variant="rect" height={28} />
        </div>
      ) : cycle === null ? (
        <div className="mt-4 flex items-center gap-3 text-sm text-gray-500">
          <CalendarClock className="h-5 w-5 shrink-0 text-gray-300" />
          <span>Not opened yet — the month-close cycle for this period hasn't been started.</span>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">Stage</span>
            <StatusBadge status={cycle.status} />
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">Total payout</span>
            <span className="font-semibold text-gray-800">
              {Number(cycle.total_payout) > 0 ? formatCurrency(cycle.total_payout) : '—'}
            </span>
          </div>
          {cycle.disbursed_at !== null && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">Disbursed</span>
              <span className="text-gray-700">{new Date(cycle.disbursed_at).toLocaleDateString()}</span>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
