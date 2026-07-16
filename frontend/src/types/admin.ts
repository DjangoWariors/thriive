import type { BulkJob } from './jobs';


export interface Role {
  id: number;
  name: string;
  code: string;
  description: string;
  permissions: Record<string, string>;
  is_system_role: boolean;
  is_active: boolean;
}

export interface RolePayload {
  name: string;
  code: string;
  description?: string;
  permissions: Record<string, string>;
}


export interface PermissionResource {
  code: string;
  label: string;
  /** The permission levels that are meaningful for this resource. */
  levels: string[];
}

export interface PermissionGroup {
  group: string;
  resources: PermissionResource[];
}

export interface PermissionCatalog {
  groups: PermissionGroup[];
  /** Full level ladder, highest → lowest. */
  levels: string[];
  level_labels: Record<string, string>;
}


export interface AdminUserPayload {
  email?: string | null;
  mobile?: string | null;
  employee_id?: string | null;
  first_name: string;
  last_name?: string;
  designation?: string;
  department?: string;
  is_active?: boolean;
  password?: string;
  role_ids?: number[];
}

export interface UserBulkImportPayload {
  format: 'csv' | 'json';
  data: string;
  dry_run?: boolean;
  run_async?: boolean;
}

export interface UserImportError {
  row: number;
  errors: string[];
}

export interface UserImportResult {
  status: 'success' | 'valid' | 'validation_failed';
  created?: number;
  rows?: number;
  would_create?: number;
  errors?: UserImportError[];
}


export type UserBulkSubmitResult =
  | { async: true; job: BulkJob }
  | { async: false; result: UserImportResult };

export interface BulkRolesPayload {
  user_ids: number[];
  role_codes: string[];
  mode: 'add' | 'replace';
}

export interface BulkRolesResult {
  status: 'success' | 'validation_failed';
  updated?: number;
  errors?: Array<{ id: number; errors: string[] }>;
}

export interface UserListParams {
  search?: string;
  page?: number;
  /** 'active' (default), 'inactive', or 'all'. */
  status?: 'active' | 'inactive' | 'all';
  /** Role code. */
  role?: string;
  /** Linked entity type code. */
  entity_type?: string;

  department?: string;
}

export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  user: number;
  user_display: string;
  expires_at: string | null;
  last_used_at: string | null;
  is_active: boolean;
  created_at: string;
}

/** Create response — `key` is the plaintext, shown exactly once. */
export interface ApiKeyIssued extends ApiKey {
  key: string;
}

export interface ApiKeyPayload {
  name: string;
  user: number;
  expires_at?: string | null;
}
