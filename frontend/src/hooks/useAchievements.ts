import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { achievementService } from '../services/achievementService';
import type { AchievementListParams, AlertRule, TerritoryGridParams } from '../types/achievement';

const achievementKeys = {
  list: (params?: AchievementListParams) => ['achievements', 'list', params ?? {}] as const,
  dashboard: (period: number | null, entity?: number) =>
    ['achievements', 'dashboard', period, entity ?? null] as const,
  drilldown: (id: number, page: number) => ['achievements', 'drilldown', id, page] as const,
  territory: (params: TerritoryGridParams) => ['achievements', 'territory', params] as const,
  alertRules: ['achievements', 'alert-rules'] as const,
};

export function useTerritoryGrid(params: TerritoryGridParams | null) {
  return useQuery({
    queryKey: achievementKeys.territory(params ?? { kpi: 0, period: 0 }),
    queryFn: () => achievementService.territory(params as TerritoryGridParams),
    enabled: params !== null && params.kpi > 0 && params.period > 0,
  });
}

export function useDashboard(period: number | null, entity?: number) {
  return useQuery({
    queryKey: achievementKeys.dashboard(period, entity),
    queryFn: () => achievementService.dashboard(period as number, entity),
    enabled: period !== null && period > 0,
  });
}

export function useAchievements(params?: AchievementListParams) {
  return useQuery({
    queryKey: achievementKeys.list(params),
    queryFn: () => achievementService.list(params),
    enabled: !!params?.period,
  });
}

export function useDrilldown(id: number | null, page = 1) {
  return useQuery({
    queryKey: achievementKeys.drilldown(id ?? 0, page),
    queryFn: () => achievementService.drilldown(id as number, page),
    enabled: id !== null && id > 0,
  });
}

export function useAlertRules() {
  return useQuery({
    queryKey: achievementKeys.alertRules,
    queryFn: () => achievementService.listAlertRules(),
  });
}

export function useSaveAlertRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number | null; payload: Partial<AlertRule> }) =>
      id ? achievementService.updateAlertRule(id, payload) : achievementService.createAlertRule(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: achievementKeys.alertRules }),
  });
}

export function useComputeAchievements() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (periodId: number) => achievementService.compute(periodId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['achievements'] }),
  });
}

export function useAcknowledgeAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => achievementService.acknowledgeAlert(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['achievements'] }),
  });
}
