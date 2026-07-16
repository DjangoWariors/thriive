import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { kpiService } from '../services/kpiService';
import type {
  ExternalMetricPayload,
  IntegrationBatchListParams,
  KPIConfigPayload,
  KpiListParams,
  MetricValueListParams,
  TransactionListParams,
} from '../types/kpi';

const kpiKeys = {
  definitions: (params?: KpiListParams) => ['kpi', 'definitions', params ?? {}] as const,
  definition: (id: number) => ['kpi', 'definition', id] as const,
  blueprint: () => ['kpi', 'blueprint'] as const,
  templates: () => ['kpi', 'templates'] as const,
  versions: (id: number) => ['kpi', 'versions', id] as const,
  transactions: (params?: TransactionListParams) => ['kpi', 'transactions', params ?? {}] as const,
};

export function useKpiDefinitions(params?: KpiListParams) {
  return useQuery({
    queryKey: kpiKeys.definitions(params),
    queryFn: () => kpiService.list(params),
  });
}

export function useKpi(id: number | null) {
  return useQuery({
    queryKey: kpiKeys.definition(id ?? 0),
    queryFn: () => kpiService.get(id as number),
    enabled: id !== null && id > 0,
  });
}

export function useKpiBlueprint() {
  return useQuery({ queryKey: kpiKeys.blueprint(), queryFn: () => kpiService.blueprint() });
}

export function useKpiTemplates() {
  return useQuery({ queryKey: kpiKeys.templates(), queryFn: () => kpiService.templates() });
}

export function useKpiVersions(id: number | null) {
  return useQuery({
    queryKey: kpiKeys.versions(id ?? 0),
    queryFn: () => kpiService.versions(id as number),
    enabled: id !== null && id > 0,
  });
}

export function useCreateKpi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: KPIConfigPayload) => kpiService.create(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi', 'definitions'] }),
  });
}

export function useUpdateKpi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: KPIConfigPayload }) =>
      kpiService.update(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi'] }),
  });
}

export function useDeactivateKpi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => kpiService.deactivate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi', 'definitions'] }),
  });
}

export function useKpiTransactions(params?: TransactionListParams) {
  return useQuery({
    queryKey: kpiKeys.transactions(params),
    queryFn: () => kpiService.listTransactions(params),
  });
}

// ── external metrics (SFA / agency feeds) ─────────────────────────────────
export function useExternalMetrics(params?: { search?: string; page?: number }) {
  return useQuery({
    queryKey: ['kpi', 'external-metrics', params ?? {}] as const,
    queryFn: () => kpiService.listExternalMetrics(params),
  });
}

export function useCreateExternalMetric() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExternalMetricPayload) => kpiService.createExternalMetric(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi', 'external-metrics'] }),
  });
}

export function useUpdateExternalMetric() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<ExternalMetricPayload> }) =>
      kpiService.updateExternalMetric(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi', 'external-metrics'] }),
  });
}

export function useDeactivateExternalMetric() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => kpiService.deactivateExternalMetric(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kpi', 'external-metrics'] }),
  });
}

export function useMetricValues(params?: MetricValueListParams) {
  return useQuery({
    queryKey: ['kpi', 'metric-values', params ?? {}] as const,
    queryFn: () => kpiService.listMetricValues(params),
  });
}

export function useIntegrationBatches(params?: IntegrationBatchListParams) {
  return useQuery({
    queryKey: ['kpi', 'integration-batches', params ?? {}] as const,
    queryFn: () => kpiService.listIntegrationBatches(params),
  });
}
