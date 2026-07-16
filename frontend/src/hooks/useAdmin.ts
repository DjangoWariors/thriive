import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminService } from '../services/adminService';
import { authService } from '../services/auth';
import type {
  AdminUserPayload,
  ApiKeyPayload,
  BulkRolesPayload,
  RolePayload,
  UserBulkImportPayload,
  UserListParams,
} from '../types/admin';


export const adminKeys = {
  users: (params?: UserListParams) => ['admin', 'users', params ?? {}] as const,
  roles: () => ['admin', 'roles'] as const,
  departments: () => ['admin', 'departments'] as const,
  permissionCatalog: () => ['admin', 'permission-catalog'] as const,
};


export function usePermissionCatalog() {
  return useQuery({
    queryKey: adminKeys.permissionCatalog(),
    queryFn: () => authService.permissionCatalog(),
    staleTime: Infinity, // static reference config for the session
  });
}


export function useUsers(params?: UserListParams) {
  return useQuery({
    queryKey: adminKeys.users(params),
    queryFn: () => adminService.listUsers(params),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AdminUserPayload) => adminService.createUser(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: AdminUserPayload }) =>
      adminService.updateUser(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminService.deactivateUser(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useReactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminService.reactivateUser(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useDepartments() {
  return useQuery({
    queryKey: adminKeys.departments(),
    queryFn: () => adminService.listDepartments(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useBulkImportUsers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserBulkImportPayload) => adminService.bulkImportUsers(payload),
    onSuccess: (res) => {
      if (!res.async && res.result.status === 'success') {
        void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
        void qc.invalidateQueries({ queryKey: adminKeys.departments() });
      }
    },
  });
}

export function useBulkAssignRoles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: BulkRolesPayload) => adminService.bulkAssignRoles(payload),
    onSuccess: (res) => {
      if (res.status === 'success') {
        void qc.invalidateQueries({ queryKey: ['admin', 'users'] });
      }
    },
  });
}


export function useRoles() {
  return useQuery({
    queryKey: adminKeys.roles(),
    queryFn: () => adminService.listRoles(),
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RolePayload) => adminService.createRole(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: adminKeys.roles() }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<RolePayload> }) =>
      adminService.updateRole(id, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: adminKeys.roles() }),
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminService.deleteRole(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: adminKeys.roles() }),
  });
}

// ── API keys (machine integrations) ─────────────────────────────────────────
export function useApiKeys() {
  return useQuery({
    queryKey: ['admin', 'api-keys'] as const,
    queryFn: () => adminService.listApiKeys(),
  });
}

export function useIssueApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApiKeyPayload) => adminService.issueApiKey(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'api-keys'] }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminService.revokeApiKey(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'api-keys'] }),
  });
}
