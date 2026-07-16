import api from './api';
import type { PaginatedResponse } from '../types/api';
import type { BulkJob } from '../types/jobs';
import type {
  CycleReadiness,
  CycleRegister,
  CycleReview,
  ExceptionCategory,
  ExceptionListParams,
  ExceptionPayload,
  IncentiveScheme,
  IncentiveSchemeListItem,
  PayoutCycle,
  PayoutDetail,
  PayoutException,
  PayoutListItem,
  PayoutListParams,
  PayoutRun,
  PayoutStatement,
  PayoutSummary,
  RunListParams,
  SchemePayload,
  SchemeValidateResult,
  SipStructureGroup,
  VariablePay,
  VariablePayBulkResult,
} from '../types/incentive';

const BASE = '/api/v1/incentives';

export const incentiveService = {
  //schemes
  async listSchemes(params?: { entity_type?: string; include_inactive?: boolean }):
    Promise<PaginatedResponse<IncentiveSchemeListItem>> {
    const { data } = await api.get<PaginatedResponse<IncentiveSchemeListItem>>(
      `${BASE}/schemes/`, { params });
    return data;
  },

  async sipStructures(): Promise<SipStructureGroup[]> {
    const { data } = await api.get<SipStructureGroup[]>(`${BASE}/schemes/sip-structures/`);
    return data;
  },

  async getScheme(id: number): Promise<IncentiveScheme> {
    const { data } = await api.get<IncentiveScheme>(`${BASE}/schemes/${id}/`);
    return data;
  },

  async createScheme(payload: SchemePayload): Promise<IncentiveScheme> {
    const { data } = await api.post<IncentiveScheme>(`${BASE}/schemes/`, payload);
    return data;
  },

  /** PUT — the backend retires the current version and creates version+1. */
  async updateScheme(id: number, payload: SchemePayload): Promise<IncentiveScheme> {
    const { data } = await api.put<IncentiveScheme>(`${BASE}/schemes/${id}/`, payload);
    return data;
  },

  async deactivateScheme(id: number): Promise<void> {
    await api.delete(`${BASE}/schemes/${id}/`);
  },

  async schemeVersions(id: number): Promise<IncentiveSchemeListItem[]> {
    const { data } = await api.get<IncentiveSchemeListItem[]>(`${BASE}/schemes/${id}/versions/`);
    return data;
  },

  async validateScheme(payload: SchemePayload): Promise<SchemeValidateResult> {
    const { data } = await api.post<SchemeValidateResult>(`${BASE}/schemes/validate/`, payload);
    return data;
  },

  //ariable pay
  async listVariablePay(params?: { period?: number; entity?: number; page?: number }):
    Promise<PaginatedResponse<VariablePay>> {
    const { data } = await api.get<PaginatedResponse<VariablePay>>(
      `${BASE}/variable-pay/`, { params });
    return data;
  },

  async upsertVariablePay(payload: {
    entity: number; target_period: number; amount: string;
    eligible_working_days?: number | null;
  }): Promise<VariablePay> {
    const { data } = await api.post<VariablePay>(`${BASE}/variable-pay/`, payload);
    return data;
  },

  async bulkImportVariablePay(targetPeriod: number, rows: Array<Record<string, unknown>>):
    Promise<VariablePayBulkResult> {
    const { data } = await api.post<VariablePayBulkResult>(
      `${BASE}/variable-pay/bulk/`, { target_period: targetPeriod, rows });
    return data;
  },

  //payout runs
  async listRuns(params?: RunListParams): Promise<PaginatedResponse<PayoutRun>> {
    const { data } = await api.get<PaginatedResponse<PayoutRun>>(
      `${BASE}/payout-runs/`, { params });
    return data;
  },

  async getRun(id: number): Promise<PayoutRun> {
    const { data } = await api.get<PayoutRun>(`${BASE}/payout-runs/${id}/`);
    return data;
  },

  /** Returns a BulkJob (poll /api/v1/jobs/{id}/) plus the created run_id. */
  async computeRun(schemeId: number, periodId: number): Promise<BulkJob & { run_id: number }> {
    const { data } = await api.post<BulkJob & { run_id: number }>(
      `${BASE}/payout-runs/compute/`, { scheme_id: schemeId, period_id: periodId });
    return data;
  },

  async submitRun(id: number): Promise<PayoutRun> {
    const { data } = await api.post<PayoutRun>(`${BASE}/payout-runs/${id}/submit/`);
    return data;
  },

  async approveRun(id: number): Promise<PayoutRun> {
    const { data } = await api.post<PayoutRun>(`${BASE}/payout-runs/${id}/approve/`);
    return data;
  },

  async rejectRun(id: number, reason: string): Promise<PayoutRun> {
    const { data } = await api.post<PayoutRun>(`${BASE}/payout-runs/${id}/reject/`, { reason });
    return data;
  },

  async markRunPaid(id: number, paymentRef: string): Promise<PayoutRun> {
    const { data } = await api.post<PayoutRun>(
      `${BASE}/payout-runs/${id}/mark-paid/`, { payment_ref: paymentRef });
    return data;
  },

  //payouts
  async listPayouts(params?: PayoutListParams): Promise<PaginatedResponse<PayoutListItem>> {
    const { data } = await api.get<PaginatedResponse<PayoutListItem>>(
      `${BASE}/payouts/`, { params });
    return data;
  },

  async payoutSummary(params?: PayoutListParams): Promise<PayoutSummary> {
    const { data } = await api.get<PayoutSummary>(`${BASE}/payouts/summary/`, { params });
    return data;
  },

  async getPayout(id: number): Promise<PayoutDetail> {
    const { data } = await api.get<PayoutDetail>(`${BASE}/payouts/${id}/`);
    return data;
  },

  async holdPayout(id: number, reason: string): Promise<PayoutDetail> {
    const { data } = await api.post<PayoutDetail>(`${BASE}/payouts/${id}/hold/`, { reason });
    return data;
  },

  async releasePayout(id: number): Promise<PayoutDetail> {
    const { data } = await api.post<PayoutDetail>(`${BASE}/payouts/${id}/release/`);
    return data;
  },

  async payoutStatement(id: number): Promise<PayoutStatement> {
    const { data } = await api.get<PayoutStatement>(`${BASE}/payouts/${id}/statement/`);
    return data;
  },

  //payout cycles (month-close)
  async listCycles(params?: { status?: string; period?: number }):
    Promise<PaginatedResponse<PayoutCycle>> {
    const { data } = await api.get<PaginatedResponse<PayoutCycle>>(`${BASE}/cycles/`, { params });
    return data;
  },

  async getCycle(id: number): Promise<PayoutCycle> {
    const { data } = await api.get<PayoutCycle>(`${BASE}/cycles/${id}/`);
    return data;
  },

  async openCycle(periodId: number): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(`${BASE}/cycles/`, { period_id: periodId });
    return data;
  },

  async cycleReadiness(id: number): Promise<CycleReadiness> {
    const { data } = await api.get<CycleReadiness>(`${BASE}/cycles/${id}/readiness/`);
    return data;
  },

  /** Returns a BulkJob (poll /api/v1/jobs/{id}/) plus cycle_id. */
  async finalizeCycle(id: number, override = false, overrideReason = ''):
    Promise<BulkJob & { cycle_id: number }> {
    const { data } = await api.post<BulkJob & { cycle_id: number }>(
      `${BASE}/cycles/${id}/finalize/`, { override, override_reason: overrideReason });
    return data;
  },

  async computeCycle(id: number): Promise<BulkJob & { cycle_id: number }> {
    const { data } = await api.post<BulkJob & { cycle_id: number }>(
      `${BASE}/cycles/${id}/compute/`);
    return data;
  },

  async cycleReview(id: number): Promise<CycleReview> {
    const { data } = await api.get<CycleReview>(`${BASE}/cycles/${id}/review/`);
    return data;
  },

  async submitCycle(id: number): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(`${BASE}/cycles/${id}/submit/`);
    return data;
  },

  async approveCycle(id: number): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(`${BASE}/cycles/${id}/approve/`);
    return data;
  },

  async rejectCycle(id: number, reason: string): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(`${BASE}/cycles/${id}/reject/`, { reason });
    return data;
  },

  async disburseCycle(id: number, paymentRef: string, registerRef = ''): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(
      `${BASE}/cycles/${id}/disburse/`, { payment_ref: paymentRef, register_ref: registerRef });
    return data;
  },

  async closeCycle(id: number): Promise<PayoutCycle> {
    const { data } = await api.post<PayoutCycle>(`${BASE}/cycles/${id}/close/`);
    return data;
  },

  async cycleRegister(id: number): Promise<CycleRegister> {
    const { data } = await api.get<CycleRegister>(`${BASE}/cycles/${id}/register/`);
    return data;
  },

  /** Fetch the register as a CSV blob (JWT-authenticated) for a browser download. */
  async downloadRegisterCsv(id: number): Promise<Blob> {
    const { data } = await api.get(`${BASE}/cycles/${id}/register/`, {
      params: { fmt: 'csv' }, responseType: 'blob',
    });
    return data as Blob;
  },

  //exceptions
  async listExceptions(params?: ExceptionListParams): Promise<PaginatedResponse<PayoutException>> {
    const { data } = await api.get<PaginatedResponse<PayoutException>>(
      `${BASE}/exceptions/`, { params });
    return data;
  },

  async createException(payload: ExceptionPayload): Promise<PayoutException> {
    const { data } = await api.post<PayoutException>(`${BASE}/exceptions/`, payload);
    return data;
  },

  async withdrawException(id: number): Promise<void> {
    await api.delete(`${BASE}/exceptions/${id}/`);
  },

  async approveException(id: number): Promise<PayoutException> {
    const { data } = await api.post<PayoutException>(`${BASE}/exceptions/${id}/approve/`);
    return data;
  },

  async rejectException(id: number, reason: string): Promise<PayoutException> {
    const { data } = await api.post<PayoutException>(
      `${BASE}/exceptions/${id}/reject/`, { reason });
    return data;
  },

  async listExceptionCategories(): Promise<PaginatedResponse<ExceptionCategory>> {
    const { data } = await api.get<PaginatedResponse<ExceptionCategory>>(
      `${BASE}/exception-categories/`);
    return data;
  },
};
