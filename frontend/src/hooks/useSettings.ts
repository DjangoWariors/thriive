import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { settingsService } from '../services/settingsService';
import type { FeatureFlagPayload, SettingCategory } from '../types/settings';

const settingsKeys = {
  settings: (category?: SettingCategory) => ['settings', 'system', category ?? 'all'] as const,
  flags: () => ['settings', 'feature-flags'] as const,
};

export function useSystemSettings(category?: SettingCategory) {
  return useQuery({
    queryKey: settingsKeys.settings(category),
    queryFn: () => settingsService.listSettings(category),
  });
}

export function useUpdateSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, value }: { id: number; value: unknown }) =>
      settingsService.updateSetting(id, value),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['settings', 'system'] }),
  });
}

export function useFeatureFlags() {
  return useQuery({
    queryKey: settingsKeys.flags(),
    queryFn: () => settingsService.listFeatureFlags(),
  });
}

export function useCreateFeatureFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: FeatureFlagPayload) => settingsService.createFeatureFlag(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: settingsKeys.flags() }),
  });
}

export function useUpdateFeatureFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<FeatureFlagPayload> }) =>
      settingsService.updateFeatureFlag(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: settingsKeys.flags() }),
  });
}

export function useDeleteFeatureFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => settingsService.deleteFeatureFlag(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: settingsKeys.flags() }),
  });
}
