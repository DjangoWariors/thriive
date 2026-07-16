import api from './api';
import type { PaginatedResponse } from '../types/api';
import type {
  AllocationRecipe,
  CostPreview,
  GapBoard,
  GenerateYearPayload,
  GridResponse,
  PersonView,
  PeriodPayload,
  PlanCreatePayload,
  PlanExplain,
  PlanRun,
  PreflightResult,
  RecipePayload,
  ReviewTask,
  RevisionPolicy,
  RevisionPolicyPayload,
  RunPreview,
  TargetAllocation,
  TargetPeriod,
  TargetRevisionEntry,
  TargetPeriodNode,
  TargetPlan,
} from '../types/target';

const BASE = '/api/v1/targets';

export const targetService = {
  //periods
  async listPeriods(params?: { fiscal_year?: string; roots_only?: boolean; page_size?: number }): Promise<PaginatedResponse<TargetPeriod>> {
    const { data } = await api.get<PaginatedResponse<TargetPeriod>>(`${BASE}/periods/`, { params });
    return data;
  },
  async createPeriod(payload: PeriodPayload): Promise<TargetPeriod> {
    const { data } = await api.post<TargetPeriod>(`${BASE}/periods/`, payload);
    return data;
  },
  async generateYear(payload: GenerateYearPayload): Promise<TargetPeriodNode> {
    const { data } = await api.post<TargetPeriodNode>(`${BASE}/periods/generate-year/`, payload);
    return data;
  },
  async periodTree(id: number): Promise<TargetPeriodNode> {
    const { data } = await api.get<TargetPeriodNode>(`${BASE}/periods/${id}/tree/`);
    return data;
  },
  //plans
  async listPlans(params?: { status?: string; period?: number; page?: number }): Promise<PaginatedResponse<TargetPlan>> {
    const { data } = await api.get<PaginatedResponse<TargetPlan>>(`${BASE}/plans/`, { params });
    return data;
  },
  async getPlan(id: number): Promise<TargetPlan> {
    const { data } = await api.get<TargetPlan>(`${BASE}/plans/${id}/`);
    return data;
  },
  async createPlan(payload: PlanCreatePayload): Promise<TargetPlan> {
    const { data } = await api.post<TargetPlan>(`${BASE}/plans/`, payload);
    return data;
  },
  async transitionPlan(id: number, status: string, forceOverBudget = false): Promise<TargetPlan> {
    const { data } = await api.post<TargetPlan>(`${BASE}/plans/${id}/transition/`,
      { status, force_over_budget: forceOverBudget });
    return data;
  },
  async setPlanTop(id: number, kpiId: number, value: string): Promise<TargetPlan> {
    const { data } = await api.post<TargetPlan>(`${BASE}/plans/${id}/set-top/`, { kpi_id: kpiId, value });
    return data;
  },
  async startRun(planId: number, kind: string): Promise<PlanRun> {
    const { data } = await api.post<PlanRun>(`${BASE}/plans/${planId}/runs/`, { kind });
    return data;
  },
  async realign(planId: number, scopeNodeId: number): Promise<PlanRun> {
    const { data } = await api.post<PlanRun>(`${BASE}/plans/${planId}/realign/`, { scope_node_id: scopeNodeId });
    return data;
  },
  async grid(planId: number, params: {
    kpi: number; parent?: number; period?: number; page?: number; page_size?: number;
  }): Promise<GridResponse> {
    const { data } = await api.get<GridResponse>(`${BASE}/plans/${planId}/grid/`, { params });
    return data;
  },
  async gapBoard(planId: number): Promise<GapBoard> {
    const { data } = await api.get<GapBoard>(`${BASE}/plans/${planId}/gap-board/`);
    return data;
  },
  async costPreview(planId: number): Promise<CostPreview> {
    const { data } = await api.get<CostPreview>(`${BASE}/plans/${planId}/cost-preview/`);
    return data;
  },
  async forceClose(planId: number, reason: string): Promise<{ force_closed: number }> {
    const { data } = await api.post(`${BASE}/plans/${planId}/force-close/`, { reason });
    return data;
  },
  async nudge(planId: number): Promise<{ nudged: number }> {
    const { data } = await api.post(`${BASE}/plans/${planId}/nudge/`);
    return data;
  },

  //runs
  async listRuns(params?: { plan?: number; kind?: string; status?: string }): Promise<PaginatedResponse<PlanRun>> {
    const { data } = await api.get<PaginatedResponse<PlanRun>>(`${BASE}/runs/`, { params });
    return data;
  },
  async runPreview(id: number): Promise<RunPreview> {
    const { data } = await api.get<RunPreview>(`${BASE}/runs/${id}/preview/`);
    return data;
  },
  async commitRun(id: number, overrideStrategy: 'keep' | 'drop' = 'keep'): Promise<Record<string, number>> {
    const { data } = await api.post(`${BASE}/runs/${id}/commit/`, { override_strategy: overrideStrategy });
    return data;
  },
  async discardRun(id: number): Promise<PlanRun> {
    const { data } = await api.post<PlanRun>(`${BASE}/runs/${id}/discard/`);
    return data;
  },
  /** Explain without run access — the backend resolves the latest committed run (reviewer-safe). */
  async planExplain(planId: number, nodeId: number): Promise<PlanExplain> {
    const { data } = await api.get<PlanExplain>(`${BASE}/plans/${planId}/explain/`, { params: { node: nodeId } });
    return data;
  },

  //review tasks
  async listReviewTasks(params?: { plan?: number; status?: string }): Promise<PaginatedResponse<ReviewTask>> {
    const { data } = await api.get<PaginatedResponse<ReviewTask>>(`${BASE}/review-tasks/`, { params });
    return data;
  },
  async acceptTask(id: number, notes = ''): Promise<ReviewTask> {
    const { data } = await api.post<ReviewTask>(`${BASE}/review-tasks/${id}/accept/`, { notes });
    return data;
  },
  /** Task-less adjust: the backend matches the edit to the caller's own review task. */
  async adjustMine(body: {
    plan_id: number; allocation_id: number; override_value: string; reason?: string; rebalance?: boolean;
  }): Promise<ReviewTask> {
    const { data } = await api.post<ReviewTask>(`${BASE}/review-tasks/adjust/`, body);
    return data;
  },

  //allocations (kept read/edit paths)
  async modify(allocationId: number, body: { override_value: string; reason?: string; rebalance?: boolean }): Promise<TargetAllocation> {
    const { data } = await api.post<TargetAllocation>(`${BASE}/allocations/${allocationId}/modify/`, body);
    return data;
  },
  /** Revision timeline for one target cell — who changed what, when and why. */
  async revisions(allocationId: number): Promise<TargetRevisionEntry[]> {
    const { data } = await api.get<TargetRevisionEntry[]>(`${BASE}/allocations/${allocationId}/revisions/`);
    return data;
  },
  /** What a proposed change would do (cap band, reason requirement), without applying it. */
  async preflight(allocationId: number, overrideValue: string): Promise<PreflightResult> {
    const { data } = await api.post<PreflightResult>(
      `${BASE}/allocations/${allocationId}/preflight/`, { override_value: overrideValue });
    return data;
  },
  /** A person's target rolled up from the territories they own (User × Retailer × SKU). */
  async personView(params: {
    entity_id: number; period_id: number; kpi_id: number; channel_id?: number | null; sku_group_id?: number | null;
    include_draft?: boolean;
  }): Promise<PersonView> {
    const { data } = await api.get<PersonView>(`${BASE}/allocations/person-view/`, { params });
    return data;
  },

  //recipes (versioned config)
  async listRecipes(params?: { page?: number; page_size?: number }): Promise<PaginatedResponse<AllocationRecipe>> {
    const { data } = await api.get<PaginatedResponse<AllocationRecipe>>(`${BASE}/recipes/`, { params });
    return data;
  },
  async saveRecipe(id: number | null, payload: RecipePayload): Promise<AllocationRecipe> {
    const { data } = id
      ? await api.put<AllocationRecipe>(`${BASE}/recipes/${id}/`, payload)
      : await api.post<AllocationRecipe>(`${BASE}/recipes/`, payload);
    return data;
  },

  //revision policies (change caps)
  async listRevisionPolicies(params?: { page?: number }): Promise<PaginatedResponse<RevisionPolicy>> {
    const { data } = await api.get<PaginatedResponse<RevisionPolicy>>(`${BASE}/revision-policies/`, { params });
    return data;
  },
  async saveRevisionPolicy(id: number | null, payload: RevisionPolicyPayload): Promise<RevisionPolicy> {
    const { data } = id
      ? await api.put<RevisionPolicy>(`${BASE}/revision-policies/${id}/`, payload)
      : await api.post<RevisionPolicy>(`${BASE}/revision-policies/`, payload);
    return data;
  },
};
