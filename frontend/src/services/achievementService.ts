import api from './api';
import type { PaginatedResponse } from '../types/api';
import type { BulkJob } from '../types/jobs';
import type {
  AchievementListItem,
  AchievementListParams,
  Alert,
  AlertRule,
  DashboardData,
  DrilldownResponse,
  TerritoryGrid,
  TerritoryGridParams,
} from '../types/achievement';

const BASE = '/api/v1/achievements';

export const achievementService = {
  async list(params?: AchievementListParams): Promise<PaginatedResponse<AchievementListItem>> {
    const { data } = await api.get<PaginatedResponse<AchievementListItem>>(`${BASE}/`, { params });
    return data;
  },

  async dashboard(period: number, entity?: number): Promise<DashboardData> {
    const { data } = await api.get<DashboardData>(`${BASE}/dashboard/`, {
      params: { period, ...(entity ? { entity } : {}) },
    });
    return data;
  },

  async drilldown(id: number, page = 1): Promise<DrilldownResponse> {
    const { data } = await api.get<DrilldownResponse>(`${BASE}/${id}/drilldown/`, { params: { page } });
    return data;
  },

  async territory(params: TerritoryGridParams): Promise<TerritoryGrid> {
    const { data } = await api.get<TerritoryGrid>(`${BASE}/territory/`, { params });
    return data;
  },

  async compute(periodId: number): Promise<BulkJob> {
    const { data } = await api.post<BulkJob>(`${BASE}/compute/`, { period_id: periodId });
    return data;
  },

  // alerts
  async listAlerts(params?: { period?: number; status?: string }): Promise<PaginatedResponse<Alert>> {
    const { data } = await api.get<PaginatedResponse<Alert>>(`${BASE}/alerts/`, { params });
    return data;
  },

  async acknowledgeAlert(id: number): Promise<Alert> {
    const { data } = await api.patch<Alert>(`${BASE}/alerts/${id}/acknowledge/`);
    return data;
  },

  // alert rules (config)
  async listAlertRules(): Promise<PaginatedResponse<AlertRule>> {
    const { data } = await api.get<PaginatedResponse<AlertRule>>(`${BASE}/alert-rules/`);
    return data;
  },

  async createAlertRule(payload: Partial<AlertRule>): Promise<AlertRule> {
    const { data } = await api.post<AlertRule>(`${BASE}/alert-rules/`, payload);
    return data;
  },

  async updateAlertRule(id: number, payload: Partial<AlertRule>): Promise<AlertRule> {
    const { data } = await api.put<AlertRule>(`${BASE}/alert-rules/${id}/`, payload);
    return data;
  },
};
