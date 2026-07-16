import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, BellRing, Check, ChevronRight, GitBranchPlus, Megaphone, Shuffle,
} from 'lucide-react';
import {
  useAcceptTask, useAdjustMine, useAllocationRevisions, useCommitRun, useCostPreview,
  useDiscardRun, useForceClose, useGapBoard, useModifyAllocation, useNudge, usePeriodTree,
  usePlan, usePlanExplain, useRealign, useReviewTasks, useRunPreview, useRuns,
  useSetPlanTop, useStartRun, useTransitionPlan,
} from '../../hooks/useTargets';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { useKpiDefinitions } from '../../hooks/useKpi';
import type {
  GapBoard, GridOwner, GridRow, PlanRun, ReviewTask, TargetPlan, TargetRevisionEntry,
} from '../../types/target';
import { useGeographyTypes } from '../../hooks/useEntities';
import { GeoNodeCombobox, type GeoSelection } from '../../components/entity/GeoNodeCombobox';
import { Select } from '../../components/ui/Select';
import { PlanGrid } from '../../components/targets/PlanGrid';
import { TerritoryActualsGrid } from '../../components/data/TerritoryActualsGrid';
import { AdjustTargetModal } from '../../components/targets/AdjustTargetModal';
import { PersonTargetDrawer } from '../../components/targets/PersonTargetDrawer';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { PageHeader } from '../../components/ui/PageHeader';
import { SimpleTable, type SimpleColumn } from '../../components/ui/SimpleTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Tabs } from '../../components/ui/Tabs';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { Textarea } from '../../components/ui/Textarea';
import { notify } from '../../utils/notify';
import { formatDate } from '../../utils/format';
import { flattenPeriods } from '../../utils/periods';
import { apiErrorMessage } from '../../utils/apiError';

function inr(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export default function PlanWorkspacePage() {
  const { id } = useParams();
  const planId = Number(id);
  const navigate = useNavigate();
  const { user } = useAuth();
  const { canWrite } = useRBAC();
  const { data: plan, isLoading } = usePlan(planId);
  // Plan-wide operators are unplaced writers; placed users are reviewers of their territory.
  const isAdmin = canWrite('target_management') && !user?.entity_info;

  if (isLoading || !plan) {
    return <div className="p-6"><TableSkeleton /></div>;
  }
  return <Workspace plan={plan} isAdmin={isAdmin} onBack={() => navigate('/targets')} />;
}

function Workspace({ plan, isAdmin, onBack }: { plan: TargetPlan; isAdmin: boolean; onBack: () => void }) {
  const [tab, setTab] = useState<'grid' | 'review' | 'actuals'>('grid');
  const [kpiId, setKpiId] = useState<number>(plan.kpis[0]?.kpi ?? 0);
  const qc = useQueryClient();
  // All recent runs (not just staged): useRuns polls while one is pending/running, so an
  // async Celery run surfaces its staged banner without a manual refresh.
  const runs = useRuns(isAdmin ? { plan: plan.id } : null);
  const runRows = useMemo(() => runs.data?.results ?? [], [runs.data]);
  const stagedRun = runRows.find((r) => r.status === 'staged') ?? null;
  const hasActiveRun = runRows.some((r) => r.status === 'pending' || r.status === 'running');
  const wasActive = useRef(false);
  useEffect(() => {
    // A run settling changes plan progress + baseline suggestions — refresh the plan.
    if (wasActive.current && !hasActiveRun) void qc.invalidateQueries({ queryKey: ['targets', 'plans'] });
    wasActive.current = hasActiveRun;
  }, [hasActiveRun, qc]);

  return (
    <div className="p-6">
      <PageHeader
        className="mb-5"
        title={plan.name}
        description={`${plan.period_code} · ${plan.root_geography_name} · ${plan.kpis.length} KPI(s)`}
        actions={<>
          <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={onBack}>All plans</Button>
          <StatusBadge status={plan.status} />
        </>}
      />

      <div className="grid gap-5 lg:grid-cols-[16rem_1fr]">
        <div className="space-y-4">
          <StageRail plan={plan} isAdmin={isAdmin} />
          {isAdmin && <AdminActions plan={plan} />}
        </div>

        <div className="min-w-0 space-y-4">
          {isAdmin && stagedRun && <StagedRunCard run={stagedRun} />}
          <Card padding="none">
            <div className="px-4 pt-2">
              <Tabs activeTab={tab} onChange={(v) => setTab(v as 'grid' | 'review' | 'actuals')}
                    tabs={[{ value: 'grid', label: 'Planning grid' },
                           { value: 'review', label: `Review & gap${plan.progress.review.open ? ` (${plan.progress.review.open})` : ''}` },
                           { value: 'actuals', label: 'Actuals' }]} />
            </div>
            {tab === 'grid' ? (
              <GridPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} isAdmin={isAdmin} />
            ) : tab === 'review' ? (
              <ReviewPanel plan={plan} isAdmin={isAdmin} />
            ) : (
              <ActualsPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---- actuals (plan tracking) -------------------------------------------------
function ActualsPanel({ plan, kpiId, setKpiId }:
  { plan: TargetPlan; kpiId: number; setKpiId: (id: number) => void }) {
  const { data: kpiDefs } = useKpiDefinitions({ page_size: 200 });
  const kpiDef = kpiDefs?.results?.find((k) => k.id === kpiId);
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <Tabs activeTab={String(kpiId)} onChange={(v) => setKpiId(Number(v))}
              tabs={plan.kpis.map((k) => ({ value: String(k.kpi), label: k.kpi_name }))} />
        <span className="text-xs text-gray-500">Target vs actual per territory · {plan.period_code}</span>
      </div>
      {kpiId > 0 ? (
        <TerritoryActualsGrid kpi={kpiId} period={plan.period}
          channelId={plan.channel ?? undefined}
          rootId={plan.root_geography} rootLabel={plan.root_geography_name}
          unit={kpiDef?.unit} decimalPlaces={kpiDef?.decimal_places}
          key={`${kpiId}-${plan.channel ?? 0}`} />
      ) : (
        <EmptyState icon={ChevronRight} title="No KPIs" description="This plan has no KPIs to track." />
      )}
    </div>
  );
}

// ---- stage rail --------------------------------------------------------------
function StageRail({ plan, isAdmin }: { plan: TargetPlan; isAdmin: boolean }) {
  const startRun = useStartRun();
  const transition = useTransitionPlan();
  const [topOpen, setTopOpen] = useState(false);
  const [overBudgetMsg, setOverBudgetMsg] = useState<string | null>(null);

  const committed = plan.progress.committed_stages;
  const steps: { key: string; label: string; done: boolean; action?: () => void; actionLabel?: string }[] = [
    {
      key: 'baseline', label: 'Baseline',
      done: plan.kpis.some((k) => k.derived_top_value !== null),
      action: () => run('baseline'), actionLabel: 'Run',
    },
    {
      key: 'top', label: 'Top numbers',
      done: plan.kpis.every((k) => k.top_value !== null),
      action: () => setTopOpen(true), actionLabel: 'Set',
    },
    { key: 'spatial', label: 'Territory split', done: committed.includes('spatial'),
      action: () => run('spatial'), actionLabel: 'Run' },
    ...(plan.product_scope.length ? [{
      key: 'product', label: 'Product split', done: committed.includes('product' as never),
      action: () => run('product'), actionLabel: 'Run',
    }] : []),
    { key: 'review', label: 'Field review', done: plan.status !== 'draft',
      action: () => move('in_review'), actionLabel: 'Open' },
    { key: 'publish', label: 'Publish', done: ['published', 'locked', 'closed'].includes(plan.status),
      action: () => move('published'), actionLabel: 'Publish' },
  ];

  function run(kind: string) {
    startRun.mutate({ planId: plan.id, kind }, {
      onSuccess: (r) => notify.success(r.status === 'staged'
        ? `${kind} run staged — review and commit it.` : `${kind} run ${r.status}.`),
      onError: (e) => notify.error(apiErrorMessage(e, `Could not run ${kind}`)),
    });
  }
  function move(status: string, force = false) {
    transition.mutate({ id: plan.id, status, force }, {
      onSuccess: () => notify.success(status === 'in_review' ? 'Review cascade opened.' : `Plan ${status}.`),
      onError: (e) => {
        const msg = apiErrorMessage(e, 'Transition blocked');
        // The budget gate is recoverable: offer an explicit, audited over-budget publish.
        if (status === 'published' && msg.includes('exceeds the plan budget')) {
          setOverBudgetMsg(msg);
        } else {
          notify.error(msg);
        }
      },
    });
  }

  const editable = isAdmin && plan.status === 'draft';
  return (
    <Card>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Plan pipeline</h3>
      <ol className="space-y-2">
        {steps.map((s) => (
          <li key={s.key} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-sm">
              <span className={`flex h-5 w-5 items-center justify-center rounded-full ${
                s.done ? 'bg-primary text-white' : 'border border-gray-300 text-gray-300'}`}>
                {s.done ? <Check className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </span>
              <span className={s.done ? 'text-gray-800' : 'text-gray-500'}>{s.label}</span>
            </span>
            {s.action && ((s.key === 'review' && isAdmin && plan.status === 'draft')
              || (s.key === 'publish' && isAdmin && ['draft', 'in_review'].includes(plan.status))
              || (editable && !['review', 'publish'].includes(s.key))) && (
              <Button variant="ghost" size="sm" onClick={s.action} loading={startRun.isPending || transition.isPending}>
                {s.actionLabel}
              </Button>
            )}
          </li>
        ))}
      </ol>
      <TopNumbersModal plan={plan} open={topOpen} onClose={() => setTopOpen(false)} />
      <ConfirmDialog open={overBudgetMsg !== null} onClose={() => setOverBudgetMsg(null)}
                     title="Publish over budget?" variant="warning"
                     message={`${overBudgetMsg ?? ''} Publishing anyway is recorded in the audit trail.`}
                     confirmLabel="Publish anyway"
                     onConfirm={() => move('published', true)} />
    </Card>
  );
}

function TopNumbersModal({ plan, open, onClose }: { plan: TargetPlan; open: boolean; onClose: () => void }) {
  const setTop = useSetPlanTop();
  const [values, setValues] = useState<Record<number, string>>({});

  return (
    <Modal open={open} onClose={onClose} title="Top numbers (Stage 2)" size="md">
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          Type the AOP number for each KPI. The derived suggestion (baseline × growth) is your sanity anchor.
        </p>
        {plan.kpis.map((k) => (
          <div key={k.id} className="flex items-end gap-3">
            <div className="flex-1">
              <Input label={k.kpi_name} type="number"
                     value={values[k.kpi] ?? k.top_value ?? ''}
                     onChange={(e) => setValues({ ...values, [k.kpi]: e.target.value })}
                     hint={k.derived_top_value !== null ? `Suggested: ₹${inr(k.derived_top_value)}` : 'Run the baseline for a suggestion'} />
            </div>
            <Button variant="outline" size="sm" loading={setTop.isPending}
                    disabled={!(values[k.kpi] ?? k.top_value)}
                    onClick={() => setTop.mutate(
                      { id: plan.id, kpiId: k.kpi, value: values[k.kpi] ?? k.top_value! },
                      { onSuccess: () => notify.success(`${k.kpi_code} top number saved`),
                        onError: (e) => notify.error(apiErrorMessage(e, 'Could not save')) })}>
              Save
            </Button>
          </div>
        ))}
        <div className="flex justify-end"><Button variant="outline" onClick={onClose}>Close</Button></div>
      </div>
    </Modal>
  );
}

// ---- admin side actions (realign, nudge, force-close) -------------------------
function AdminActions({ plan }: { plan: TargetPlan }) {
  const realign = useRealign();
  const nudge = useNudge();
  const forceClose = useForceClose();
  const { data: geoTypes } = useGeographyTypes();
  const geoTypeCode = geoTypes?.results?.[0]?.code ?? '';
  const [realignOpen, setRealignOpen] = useState(false);
  const [scope, setScope] = useState<GeoSelection | null>(null);
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeReason, setCloseReason] = useState('');

  const canRealign = plan.progress.committed_stages.includes('spatial')
    && ['draft', 'in_review', 'published'].includes(plan.status);
  return (
    <Card>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Controls</h3>
      <div className="space-y-2">
        {canRealign && (
          <Button variant="outline" size="sm" className="w-full" icon={<Shuffle className="h-4 w-4" />}
                  onClick={() => setRealignOpen(true)}>
            Realign a subtree
          </Button>
        )}
        {plan.status === 'in_review' && (
          <>
            <Button variant="outline" size="sm" className="w-full" icon={<BellRing className="h-4 w-4" />}
                    onClick={() => nudge.mutate(plan.id, {
                      onSuccess: (r) => notify.success(`Nudged ${r.nudged} owner(s)`),
                    })}>
              Nudge pending owners
            </Button>
            <Button variant="outline" size="sm" className="w-full" icon={<Megaphone className="h-4 w-4" />}
                    onClick={() => setCloseOpen(true)}>
              Force-close review
            </Button>
          </>
        )}
      </div>

      <Modal open={realignOpen} onClose={() => setRealignOpen(false)} title="Realign a changed subtree" size="md">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            {/*Mid-period territory churn: re-split only the changed subtree. Its committed total stays*/}
            {/*fixed; the rest of the plan is untouched. Overrides inside are surfaced before commit.*/}

            Mid-period Territory Realignment: Re-split only the affected subtree. The committed total
            remains unchanged, the rest of the plan is unaffected, and manual overrides are highlighted before commit
          </p>
          <GeoNodeCombobox typeCode={geoTypeCode} value={scope} onChange={setScope} label="Changed subtree root" />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setRealignOpen(false)}>Cancel</Button>
            <Button loading={realign.isPending} disabled={!scope}
                    onClick={() => realign.mutate({ planId: plan.id, scopeNodeId: scope!.id }, {
                      onSuccess: () => { notify.success('Realignment staged — review and commit it.'); setRealignOpen(false); },
                      onError: (e) => notify.error(apiErrorMessage(e, 'Could not realign')),
                    })}>
              Run
            </Button>
          </div>
        </div>
      </Modal>

      <CostOfPlan plan={plan} />

      <Modal open={closeOpen} onClose={() => setCloseOpen(false)} title="Force-close the review" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Closes every open task so the plan can publish. Audited.</p>
          <Textarea label="Reason" value={closeReason} onChange={(e) => setCloseReason(e.target.value)} rows={2} />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setCloseOpen(false)}>Cancel</Button>
            <Button loading={forceClose.isPending} disabled={!closeReason.trim()}
                    onClick={() => forceClose.mutate({ planId: plan.id, reason: closeReason }, {
                      onSuccess: (r) => { notify.success(`Closed ${r.force_closed} task(s)`); setCloseOpen(false); },
                      onError: (e) => notify.error(apiErrorMessage(e, 'Could not force-close')),
                    })}>
              Force-close
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  );
}

function CostOfPlan({ plan }: { plan: TargetPlan }) {
  // The finance publish gate: only meaningful once a budget is configured on the plan.
  const hasBudget = plan.settings?.payout_budget != null;
  const { data } = useCostPreview(plan.id, hasBudget);
  if (!hasBudget || !data) return null;
  return (
    <div className="mt-4 border-t border-gray-100 pt-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Cost of plan</h4>
      <dl className="space-y-1 text-sm">
        {Object.entries(data.scenarios).map(([pct, total]) => (
          <div key={pct} className="flex justify-between">
            <dt className="text-gray-500">At {pct}% achievement</dt>
            <dd className="font-medium text-gray-800">₹{inr(total)}</dd>
          </div>
        ))}
        <div className="flex justify-between border-t border-gray-100 pt-1">
          <dt className="text-gray-500">Budget</dt>
          <dd className={data.over_budget_at_100 ? 'font-semibold text-red-600' : 'font-medium text-gray-800'}>
            ₹{inr(data.budget)}{data.over_budget_at_100 && ' — exceeded'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

// ---- staged run banner ---------------------------------------------------------
const RUN_KIND_LABELS: Record<string, string> = {
  baseline: 'Baseline', spatial: 'Territory split', product: 'Product split', realign: 'Realign',
};

function StagedRunCard({ run }: { run: PlanRun }) {
  const { data: preview } = useRunPreview(run.id);
  const commit = useCommitRun();
  const discard = useDiscardRun();
  const [strategy, setStrategy] = useState<'keep' | 'drop'>('keep');
  const [showChanges, setShowChanges] = useState(false);
  const collisions = preview?.override_collisions ?? [];
  const collisionCount = preview?.override_collision_count ?? 0;

  const title = run.kind === 'realign' && run.scope_node_code
    ? `Realign of ${run.scope_node_code}`
    : RUN_KIND_LABELS[run.kind] ?? run.kind;

  return (
    <Card className="border-blue-200 bg-blue-50/50">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-800">{title} — staged, not applied yet</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {run.kind === 'baseline'
              ? 'Reference data: it feeds the top-number suggestion and is never committed. Discard it when you are done reviewing.'
              : 'The plan is untouched so far. Review the changes, then Commit to put these numbers on the plan — or Discard and re-run with different settings.'}
          </p>
          {preview && run.kind !== 'baseline' && (
            <p className="mt-1 text-xs text-gray-500">
              {preview.staged_rows} rows · {preview.new} new · {preview.changed} changed · {preview.unchanged} unchanged
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {preview && preview.top_deltas.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setShowChanges((v) => !v)}>
              {showChanges ? 'Hide changes' : 'What changes?'}
            </Button>
          )}
          <Button variant="outline" size="sm" loading={discard.isPending}
                  onClick={() => discard.mutate(run.id, { onSuccess: () => notify.success('Run discarded') })}>
            Discard
          </Button>
          {run.kind !== 'baseline' && (
            <Button size="sm" loading={commit.isPending}
                    onClick={() => commit.mutate({ runId: run.id, strategy }, {
                      onSuccess: (s) => notify.success(`Committed — ${s.created} created, ${s.updated} updated`),
                      onError: (e) => notify.error(apiErrorMessage(e, 'Commit failed')),
                    })}>
              Commit
            </Button>
          )}
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

      {collisionCount > 0 && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-800">
            {collisionCount} manual edit(s) sit on numbers this commit would change:
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

// ---- planning grid panel -------------------------------------------------------
function GridPanel({ plan, kpiId, setKpiId, isAdmin }: {
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
  const adjust = useAdjustMine();
  const modify = useModifyAllocation();
  const [editRow, setEditRow] = useState<GridRow | null>(null);
  const [explainRow, setExplainRow] = useState<GridRow | null>(null);
  const [ownerFor, setOwnerFor] = useState<GridOwner | null>(null);

  // Grid controls: which period slice, and where in the tree to browse from.
  const { data: periodTree } = usePeriodTree(plan.period);
  const periodOptions = useMemo(() => flattenPeriods(periodTree), [periodTree]);
  const [periodId, setPeriodId] = useState<number | undefined>(undefined);
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
  const submitting = adjust.isPending || modify.isPending;

  function submitEdit(value: string, reason: string, rebalance: boolean) {
    const done = {
      onSuccess: () => { notify.success('Target updated'); setEditRow(null); },
      onError: (e: unknown) => notify.error(apiErrorMessage(e, 'Could not update the target')),
    };
    if (!isAdmin && plan.status === 'in_review' && myOpenTask) {
      // Task holders go through the review path so their task flips to adjusted/escalated.
      adjust.mutate({ plan_id: plan.id, allocation_id: editRow!.allocation_id!,
                      override_value: value, reason, rebalance }, done);
    } else {
      modify.mutate({ id: editRow!.allocation_id!, body: { override_value: value, reason, rebalance } }, done);
    }
  }

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
        <div className="w-56">
          <Select label="Period slice" value={String(periodId ?? plan.period)}
                  onChange={(e) => setPeriodId(Number(e.target.value) === plan.period ? undefined : Number(e.target.value))}
                  options={periodOptions.length ? periodOptions : [{ value: String(plan.period), label: plan.period_code }]} />
        </div>
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
        <PlanGrid planId={plan.id} kpiId={kpiId} periodId={periodId}
                  rootParentId={jumpTo?.id} unit={kpiDef?.unit} decimalPlaces={kpiDef?.decimal_places}
                  showReview={showReview} canEdit={canEdit}
                  onEdit={setEditRow} onExplain={setExplainRow} onOwner={setOwnerFor} />
      </div>
      <AdjustTargetModal key={editRow?.allocation_id ?? 'closed'} open={editRow !== null}
                         row={editRow} submitting={submitting}
                         onClose={() => setEditRow(null)} onSubmit={submitEdit} />
      <ExplainModal planId={plan.id} row={explainRow} onClose={() => setExplainRow(null)} />
      <PersonTargetDrawer owner={ownerFor} periodId={periodId ?? plan.period} kpiId={kpiId}
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

// ---- review & gap panel ----------------------------------------------------------
function ReviewPanel({ plan, isAdmin }: { plan: TargetPlan; isAdmin: boolean }) {
  const { data: board, isLoading } = useGapBoard(plan.id);
  const tasks = useReviewTasks({ plan: plan.id });
  const accept = useAcceptTask();

  if (isLoading) return <div className="p-4"><TableSkeleton /></div>;
  if (!board || board.tasks_total === 0) {
    return (
      <div className="p-4">
        <EmptyState icon={Megaphone} title="No review cascade"
                    description="Send the plan for review to open one task per territory owner." />
      </div>
    );
  }

  const taskColumns: SimpleColumn<ReviewTask>[] = [
    { header: 'Territory', render: (t) => <span className="font-medium text-gray-900">{t.node_name}</span> },
    { header: 'Level', render: (t) => <Badge variant="default">{t.node_level}</Badge> },
    { header: 'Owner', render: (t) => t.owner_name ?? <span className="text-gray-400">unowned</span> },
    { header: 'Status', align: 'center', render: (t) => <StatusBadge status={t.status} /> },
    {
      header: '', align: 'right',
      render: (t) => (t.status === 'pending' && !isAdmin ? (
        <Button variant="ghost" size="sm" loading={accept.isPending}
                onClick={() => accept.mutate({ taskId: t.id }, {
                  onSuccess: () => notify.success('Accepted — thank you'),
                })}>
          Accept
        </Button>
      ) : null),
    },
  ];

  return (
    <div className="space-y-5 p-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Tasks" value={`${board.tasks_total - board.tasks_open}/${board.tasks_total} answered`} />
        {board.kpis.map((k) => (
          <Stat key={k.kpi} label={`${k.kpi} gap (bottom-up vs top-down)`}
                value={`₹${inr(k.gap)}`} accent={Number(k.gap) !== 0} />
        ))}
      </div>

      <GapMovers board={board} />

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          {isAdmin ? 'All review tasks' : 'My review tasks'}
        </h3>
        <SimpleTable columns={taskColumns} rows={tasks.data?.results ?? []} rowKey={(t) => t.id} />
        {!isAdmin && (
          <p className="mt-2 text-xs text-gray-400">
            To adjust a number instead, open the planning grid and edit within your territory —
            changes inside the cap apply immediately; bigger ones go to your manager.
          </p>
        )}
      </div>
    </div>
  );
}

function GapMovers({ board }: { board: GapBoard }) {
  if (board.top_movers.length === 0) return null;
  const columns: SimpleColumn<GapBoard['top_movers'][number]>[] = [
    { header: 'Territory', render: (m) => m.geography_node },
    { header: 'KPI', render: (m) => m.kpi },
    { header: 'Top-down', align: 'right', render: (m) => `₹${inr(m.top_down)}` },
    { header: 'Current', align: 'right', render: (m) => `₹${inr(m.current)}` },
    {
      header: 'Delta', align: 'right',
      render: (m) => <span className={Number(m.delta) > 0 ? 'text-green-600' : 'text-red-600'}>₹{inr(m.delta)}</span>,
    },
  ];
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Biggest movers</h3>
      <SimpleTable columns={columns} rows={board.top_movers} rowKey={(m) => `${m.geography_node}-${m.kpi}`} />
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
