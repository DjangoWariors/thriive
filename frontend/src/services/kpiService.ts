import api from './api';
import type { PaginatedResponse } from '../types/api';
import type { BulkJob } from '../types/jobs';
import type {
  ExternalMetric,
  ExternalMetricPayload,
  ExternalMetricValue,
  IntegrationBatch,
  IntegrationBatchListParams,
  KPIConfigPayload,
  KPIDefinition,
  KPIDefinitionListItem,
  KPITransaction,
  KpiListParams,
  KpiPreviewResult,
  KpiTemplate,
  KpiValidateResult,
  MetricValueListParams,
  TransactionListParams,
} from '../types/kpi';

const BASE = '/api/v1/kpis';

export const kpiService = {
  //KPI definitions
  async list(params?: KpiListParams): Promise<PaginatedResponse<KPIDefinitionListItem>> {
    const { data } = await api.get<PaginatedResponse<KPIDefinitionListItem>>(`${BASE}/definitions/`, { params });
    return data;
  },

  async get(id: number): Promise<KPIDefinition> {
    const { data } = await api.get<KPIDefinition>(`${BASE}/definitions/${id}/`);
    return data;
  },

  async create(payload: KPIConfigPayload): Promise<KPIDefinition> {
    const { data } = await api.post<KPIDefinition>(`${BASE}/definitions/`, payload);
    return data;
  },

  /** PUT — the backend retires the current version and creates version+1. */
  async update(id: number, payload: KPIConfigPayload): Promise<KPIDefinition> {
    const { data } = await api.put<KPIDefinition>(`${BASE}/definitions/${id}/`, payload);
    return data;
  },

  async deactivate(id: number): Promise<void> {
    await api.delete(`${BASE}/definitions/${id}/`);
  },

  async blueprint(): Promise<KPIDefinition[]> {
    const { data } = await api.get<KPIDefinition[]>(`${BASE}/definitions/blueprint/`);
    return data;
  },

  /** Configurable builder starting points (seeded per client, editable in admin). */
  async templates(): Promise<KpiTemplate[]> {
    const { data } = await api.get<KpiTemplate[]>(`${BASE}/templates/`);
    return data;
  },

  async versions(id: number): Promise<KPIDefinition[]> {
    const { data } = await api.get<KPIDefinition[]>(`${BASE}/definitions/${id}/versions/`);
    return data;
  },

  async validate(config: KPIConfigPayload): Promise<KpiValidateResult> {
    const { data } = await api.post<KpiValidateResult>(`${BASE}/definitions/validate/`, config);
    return data;
  },

  async preview(body: {
    config: KPIConfigPayload;
    entity_id: number;
    period_start: string;
    period_end: string;
  }): Promise<KpiPreviewResult> {
    const { data } = await api.post<KpiPreviewResult>(`${BASE}/definitions/preview/`, body);
    return data;
  },

  //transactions
  async listTransactions(params?: TransactionListParams): Promise<PaginatedResponse<KPITransaction>> {
    const { data } = await api.get<PaginatedResponse<KPITransaction>>(`${BASE}/transactions/`, { params });
    return data;
  },

  /** Idempotent CSV upsert. Returns a BulkJob to poll via /api/v1/jobs/{id}/. */
  async bulkImportTransactions(csvText: string): Promise<BulkJob> {
    const { data } = await api.post<BulkJob>(`${BASE}/transactions/bulk/`, { data: csvText });
    return data;
  },

  //external metrics (SFA / agency feeds)
  async listExternalMetrics(params?: { search?: string; page?: number }): Promise<PaginatedResponse<ExternalMetric>> {
    const { data } = await api.get<PaginatedResponse<ExternalMetric>>(`${BASE}/external-metrics/`, { params });
    return data;
  },

  async createExternalMetric(payload: ExternalMetricPayload): Promise<ExternalMetric> {
    const { data } = await api.post<ExternalMetric>(`${BASE}/external-metrics/`, payload);
    return data;
  },

  async updateExternalMetric(id: number, payload: Partial<ExternalMetricPayload>): Promise<ExternalMetric> {
    const { data } = await api.patch<ExternalMetric>(`${BASE}/external-metrics/${id}/`, payload);
    return data;
  },

  async deactivateExternalMetric(id: number): Promise<void> {
    await api.delete(`${BASE}/external-metrics/${id}/`);
  },

  async listMetricValues(params?: MetricValueListParams): Promise<PaginatedResponse<ExternalMetricValue>> {
    const { data } = await api.get<PaginatedResponse<ExternalMetricValue>>(`${BASE}/metric-values/`, { params });
    return data;
  },

  /** CSV import (all-or-nothing). Returns a BulkJob to poll via /api/v1/jobs/{id}/. */
  async bulkImportMetricValues(csvText: string): Promise<BulkJob> {
    const { data } = await api.post<BulkJob>(`${BASE}/metric-values/bulk/`, { data: csvText });
    return data;
  },

  // integration monitor
  async listIntegrationBatches(params?: IntegrationBatchListParams): Promise<PaginatedResponse<IntegrationBatch>> {
    const { data } = await api.get<PaginatedResponse<IntegrationBatch>>(`${BASE}/integration-batches/`, { params });
    return data;
  },

  async getIntegrationBatch(id: number): Promise<IntegrationBatch> {
    const { data } = await api.get<IntegrationBatch>(`${BASE}/integration-batches/${id}/`);
    return data;
  },
};
