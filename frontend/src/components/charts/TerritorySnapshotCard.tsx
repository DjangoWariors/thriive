import { useNavigate } from 'react-router';
import { Map } from 'lucide-react';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { useTerritoryGrid } from '../../hooks/useAchievements';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { ProgressBar } from '../ui/ProgressBar';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { formatPct } from '../../utils/format';

/** Top-level territory plan tracking for the primary KPI — links into the full grid. */
export function TerritorySnapshotCard({ periodId }: { periodId: number }) {
  const navigate = useNavigate();
  const { data: kpisResp, isLoading: kpisLoading } = useKpiDefinitions();
  const kpi = kpisResp?.results?.[0] ?? null;
  const { data, isLoading } = useTerritoryGrid(
    kpi ? { kpi: kpi.id, period: periodId, page_size: 5 } : null,
  );

  return (
    <Card padding="md">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">Territory Plan Tracking</p>
          <p className="text-[11px] uppercase tracking-wide text-gray-500">{kpi?.name ?? '—'}</p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/achievements?view=territory&period=${periodId}`)}
        >
          View grid →
        </Button>
      </div>

      {kpisLoading || isLoading ? (
        <div className="mt-3 space-y-3" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} variant="rect" height={28} />
          ))}
        </div>
      ) : !kpi || !data || data.rows.length === 0 ? (
        <EmptyState
          icon={Map}
          title="No territory targets"
          description="Committed plan targets appear here once a plan is published for this period."
          className="py-6"
        />
      ) : (
        <ul className="mt-3 space-y-2.5">
          {data.rows.map((row) => (
            <li key={row.node_id}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="truncate font-medium text-gray-800">{row.name}</span>
                <span className="ml-2 shrink-0 font-semibold text-gray-700">
                  {row.achievement_pct !== null ? formatPct(row.achievement_pct) : '—'}
                </span>
              </div>
              <ProgressBar value={row.achievement_pct !== null ? Number(row.achievement_pct) : 0} size="sm" />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
