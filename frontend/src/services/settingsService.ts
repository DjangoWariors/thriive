import api from './api';
import type {
  FeatureFlag,
  FeatureFlagPayload,
  SettingCategory,
  SystemSetting,
} from '../types/settings';

const BASE = '/api/v1/admin';

export const settingsService = {
  async listSettings(category?: SettingCategory): Promise<SystemSetting[]> {
    const { data } = await api.get<SystemSetting[]>(`${BASE}/settings/`, {
      params: category ? { category } : undefined,
    });
    return data;
  },

  async updateSetting(id: number, value: unknown): Promise<SystemSetting> {
    const { data } = await api.post<SystemSetting>(`${BASE}/settings/${id}/update_value/`, {
      value,
    });
    return data;
  },

  async listFeatureFlags(): Promise<FeatureFlag[]> {
    const { data } = await api.get<FeatureFlag[]>(`${BASE}/feature-flags/`);
    return data;
  },

  async createFeatureFlag(payload: FeatureFlagPayload): Promise<FeatureFlag> {
    const { data } = await api.post<FeatureFlag>(`${BASE}/feature-flags/`, payload);
    return data;
  },

  async updateFeatureFlag(id: number, payload: Partial<FeatureFlagPayload>): Promise<FeatureFlag> {
    const { data } = await api.patch<FeatureFlag>(`${BASE}/feature-flags/${id}/`, payload);
    return data;
  },

  async deleteFeatureFlag(id: number): Promise<void> {
    await api.delete(`${BASE}/feature-flags/${id}/`);
  },
};
