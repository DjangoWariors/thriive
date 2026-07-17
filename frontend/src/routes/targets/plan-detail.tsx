import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, ClipboardCheck, GitBranchPlus, Package, Rocket, Shuffle, Target,
} from 'lucide-react';
import { usePlan, useRuns } from '../../hooks/useTargets';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import type { PlanRun, RunKind, TargetPlan } from '../../types/target';
import {
  activeStageKey, isLive, planStages, type StageKey,
} from '../../components/targets/plan-stages';
import { TopNumbersStage } from '../../components/targets/TopNumbersStage';
import { SplitStage } from '../../components/targets/SplitStage';
import { ReviewStage } from '../../components/targets/ReviewStage';
import { PublishStage } from '../../components/targets/PublishStage';
import { RealignDialog } from '../../components/targets/RealignDialog';
import { StagedRunReview } from '../../components/targets/StagedRunReview';
import { REALIGN_ENABLED } from '../../config/features';
import { PlanGridPanel } from '../../components/targets/PlanGridPanel';
import { ActualsPanel } from '../../components/targets/ActualsPanel';
import { ReviewerWorkspace } from '../../components/targets/ReviewerWorkspace';
import { Stepper, type WizardStep } from '../../components/ui/WizardChrome';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { PageHeader } from '../../components/ui/PageHeader';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Tabs } from '../../components/ui/Tabs';
import { TableSkeleton } from '../../components/ui/Skeleton';

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
  const onBack = () => navigate('/targets');
  return isAdmin
    ? <AdminWorkspace plan={plan} onBack={onBack} />
    : <ReviewerWorkspace plan={plan} onBack={onBack} />;
}

const STAGE_ICONS: Record<StageKey, WizardStep['icon']> = {
  top: Target, spatial: GitBranchPlus, product: Package, review: ClipboardCheck, publish: Rocket,
};

/** One guided flow: the stepper shows where the plan stands, the active stage's panel
 * carries its actions AND its results, and the grid/actuals canvas sits below throughout. */
function AdminWorkspace({ plan, onBack }: { plan: TargetPlan; onBack: () => void }) {
  const [tab, setTab] = useState<'grid' | 'actuals'>('grid');
  const [kpiId, setKpiId] = useState<number>(plan.kpis[0]?.kpi ?? 0);
  const [selectedStage, setSelectedStage] = useState<StageKey | null>(null);
  const [realignOpen, setRealignOpen] = useState(false);
  const qc = useQueryClient();

  // All recent runs (not just staged): useRuns polls while one is pending/running, so an
  // async Celery run surfaces its result without a manual refresh.
  const runs = useRuns({ plan: plan.id });
  const runRows = useMemo(() => runs.data?.results ?? [], [runs.data]);
  const stagedOf = (kind: RunKind): PlanRun | null =>
    runRows.find((r) => r.status === 'staged' && r.kind === kind) ?? null;
  const runningOf = (kind: RunKind): boolean =>
    runRows.some((r) => r.kind === kind && (r.status === 'pending' || r.status === 'running'));
  const hasActiveRun = runRows.some((r) => r.status === 'pending' || r.status === 'running');
  const wasActive = useRef(false);
  useEffect(() => {
    // A run settling changes plan progress + baseline suggestions — refresh the plan.
    if (wasActive.current && !hasActiveRun) void qc.invalidateQueries({ queryKey: ['targets', 'plans'] });
    wasActive.current = hasActiveRun;
  }, [hasActiveRun, qc]);

  const stages = planStages(plan);
  const active = selectedStage ?? activeStageKey(stages);
  const editable = plan.status === 'draft';
  const live = isLive(plan);
  const canRealign = REALIGN_ENABLED
    && plan.progress.committed_stages.includes('spatial')
    && ['draft', 'in_review', 'published'].includes(plan.status);
  const realignRun = REALIGN_ENABLED ? stagedOf('realign') : null;

  const steps: WizardStep[] = stages.map((s) => ({
    label: s.key === 'review' && plan.progress.review.open
      ? `${s.label} (${plan.progress.review.open})` : s.label,
    icon: STAGE_ICONS[s.key],
  }));
  const currentIdx = stages.findIndex((s) => s.key === active);

  const stagePanel = live && selectedStage === null ? (
    <Card className="border-green-200 bg-green-50/40">
      <p className="text-sm font-medium text-green-800">
        Published — targets are live for {plan.period_code}. Track them on the Actuals tab.
      </p>
    </Card>
  ) : active === 'top' ? (
    <TopNumbersStage plan={plan} stagedBaseline={stagedOf('baseline')}
                     calculating={runningOf('baseline')} editable={editable} />
  ) : active === 'spatial' || active === 'product' ? (
    <SplitStage plan={plan} kind={active} stagedRun={stagedOf(active)} running={runningOf(active)}
                editable={editable} done={stages.find((s) => s.key === active)?.done ?? false} />
  ) : active === 'review' ? (
    <ReviewStage plan={plan} />
  ) : (
    <PublishStage plan={plan} />
  );

  return (
    <div className="p-6">
      <PageHeader
        className="mb-4"
        title={plan.name}
        description={`${plan.period_code} · ${plan.root_geography_name} · ${plan.kpis.length} KPI(s)`}
        actions={<>
          <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={onBack}>All plans</Button>
          {canRealign && (
            <Button variant="outline" icon={<Shuffle className="h-4 w-4" />} onClick={() => setRealignOpen(true)}>
              Realign a subtree
            </Button>
          )}
          <StatusBadge status={plan.status} />
        </>}
      />

      <div className="mb-4">
        <Stepper steps={steps} current={currentIdx} completed={stages.map((s) => s.done)}
                 onStepClick={(i) => setSelectedStage(stages[i]!.key)} />
      </div>

      <div className="space-y-4">
        {stagePanel}
        {realignRun && <StagedRunReview run={realignRun} />}
        <Card padding="none">
          <div className="px-4 pt-2">
            <Tabs activeTab={tab} onChange={(v) => setTab(v as 'grid' | 'actuals')}
                  tabs={[{ value: 'grid', label: 'Planning grid' },
                         { value: 'actuals', label: 'Actuals' }]} />
          </div>
          {tab === 'grid'
            ? <PlanGridPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} isAdmin />
            : <ActualsPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} />}
        </Card>
      </div>

      <RealignDialog plan={plan} open={realignOpen} onClose={() => setRealignOpen(false)} />
    </div>
  );
}
