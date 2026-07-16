import { useState } from 'react';
import { ChevronRight, Home, MapPin } from 'lucide-react';
import { useTerritoryGrid } from '../../hooks/useAchievements';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Pagination } from '../ui/Pagination';
import { ProgressBar } from '../ui/ProgressBar';
import { SimpleTable } from '../ui/SimpleTable';
import { TableSkeleton } from '../ui/Skeleton';
import { formatCurrency, formatPct, makeUnitFormatter } from '../../utils/format';
import type { TerritoryGridRow } from '../../types/achievement';

interface Props {
  kpi: number;
  period: number;
  channelId?: number;
  skuGroup?: number;
  /** Territory to open at (e.g. a plan's root) — omitted, the grid starts at the tree roots. */
  rootId?: number;
  rootLabel?: string;
  /** KPI display unit ('₹', 'outlets', …) — non-currency KPIs render plain numbers. */
  unit?: string;
  decimalPlaces?: number;
}

/** Plan-tracking grid: target vs actual per territory, drilled one geography level at a
 * time (lazy, territory-RBAC-scoped by the backend). Reused by the achievements territory
 * view and the target plan's Actuals mode. */
export function TerritoryActualsGrid({
  kpi, period, channelId, skuGroup, rootId, rootLabel = 'All territories', unit, decimalPlaces,
}: Props) {
  const currency = !unit || unit === '₹' || unit.toUpperCase() === 'INR';
  const fmt = currency
    ? (v: string | null) => (v === null || v === '' ? '—' : formatCurrency(v))
    : makeUnitFormatter(unit, decimalPlaces);
  const [stack, setStack] = useState<{ id: number | null; name: string }[]>(
    [{ id: rootId ?? null, name: rootLabel }]);
  const [page, setPage] = useState(1);
  const current = stack[stack.length - 1];

  const { data, isLoading } = useTerritoryGrid({
    kpi, period, page,
    ...(current.id !== null ? { parent: current.id } : {}),
    ...(channelId ? { channel_id: channelId } : {}),
    ...(skuGroup ? { sku_group: skuGroup } : {}),
  });

  const push = (row: TerritoryGridRow) => {
    setStack((s) => [...s, { id: row.node_id, name: row.name }]);
    setPage(1);
  };
  const jumpTo = (idx: number) => {
    setStack((s) => s.slice(0, idx + 1));
    setPage(1);
  };
  const noActualsYet = !!data && data.rows.length > 0 && data.rows.every((r) => r.actual === null);

  return (
    <div className="space-y-3">
      <nav className="flex flex-wrap items-center gap-1 text-sm">
        {stack.map((crumb, i) => (
          <span key={`${crumb.id}-${i}`} className="flex items-center gap-1">
            {i > 0 && <ChevronRight size={14} className="text-gray-300" />}
            <button
              type="button"
              onClick={() => jumpTo(i)}
              className={i === stack.length - 1 ? 'font-medium text-gray-900' : 'text-gray-500 hover:text-primary'}
            >
              {i === 0 ? <span className="inline-flex items-center gap-1"><Home size={13} />{crumb.name}</span> : crumb.name}
            </button>
          </span>
        ))}
      </nav>

      {isLoading ? (
        <TableSkeleton />
      ) : !data || data.rows.length === 0 ? (
        <Card>
          <EmptyState icon={MapPin} title="No territory data here"
            description="No committed targets for this KPI beneath the selected territory." />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={data.rows}
            rowKey={(r) => r.node_id}
            onRowClick={(r) => { if (r.children_count > 0) push(r); }}
            columns={[
              { header: 'Territory', render: (r) => (
                <div className="flex items-center gap-1.5">
                  <div>
                    <p className="font-medium text-gray-900">{r.name}</p>
                    <p className="text-xs text-gray-500">{r.code} · {r.level}</p>
                  </div>
                  {r.children_count > 0 && (
                    <span className="ml-1 text-xs text-gray-400">({r.children_count})</span>
                  )}
                </div>
              ) },
              { header: 'Target', align: 'right', render: (r) => (
                <span className="text-gray-600">{r.target ? fmt(r.target) : '—'}</span>) },
              { header: 'Actual', align: 'right', render: (r) => (
                <span className="font-medium text-gray-900">{r.actual ? fmt(r.actual) : '—'}</span>) },
              { header: 'Achievement', render: (r) => (
                r.achievement_pct === null ? <span className="text-gray-400">—</span> : (
                  <div className="w-28">
                    <p className="text-sm font-semibold text-gray-800">{formatPct(r.achievement_pct)}</p>
                    <ProgressBar value={Number(r.achievement_pct)} size="sm" />
                  </div>
                )
              ) },
              { header: 'Gap', align: 'right', render: (r) => (
                <span className="text-gray-500">{r.gap ? fmt(r.gap) : '—'}</span>) },
              { header: 'Run-rate needed', align: 'right', render: (r) => (
                <span className="text-gray-500">{r.run_rate_needed ? fmt(r.run_rate_needed) : '—'}</span>) },
              { header: '', align: 'right', render: (r) => (
                r.children_count > 0 ? <ChevronRight size={16} className="text-gray-300" /> : null) },
            ]}
          />
          <Pagination count={data.total} page={page} pageSize={data.page_size} onPageChange={setPage} />
          {noActualsYet && (
            <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">
              Actuals appear after the next achievement compute.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
