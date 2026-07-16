import api from './api';
import type { PaginatedResponse } from '../types/api';
import type {
  ApprovalDelegation,
  BulkActionResult,
  PendingApproval,
  WorkflowAction,
  WorkflowDefinitionSummary,
  WorkflowInstance,
} from '../types/workflow';

const BASE = '/api/v1/workflows';

export interface PendingParams {
  page?: number;
}

export const workflowService = {
  async listPending(params?: PendingParams): Promise<PaginatedResponse<PendingApproval>> {
    const { data } = await api.get<PaginatedResponse<PendingApproval>>(`${BASE}/pending/`, { params });
    return data;
  },

  async pendingCount(): Promise<number> {
    const { data } = await api.get<{ count: number }>(`${BASE}/pending/count/`);
    return data.count;
  },

  async getInstance(id: number): Promise<WorkflowInstance> {
    const { data } = await api.get<WorkflowInstance>(`${BASE}/${id}/`);
    return data;
  },

  async getHistory(id: number): Promise<WorkflowAction[]> {
    const { data } = await api.get<WorkflowAction[]>(`${BASE}/${id}/history/`);
    return data;
  },

  async approve(id: number, comments = ''): Promise<WorkflowInstance> {
    const { data } = await api.post<WorkflowInstance>(`${BASE}/${id}/approve/`, { comments });
    return data;
  },

  async reject(id: number, reason: string): Promise<WorkflowInstance> {
    const { data } = await api.post<WorkflowInstance>(`${BASE}/${id}/reject/`, { reason });
    return data;
  },

  async bulkApprove(ids: number[], comments = ''): Promise<BulkActionResult> {
    const { data } = await api.post<BulkActionResult>(`${BASE}/bulk-approve/`, { ids, comments });
    return data;
  },

  async bulkReject(ids: number[], reason: string): Promise<BulkActionResult> {
    const { data } = await api.post<BulkActionResult>(`${BASE}/bulk-reject/`, { ids, reason });
    return data;
  },

  async listDefinitions(): Promise<PaginatedResponse<WorkflowDefinitionSummary>> {
    const { data } = await api.get<PaginatedResponse<WorkflowDefinitionSummary>>(`${BASE}/definitions/`);
    return data;
  },

  async listDelegations(): Promise<PaginatedResponse<ApprovalDelegation>> {
    const { data } = await api.get<PaginatedResponse<ApprovalDelegation>>(`${BASE}/delegations/`);
    return data;
  },

  async createDelegation(payload: {
    delegate: number;
    scope: string;
    start_date: string;
    end_date: string;
    reason?: string;
  }): Promise<ApprovalDelegation> {
    const { data } = await api.post<ApprovalDelegation>(`${BASE}/delegations/`, payload);
    return data;
  },

  async endDelegation(id: number): Promise<void> {
    await api.delete(`${BASE}/delegations/${id}/`);
  },
};
