import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { targetService } from '../services/targetService';
import type {
  GenerateYearPayload,
  PlanCreatePayload,
  RecipePayload,
  RevisionPolicyPayload,
} from '../types/target';

const targetKeys = {
  periods: () => ['targets', 'periods'] as const,
  planYears: () => ['targets', 'periods', 'roots'] as const,
  periodTree: (id: number) => ['targets', 'periods', 'tree', id] as const,
  personView: (p: object) => ['targets', 'person-view', p] as const,
  revisionPolicies: () => ['targets', 'revision-policies'] as const,
  plans: () => ['targets', 'plans'] as const,
  plan: (id: number) => ['targets', 'plans', id] as const,
  grid: (planId: number, p: object) => ['targets', 'grid', planId, p] as const,
  gapBoard: (planId: number) => ['targets', 'gap-board', planId] as const,
  costPreview: (planId: number) => ['targets', 'cost-preview', planId] as const,
  runs: (p: object) => ['targets', 'runs', p] as const,
  runPreview: (id: number) => ['targets', 'runs', 'preview', id] as const,
  explain: (runId: number, nodeId: number) => ['targets', 'explain', runId, nodeId] as const,
  reviewTasks: (p: object) => ['targets', 'review-tasks', p] as const,
  recipes: () => ['targets', 'recipes'] as const,
};

function invalidatePlans(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['targets'] });
}

// ── periods (planning calendar) ────────────────────────────────────────────────
export function useTargetPeriods(params?: { page_size?: number }) {
  return useQuery({ queryKey: [...targetKeys.periods(), params ?? {}],
    queryFn: () => targetService.listPeriods(params) });
}

/** The annual root periods — one per plan year — for the Planning Calendar. */
export function usePlanYears() {
  return useQuery({ queryKey: targetKeys.planYears(), queryFn: () => targetService.listPeriods({ roots_only: true }) });
}

export function usePeriodTree(id: number | null) {
  return useQuery({
    queryKey: targetKeys.periodTree(id ?? 0),
    queryFn: () => targetService.periodTree(id!),
    enabled: id !== null && id > 0,
  });
}

export function useGenerateYear() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: GenerateYearPayload) => targetService.generateYear(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['targets', 'periods'] }),
  });
}

// ── plans ──────────────────────────────────────────────────────────────────────
export function usePlans(params?: { status?: string; page?: number }) {
  return useQuery({ queryKey: [...targetKeys.plans(), params ?? {}],
    queryFn: () => targetService.listPlans(params) });
}

export function usePlan(id: number | null) {
  return useQuery({
    queryKey: targetKeys.plan(id ?? 0),
    queryFn: () => targetService.getPlan(id!),
    enabled: id !== null && id > 0,
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlanCreatePayload) => targetService.createPlan(payload),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useTransitionPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, force }: { id: number; status: string; force?: boolean }) =>
      targetService.transitionPlan(id, status, force ?? false),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useSetPlanTop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, kpiId, value }: { id: number; kpiId: number; value: string }) =>
      targetService.setPlanTop(id, kpiId, value),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, kind }: { planId: number; kind: string }) =>
      targetService.startRun(planId, kind),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useRealign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, scopeNodeId }: { planId: number; scopeNodeId: number }) =>
      targetService.realign(planId, scopeNodeId),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useGrid(planId: number | null, params: {
  kpi: number; parent?: number; period?: number; page?: number; page_size?: number;
} | null) {
  return useQuery({
    queryKey: targetKeys.grid(planId ?? 0, params ?? {}),
    queryFn: () => targetService.grid(planId!, params!),
    enabled: planId !== null && params !== null && params.kpi > 0,
  });
}

export function useGapBoard(planId: number | null) {
  return useQuery({
    queryKey: targetKeys.gapBoard(planId ?? 0),
    queryFn: () => targetService.gapBoard(planId!),
    enabled: planId !== null && planId > 0,
  });
}

export function useCostPreview(planId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: targetKeys.costPreview(planId ?? 0),
    queryFn: () => targetService.costPreview(planId!),
    enabled: enabled && planId !== null && planId > 0,
  });
}

export function useForceClose() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, reason }: { planId: number; reason: string }) =>
      targetService.forceClose(planId, reason),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useNudge() {
  return useMutation({
    mutationFn: (planId: number) => targetService.nudge(planId),
  });
}

// ── runs ───────────────────────────────────────────────────────────────────────
export function useRuns(params: { plan?: number; kind?: string; status?: string } | null) {
  return useQuery({
    queryKey: targetKeys.runs(params ?? {}),
    queryFn: () => targetService.listRuns(params ?? undefined),
    enabled: params !== null,
    // Runs stage asynchronously (Celery): poll while one is in flight so the staged
    // banner and baseline results appear without a manual refresh.
    refetchInterval: (query) => {
      const rows = query.state.data?.results ?? [];
      return rows.some((r) => r.status === 'pending' || r.status === 'running') ? 3000 : false;
    },
  });
}

export function useRunPreview(runId: number | null) {
  return useQuery({
    queryKey: targetKeys.runPreview(runId ?? 0),
    queryFn: () => targetService.runPreview(runId!),
    enabled: runId !== null && runId > 0,
  });
}

export function useCommitRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, strategy }: { runId: number; strategy: 'keep' | 'drop' }) =>
      targetService.commitRun(runId, strategy),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useDiscardRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: number) => targetService.discardRun(runId),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function usePlanExplain(planId: number | null, nodeId: number | null) {
  return useQuery({
    queryKey: targetKeys.explain(planId ?? 0, nodeId ?? 0),
    queryFn: () => targetService.planExplain(planId!, nodeId!),
    enabled: planId !== null && planId > 0 && nodeId !== null && nodeId > 0,
  });
}

// ── review tasks ───────────────────────────────────────────────────────────────
export function useReviewTasks(params: { plan?: number; status?: string } | null) {
  return useQuery({
    queryKey: targetKeys.reviewTasks(params ?? {}),
    queryFn: () => targetService.listReviewTasks(params ?? undefined),
    enabled: params !== null,
  });
}

export function useAcceptTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, notes }: { taskId: number; notes?: string }) =>
      targetService.acceptTask(taskId, notes ?? ''),
    onSuccess: () => invalidatePlans(qc),
  });
}

/** Task-less adjust — the backend routes the edit to the caller's own review task. */
export function useAdjustMine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      plan_id: number; allocation_id: number; override_value: string; reason?: string; rebalance?: boolean;
    }) => targetService.adjustMine(body),
    onSuccess: () => invalidatePlans(qc),
  });
}

export function useModifyAllocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { override_value: string; reason?: string; rebalance?: boolean } }) =>
      targetService.modify(id, body),
    onSuccess: () => invalidatePlans(qc),
  });
}

// ── person view ────────────────────────────────────────────────────────────────
export function usePersonView(
  params: { entity_id: number; period_id: number; kpi_id: number; include_draft?: boolean } | null,
) {
  return useQuery({
    queryKey: targetKeys.personView(params ?? {}),
    queryFn: () => targetService.personView(params!),
    enabled: params !== null && params.entity_id > 0 && params.period_id > 0 && params.kpi_id > 0,
  });
}

/** Revision timeline for one target cell (grid explain modal's Change history). */
export function useAllocationRevisions(allocationId: number | null) {
  return useQuery({
    queryKey: ['targets', 'revisions', allocationId ?? 0] as const,
    queryFn: () => targetService.revisions(allocationId!),
    enabled: allocationId !== null && allocationId > 0,
  });
}

/** Preview an edit's governance outcome (band / reason requirement / blocked). */
export function usePreflight(allocationId: number | null, overrideValue: string) {
  return useQuery({
    queryKey: ['targets', 'preflight', allocationId ?? 0, overrideValue] as const,
    queryFn: () => targetService.preflight(allocationId!, overrideValue),
    enabled: allocationId !== null && allocationId > 0 && overrideValue !== '' && Number(overrideValue) >= 0,
    staleTime: 15_000,
  });
}

// ── recipes ────────────────────────────────────────────────────────────────────
export function useRecipes(params?: { page?: number; page_size?: number }) {
  return useQuery({ queryKey: [...targetKeys.recipes(), params ?? {}],
    queryFn: () => targetService.listRecipes(params) });
}

export function useSaveRecipe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number | null; payload: RecipePayload }) =>
      targetService.saveRecipe(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: targetKeys.recipes() }),
  });
}

// ── revision policies ──────────────────────────────────────────────────────────
export function useRevisionPolicies(params?: { page?: number }) {
  return useQuery({ queryKey: [...targetKeys.revisionPolicies(), params ?? {}],
    queryFn: () => targetService.listRevisionPolicies(params) });
}

export function useSaveRevisionPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number | null; payload: RevisionPolicyPayload }) =>
      targetService.saveRevisionPolicy(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: targetKeys.revisionPolicies() }),
  });
}
