import { useState } from 'react';
import { useCommitRun, useDiscardRun, useRunPreview, useRunStagedRows } from '../../hooks/useTargets';
import type { PlanRun } from '../../types/target';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Pagination } from '../ui/Pagination';
import { notify } from '../../utils/notify';
import { formatInr as inr } from '../../utils/format';
import { apiErrorMessage } from '../../utils/apiError';

const STAGED_PAGE_SIZE = 25;

const RUN_KIND_LABELS: Record<string, string> = {
  spatial: 'Territory split', product: 'Product split', realign: 'Realignment',
};

/** A staged run's review-and-apply surface: diff stats, the what-changes table, the
 * override-collision keep/drop choice, and the Apply/Discard actions. Nothing touches the
 * plan until Apply. */
export function StagedRunReview({ run }: { run: PlanRun }) {
  const { data: preview } = useRunPreview(run.id);
  const commit = useCommitRun();
  const discard = useDiscardRun();
  const [strategy, setStrategy] = useState<'keep' | 'drop'>('keep');
  const [showChanges, setShowChanges] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [allPage, setAllPage] = useState(1);
  const { data: staged } = useRunStagedRows(run.id, allPage, showAll);
  const collisions = preview?.override_collisions ?? [];
  const collisionCount = preview?.override_collision_count ?? 0;

  const title = run.kind === 'realign' && run.scope_node_code
    ? `Realignment of ${run.scope_node_code}`
    : RUN_KIND_LABELS[run.kind] ?? run.kind;

  return (
    <Card className="border-blue-200 bg-blue-50/50">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-800">{title} ready to review — nothing changes until you apply it</p>
          <p className="mt-0.5 text-xs text-gray-500">
            Review the changes, then Apply to put these numbers on the plan — or Discard and
            re-run with different settings.
          </p>
          {preview && (
            <p className="mt-1 text-xs text-gray-500">
              {preview.staged_rows} rows · {preview.new} new · {preview.changed} changed · {preview.unchanged} unchanged
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {preview && preview.top_deltas.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setShowChanges((v) => !v)}>
              {showChanges ? 'Hide changes' : 'What changes?'}
            </Button>
          )}
          {preview && preview.staged_rows > 0 && (
            <Button variant="outline" size="sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? 'Hide staged rows' : 'View staged rows'}
            </Button>
          )}
          <Button variant="outline" size="sm" loading={discard.isPending}
                  onClick={() => discard.mutate(run.id, { onSuccess: () => notify.success('Discarded — nothing changed') })}>
            Discard
          </Button>
          <Button size="sm" loading={commit.isPending}
                  onClick={() => commit.mutate({ runId: run.id, strategy }, {
                    onSuccess: (s) => notify.success(`Applied — ${s.created + s.updated} territories updated`),
                    onError: (e) => notify.error(apiErrorMessage(e, 'Could not apply the run')),
                  })}>
            Apply to plan
          </Button>
        </div>
      </div>

      {showChanges && preview && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-blue-100 bg-white p-2">
          <table className="w-full text-xs text-gray-600">
            <thead><tr className="text-left uppercase text-gray-400">
              <th className="px-2 py-1">Territory</th><th className="px-2 py-1">KPI</th>
              <th className="px-2 py-1 text-right">Current</th><th className="px-2 py-1 text-right">Staged</th>
            </tr></thead>
            <tbody>
              {preview.top_deltas.map((d, i) => (
                <tr key={i}>
                  <td className="px-2 py-1 font-medium text-gray-800">{d.geography_node}</td>
                  <td className="px-2 py-1">{d.kpi}</td>
                  <td className="px-2 py-1 text-right">{inr(d.from)}</td>
                  <td className="px-2 py-1 text-right">{inr(d.to)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-2 pt-1 text-[11px] text-gray-400">
            Largest moves first{preview.changed > preview.top_deltas.length
              ? ` — showing ${preview.top_deltas.length} of ${preview.changed} changed rows` : ''}.
          </p>
        </div>
      )}

      {showAll && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-blue-100 bg-white p-2">
          <table className="w-full text-xs text-gray-600">
            <thead><tr className="text-left uppercase text-gray-400">
              <th className="px-2 py-1">Territory</th><th className="px-2 py-1">Level</th>
              <th className="px-2 py-1">KPI</th><th className="px-2 py-1">Product</th>
              <th className="px-2 py-1 text-right">Staged</th><th className="px-2 py-1 text-right">Base</th>
            </tr></thead>
            <tbody>
              {(staged?.results ?? []).map((r, i) => (
                <tr key={i}>
                  <td className="px-2 py-1 font-medium text-gray-800">
                    {r.geography_node} <span className="text-gray-400">{r.geography_node_code}</span>
                  </td>
                  <td className="px-2 py-1">{r.level}</td>
                  <td className="px-2 py-1">{r.kpi}</td>
                  <td className="px-2 py-1">{r.sku_group ?? '—'}</td>
                  <td className="px-2 py-1 text-right">₹{inr(r.value)}</td>
                  <td className="px-2 py-1 text-right text-gray-400">
                    {r.base_value !== null ? `₹${inr(r.base_value)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-2 pt-1">
            <Pagination count={staged?.count ?? 0} page={allPage} pageSize={STAGED_PAGE_SIZE}
                        onPageChange={setAllPage} />
          </div>
          <p className="px-2 pt-1 text-[11px] text-gray-400">
            Every generated row — the full split before it's applied, changed or not.
          </p>
        </div>
      )}

      {collisionCount > 0 && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-800">
            {collisionCount} manual edit(s) sit on numbers this run would change:
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-amber-700">
            {collisions.slice(0, 5).map((c, i) => (
              <li key={i}>{c.geography_node} · {c.kpi} — manual {inr(c.override)}, new system number {inr(c.staged)}</li>
            ))}
            {collisionCount > 5 && <li>…and {collisionCount - 5} more</li>}
          </ul>
          <div className="mt-2 space-y-1 text-xs text-gray-700">
            <label className="flex items-center gap-2">
              <input type="radio" name="override-strategy" checked={strategy === 'keep'}
                     onChange={() => setStrategy('keep')} />
              Keep the manual edits — the system number updates underneath them
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="override-strategy" checked={strategy === 'drop'}
                     onChange={() => setStrategy('drop')} />
              Replace the manual edits with the new system numbers
            </label>
          </div>
        </div>
      )}
    </Card>
  );
}
