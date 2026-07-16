import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Crosshair } from 'lucide-react';
import { usePersonView } from '../../hooks/useTargets';
import type { GridOwner } from '../../types/target';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { StatusBadge } from '../ui/StatusBadge';
import { TableSkeleton } from '../ui/Skeleton';
import { apiErrorMessage } from '../../utils/apiError';

interface PersonTargetDrawerProps {
  /** The person clicked in the grid; null keeps the drawer closed. */
  owner: GridOwner | null;
  periodId: number;
  kpiId: number;
  /** Admins previewing a draft plan see its numbers; everywhere else only live plans count. */
  includeDraft?: boolean;
  onClose: () => void;
}

function inr(value: string | null): string {
  if (value === null || value === '') return '—';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

/**
 * "What does this person carry, in total?" — the derived rollup of every territory
 * they own, opened from the plan grid's owner column. Read-only: targets are planned
 * by territory; this is just the person-axis reading of them.
 */
export function PersonTargetDrawer({ owner, periodId, kpiId, includeDraft, onClose }: PersonTargetDrawerProps) {
  const { data, isLoading, error } = usePersonView(
    owner ? { entity_id: owner.entity_id, period_id: periodId, kpi_id: kpiId,
              ...(includeDraft ? { include_draft: true } : {}) } : null,
  );

  useEffect(() => {
    if (!owner) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [owner, onClose]);

  if (!owner) return null;

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-xl animate-in slide-in-from-right duration-200"
        role="dialog"
        aria-modal="true"
        aria-label={`Target details for ${owner.name}`}
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <Avatar name={owner.name} size="lg" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{owner.name}</h2>
              <p className="text-sm text-gray-500">{owner.type} · {owner.code}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-4 rounded-lg p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <TableSkeleton />
          ) : error ? (
            <EmptyState icon={Crosshair} title="Not available"
                        description={apiErrorMessage(error, 'This person is outside your area.')} />
          ) : data ? (
            <>
              <div className="mb-5 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-gray-200 border-t-4 border-t-primary bg-white p-4">
                  <p className="text-xs uppercase tracking-wide text-gray-500">Total target</p>
                  <p className="mt-1 text-xl font-bold text-gray-900">₹{inr(data.target)}</p>
                </div>
                <div className="rounded-xl border border-gray-200 border-t-4 border-t-blue-500 bg-white p-4">
                  <p className="text-xs uppercase tracking-wide text-gray-500">Territories owned</p>
                  <p className="mt-1 text-xl font-bold text-gray-900">{data.owned_node_count}</p>
                </div>
              </div>
              <p className="mb-3 text-xs text-gray-400">
                Derived from the territories they own — planned by territory, never edited here.
              </p>
              {data.rows.length === 0 ? (
                <EmptyState icon={Crosshair} title="No targets yet"
                            description="No target has been planned on the territories this person owns." />
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                      <th className="py-2 pr-3 font-medium">Territory</th>
                      <th className="py-2 pr-3 font-medium">SKU group</th>
                      <th className="py-2 pr-3 text-right font-medium">Target</th>
                      <th className="py-2 text-center font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={r.allocation_id} className="border-b border-gray-100">
                        <td className="py-2 pr-3 font-medium text-gray-900">
                          {r.geography_node ?? r.geography_code ?? '—'}
                          {r.channel && <Badge variant="default" className="ml-1.5">{r.channel}</Badge>}
                        </td>
                        <td className="py-2 pr-3 text-gray-600">{r.sku_group ?? 'All'}</td>
                        <td className="py-2 pr-3 text-right font-medium tabular-nums text-gray-800">₹{inr(r.target)}</td>
                        <td className="py-2 text-center"><StatusBadge status={r.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
