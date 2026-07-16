export interface UserRole {
  id: number;
  code: string;
  name: string;
  /** RBAC permission matrix for this role. */
  permissions: Record<string, string>;
}

export interface EntityInfo {
  id: number;
  name: string;
  code: string;
  type: string;
  path: string;
}

export interface User {
  id: number;
  email: string | null;
  mobile: string | null;
  employee_id: string | null;
  first_name: string;
  last_name: string;
  designation: string;
  department: string;
  is_superuser: boolean;
  is_active?: boolean;
  last_login?: string | null;
  active_roles: UserRole[];
  entity_info: EntityInfo | null;
  portal_type: 'admin' | 'partner';
  date_joined: string;
  /** False for OTP-only accounts (no usable password to change). */
  has_password?: boolean;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}
