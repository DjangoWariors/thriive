import { useState } from 'react';
import { BellRing, Megaphone } from 'lucide-react';
import {
  useForceClose, useGapBoard, useNudge, useReviewTasks, useTransitionPlan,
} from '../../hooks/useTargets';
import { useKpiDefinitions } from '../../hooks/useKpi';
import type { GapBoard, ReviewTask, TargetPlan } from '../../types/target';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Modal } from '../ui/Modal';
import { SimpleTable, type SimpleColumn } from '../ui/SimpleTable';
import { StatusBadge } from '../ui/StatusBadge';
import { TableSkeleton } from '../ui/Skeleton';
import { Textarea } from '../ui/Textarea';
import { notify } from '../../utils/notify';
import { makeUnitFormatter } from '../../utils/format';
import { apiErrorMessage } from '../../utils/apiError';

type Fmt = (kpiCode: string) => (value: string | null) => string;

/** Stage 4 — the field review cascade, all in one panel: send it, watch the gap close,
 * remind the stragglers, and (audited) close what's left. */
export function ReviewStage({ plan }: { plan: TargetPlan }) {
  const transition = useTransitionPlan();
  const nudge = useNudge();
  const forceClose = useForceClose();
  const { data: board, isLoading } = useGapBoard(plan.id);
  const tasks = useReviewTasks({ plan: plan.id });
  const { data: kpiDefs } = useKpiDefinitions({ page_size: 200 });
  // Gap-board rows are keyed by KPI code; format each in that KPI's own unit.
  const fmtByCode: Fmt = (code) => {
    const def = kpiDefs?.results?.find((k) => k.code === code);
    return makeUnitFormatter(def?.unit, def?.decimal_places);
  };
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeReason, setCloseReason] = useState('');

  const open = plan.progress.review.open;

  if (plan.status === 'draft') {
    return (
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">Field review</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              {plan.review_levels.length
                ? `Opens one task per ${plan.review_levels.join(' / ')} owner: they check their numbers, `
                  + 'adjust within the change cap, and accept. Publish waits until everyone has answered.'
                : 'This plan has no review levels — you can publish directly, or send it for review anyway to pause edits.'}
            </p>
          </div>
          <Button size="sm" icon={<Megaphone className="h-4 w-4" />} loading={transition.isPending}
                  onClick={() => transition.mutate({ id: plan.id, status: 'in_review' }, {
                    onSuccess: () => notify.success('Sent for review — one task per territory owner.'),
                    onError: (e) => notify.error(apiErrorMessage(e, 'Could not send for review')),
                  })}>
            Send for review
          </Button>
        </div>
      </Card>
    );
  }

  if (isLoading) return <Card><TableSkeleton /></Card>;

  const taskColumns: SimpleColumn<ReviewTask>[] = [
    { header: 'Territory', render: (t) => <span className="font-medium text-gray-900">{t.node_name}</span> },
    { header: 'Level', render: (t) => <Badge variant="default">{t.node_level}</Badge> },
    { header: 'Owner', render: (t) => t.owner_name ?? <span className="text-gray-400">unowned</span> },
    { header: 'Status', align: 'center', render: (t) => <StatusBadge status={t.status} /> },
  ];

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Field review</h3>
          <p className="mt-0.5 text-xs text-gray-500">
            {open > 0
              ? `${open} territory owner(s) still to answer. Publish stays blocked until they do — or you close the rest.`
              : 'Everyone has answered — the plan is clear to publish.'}
          </p>
        </div>
        {plan.status === 'in_review' && open > 0 && (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" icon={<BellRing className="h-4 w-4" />}
                    onClick={() => nudge.mutate(plan.id, {
                      onSuccess: (r) => notify.success(`Reminder sent to ${r.nudged} owner(s)`),
                    })}>
              Send a reminder
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCloseOpen(true)}>
              Close remaining reviews
            </Button>
          </div>
        )}
      </div>

      {board && board.tasks_total > 0 && (
        <div className="mt-4 space-y-5">
          <div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="Tasks" value={`${board.tasks_total - board.tasks_open}/${board.tasks_total} answered`} />
              {board.kpis.map((k) => (
                <Stat key={k.kpi} label={`${k.kpi} gap`}
                      value={fmtByCode(k.kpi)(k.gap)} accent={Number(k.gap) !== 0} />
              ))}
            </div>
            <p className="mt-2 text-xs text-gray-400">
              Gap = what the territories currently sum to, minus the top-down number.
            </p>
          </div>
          <GapMovers board={board} fmtByCode={fmtByCode} />
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">All review tasks</h4>
            <SimpleTable columns={taskColumns} rows={tasks.data?.results ?? []} rowKey={(t) => t.id} />
          </div>
        </div>
      )}

      <Modal open={closeOpen} onClose={() => setCloseOpen(false)} title="Close the remaining reviews" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Closes every open task so the plan can publish. This is recorded in the audit trail.
          </p>
          <Textarea label="Reason" value={closeReason} onChange={(e) => setCloseReason(e.target.value)} rows={2} />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setCloseOpen(false)}>Cancel</Button>
            <Button loading={forceClose.isPending} disabled={!closeReason.trim()}
                    onClick={() => forceClose.mutate({ planId: plan.id, reason: closeReason }, {
                      onSuccess: (r) => { notify.success(`Closed ${r.force_closed} task(s)`); setCloseOpen(false); },
                      onError: (e) => notify.error(apiErrorMessage(e, 'Could not close the reviews')),
                    })}>
              Close reviews
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  );
}

function GapMovers({ board, fmtByCode }: { board: GapBoard; fmtByCode: Fmt }) {
  if (board.top_movers.length === 0) return null;
  const columns: SimpleColumn<GapBoard['top_movers'][number]>[] = [
    {
      header: 'Territory',
      render: (m) => (
        <span>
          <span className="font-medium text-gray-900">{m.geography_node}</span>
          <span className="ml-2 text-xs text-gray-400">{m.geography_node_code}</span>
        </span>
      ),
    },
    { header: 'KPI', render: (m) => m.kpi },
    { header: 'Top-down', align: 'right', render: (m) => fmtByCode(m.kpi)(m.top_down) },
    { header: 'Current', align: 'right', render: (m) => fmtByCode(m.kpi)(m.current) },
    {
      header: 'Delta', align: 'right',
      render: (m) => (
        <span className={Number(m.delta) > 0 ? 'text-green-600' : 'text-red-600'}>
          {fmtByCode(m.kpi)(m.delta)}
        </span>
      ),
    },
  ];
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Biggest movers</h4>
      <SimpleTable columns={columns} rows={board.top_movers} rowKey={(m) => `${m.geography_node_code}-${m.kpi}`} />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-lg font-bold ${accent ? 'text-amber-600' : 'text-gray-900'}`}>{value}</p>
    </div>
  );
}
