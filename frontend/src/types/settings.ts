export type SettingCategory =
  | 'financial'
  | 'tds'
  | 'locale'
  | 'branding'
  | 'security'
  | 'feature';

export interface SystemSetting {
  id: number;
  key: string;
  category: SettingCategory;
  /** Masked to '••••••' for non-superusers when is_sensitive. */
  value: unknown;
  value_type: 'number' | 'string' | 'bool' | 'json';
  description: string;
  is_sensitive: boolean;
}

export type FeatureFlagScope = 'global' | 'role' | 'entity_type';

export interface FeatureFlag {
  id: number;
  code: string;
  description: string;
  is_enabled: boolean;
  scope: FeatureFlagScope;
  scope_value: string;
}

export interface FeatureFlagPayload {
  code: string;
  description?: string;
  is_enabled: boolean;
  scope: FeatureFlagScope;
  scope_value?: string;
}

/** prefs[category][channel] = opted-in?  Missing keys default to true. */
export type NotificationPrefs = Record<string, Partial<Record<string, boolean>>>;

export interface NotificationPreference {
  prefs: NotificationPrefs;
  available_categories: string[];
  channels: string[];
}
