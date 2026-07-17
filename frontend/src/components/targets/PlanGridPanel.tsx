import { useMemo, useState } from 'react';
import { GitBranchPlus } from 'lucide-react';
import { useAllocationRevisions, usePlanExplain, useReviewTasks } from '../../hooks/useTargets';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { useGeographyTypes } from '../../hooks/useEntities';
import type { GridOwner, GridRow, TargetPlan, TargetRevisionEntry } from '../../types/target';
import { GeoNodeCombobox, type GeoSelection } from '../entity/GeoNodeCombobox';
import { PlanGrid } from './PlanGrid';
import { PersonTargetDrawer } from './PersonTargetDrawer';
import { TargetEditDialog } from './TargetEditDialog';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { Modal } from '../ui/Modal';
import { StatusBadge } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { TableSkeleton } from '../ui/Skeleton';
import { formatDate } from '../../utils/format';
import { formatInr as inr } from '../../utils/format';

/** The planning-grid tab: KPI sub-tabs, jump-to-territory, the lazy tree grid, and the
 * edit / explain / owner drill-ins. Serves both personas — `isAdmin` decides the edit
 * endpoint and the reset-scope label. */
export function PlanGridPanel({ plan, kpiId, setKpiId, isAdmin }: {
  plan: TargetPlan; kpiId: number; setKpiId: (id: number) => void; isAdmin: boolean;
}) {
  const tasks = useReviewTasks(plan.status === 'in_review' ? { plan: plan.id } : null);
  // Any respondable task means this reviewer can edit; the backend matches each edit
  // to the right task by territory (a reviewer may own several).
  const myOpenTask = useMemo(
    () => (tasks.data?.results ?? []).find(
      (t) => t.status === 'pending' || t.status === 'adjusted' || t.status === 'accepted') ?? null,
    [tasks.data],
  );
  const [editRow, setEditRow] = useState<GridRow | null>(null);
  const [explainRow, setExplainRow] = useState<GridRow | null>(null);
  const [ownerFor, setOwnerFor] = useState<GridOwner | null>(null);

  const { data: geoTypes } = useGeographyTypes();
  const geoTypeCode = geoTypes?.results?.[0]?.code ?? '';
  const [jumpTo, setJumpTo] = useState<GeoSelection | null>(null);
  const { data: kpiDefs } = useKpiDefinitions({ page_size: 200 });
  const kpiDef = kpiDefs?.results?.find((k) => k.id === kpiId);
  const showReview = plan.status !== 'draft' || plan.progress.review.total > 0;

  const canEdit = (row: GridRow) => {
    if (row.status === 'locked') return false;
    if (isAdmin) return ['draft', 'published', 'in_review'].includes(plan.status);
    // A placed persona edits within their territory ONLY during the review window.
    // Published numbers are read-only for the field — corrections go through HO
    // (which stays governed by change caps / maker-checker server-side).
    return plan.status === 'in_review';
  };
  // Task holders go through the review path so their task flips to adjusted/escalated.
  const editMode = !isAdmin && plan.status === 'in_review' && myOpenTask ? 'reviewer' : 'admin';

  if (plan.kpis.length === 0) {
    return <EmptyState icon={GitBranchPlus} title="No KPIs on this plan" description="Add KPIs when creating the plan." />;
  }
  return (
    <>
      <div className="px-4 pt-3">
        <Tabs activeTab={String(kpiId)} onChange={(v) => setKpiId(Number(v))}
              tabs={plan.kpis.map((k) => ({ value: String(k.kpi), label: k.kpi_name }))} />
      </div>
      <div className="flex flex-wrap items-end gap-3 px-4 pt-3">
        <div className="w-72">
          <GeoNodeCombobox typeCode={geoTypeCode} value={jumpTo} onChange={setJumpTo}
                           label="Jump to territory" placeholder="Browse from anywhere in the tree…" />
        </div>
        {jumpTo && (
          <button type="button" onClick={() => setJumpTo(null)}
                  className="pb-2 text-xs font-medium text-primary hover:underline">
            {isAdmin ? `Reset to ${plan.root_geography_name}` : 'Reset to my territory'}
          </button>
        )}
      </div>
      <div className="mt-2 overflow-x-auto">
        <PlanGrid planId={plan.id} kpiId={kpiId}
                  rootParentId={jumpTo?.id} unit={kpiDef?.unit} decimalPlaces={kpiDef?.decimal_places}
                  showReview={showReview} canEdit={canEdit}
                  onEdit={setEditRow} onExplain={setExplainRow} onOwner={setOwnerFor} />
      </div>
      <TargetEditDialog plan={plan} row={editRow} mode={editMode} onClose={() => setEditRow(null)} />
      <ExplainModal planId={plan.id} row={explainRow} onClose={() => setExplainRow(null)} />
      <PersonTargetDrawer owner={ownerFor} periodId={plan.period} kpiId={kpiId}
                          includeDraft={isAdmin && !['published', 'locked', 'closed'].includes(plan.status)}
                          onClose={() => setOwnerFor(null)} />
    </>
  );
}

function ExplainModal({ planId, row, onClose }: { planId: number; row: GridRow | null; onClose: () => void }) {
  const [tab, setTab] = useState<'explain' | 'history'>('explain');
  const { data, isLoading } = usePlanExplain(row ? planId : null, row?.geography_node_id ?? null);
  const revisions = useAllocationRevisions(row?.allocation_id ?? null);
  if (!row) return null;
  const historyCount = revisions.data?.length ?? 0;
  return (
    <Modal open onClose={onClose} title={`Why this number — ${row.name}`} size="md">
      <div className="space-y-4">
        <Tabs activeTab={tab} onChange={(v) => setTab(v as 'explain' | 'history')}
              tabs={[{ value: 'explain', label: 'System split' },
                     { value: 'history', label: `Change history${historyCount ? ` (${historyCount})` : ''}` }]} />
        {tab === 'history' ? (
          <ChangeHistory revisions={revisions.data} />
        ) : isLoading ? (
          <TableSkeleton />
        ) : !data || data.run_id === null ? (
          <p className="text-sm text-gray-500">No committed run yet — the number was set or imported manually.</p>
        ) : (
          <>
            {data.rows.map((r, i) => (
              <div key={i} className="rounded-lg border border-gray-200 p-3">
                <p className="text-sm font-medium text-gray-800">
                  {r.kpi} · {r.period}{r.sku_group ? ` · ${r.sku_group}` : ''} — ₹{inr(r.value)}
                  {r.base_value !== null && <span className="text-gray-400"> (base ₹{inr(r.base_value)})</span>}
                </p>
                <ExplainDetail explain={r.explain} />
              </div>
            ))}
            {data.rows.length === 0 && (
              <p className="text-sm text-gray-500">This run has no staged rows for this territory.</p>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

/** The human side of "why this number": every manual override and rebalance on this cell,
 * with who raised it, who decided it, and the stated reason. */
function ChangeHistory({ revisions }: { revisions?: TargetRevisionEntry[] }) {
  if (!revisions?.length) {
    return <p className="text-sm text-gray-500">No manual changes — this number is untouched since commit.</p>;
  }
  return (
    <div className="space-y-2">
      {revisions.map((r) => (
        <div key={r.id} className="rounded-lg border border-gray-100 bg-gray-50 p-2.5 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-gray-800">₹{inr(r.old_value)} → ₹{inr(r.new_value)}</span>
            {r.source === 'rebalance'
              ? <Badge variant="default" size="sm">rebalance</Badge>
              : r.band === 'escalate' && <Badge variant="warning" size="sm">escalated</Badge>}
            <StatusBadge status={r.status} />
            <span className="ml-auto text-gray-400">{formatDate(r.created_at)}</span>
          </div>
          <p className="mt-1 text-gray-500">
            by {r.requested_by_name ?? 'system'}
            {r.status !== 'pending' && r.approved_by_name && r.approved_by_name !== r.requested_by_name
              ? ` · decided by ${r.approved_by_name}` : ''}
          </p>
          {r.reason && <p className="mt-1 italic text-gray-600">“{r.reason}”</p>}
        </div>
      ))}
    </div>
  );
}

function ExplainDetail({ explain }: { explain: Record<string, unknown> }) {
  // Product-split rows: mode + any fixed off-the-top shares (the NPI-seeding case).
  const product = explain.product_split as
    | { mode?: string; fixed_mix?: Record<string, string> }
    | undefined;
  if (product) {
    const fixed = Object.entries(product.fixed_mix ?? {});
    return (
      <p className="mt-1 text-xs text-gray-500">
        {fixed.length > 0 && (
          <>Fixed share off the top: <span className="font-medium text-gray-600">
            {fixed.map(([g, p]) => `${g} ${p}%`).join(' · ')}</span>. </>
        )}
        The {fixed.length > 0 ? 'remainder splits' : 'total splits'} by this territory's own
        product mix over last year; groups with no history share equally.
      </p>
    );
  }
  // The plan-root row: where the top number came from.
  if (typeof explain.top_number === 'string') {
    return (
      <p className="mt-1 text-xs text-gray-500">
        {explain.source === 'realign_committed'
          ? 'Realign — held at the previously committed total for this subtree.'
          : 'The plan’s top number (AOP letter), cascaded down from here.'}
      </p>
    );
  }
  const components = explain.components as
    | { source: string; key?: string; weight_pct: string; share_pct: string; raw: string; no_signal?: boolean }[]
    | undefined;
  if (components) {
    return (
      <table className="mt-2 w-full text-xs text-gray-600">
        <thead><tr className="text-left uppercase text-gray-400">
          <th className="py-1">Component</th><th className="py-1 text-right">Blend</th>
          <th className="py-1 text-right">Raw</th><th className="py-1 text-right">Share</th>
        </tr></thead>
        <tbody>
          {components.map((c, i) => (
            <tr key={i}>
              <td className="py-1">{c.source}{c.key ? ` (${c.key})` : ''}{c.no_signal && <Badge variant="warning">no signal</Badge>}</td>
              <td className="py-1 text-right">{c.weight_pct}%</td>
              <td className="py-1 text-right">{c.raw}</td>
              <td className="py-1 text-right">{c.share_pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <dl className="mt-2 space-y-0.5 text-xs text-gray-500">
      {Object.entries(explain).map(([k, v]) => (
        <div key={k} className="flex gap-2"><dt className="font-medium">{k}:</dt><dd>{JSON.stringify(v)}</dd></div>
      ))}
    </dl>
  );
}
