import axios from 'axios';
import api from './api';
import type {PaginatedResponse} from '../types/api';
import type {User} from '../types/auth';
import type {BulkJob} from '../types/jobs';
import type {
    AdminUserPayload,
    ApiKey,
    ApiKeyIssued,
    ApiKeyPayload,
    BulkRolesPayload,
    BulkRolesResult,
    Role,
    RolePayload,
    UserBulkImportPayload,
    UserBulkSubmitResult,
    UserImportResult,
    UserListParams,
} from '../types/admin';

export const adminService = {

    async listUsers(params?: UserListParams): Promise<PaginatedResponse<User>> {
        const {data} = await api.get<PaginatedResponse<User>>('/api/v1/auth/users/', {params});
        return data;
    },

    async createUser(payload: AdminUserPayload): Promise<User> {
        const {data} = await api.post<User>('/api/v1/auth/users/', payload);
        return data;
    },

    async updateUser(id: number, payload: AdminUserPayload): Promise<User> {
        const {data} = await api.patch<User>(`/api/v1/auth/users/${id}/`, payload);
        return data;
    },

    async deactivateUser(id: number): Promise<void> {
        await api.delete(`/api/v1/auth/users/${id}/`);
    },

    async reactivateUser(id: number): Promise<User> {
        const {data} = await api.post<User>(`/api/v1/auth/users/${id}/reactivate/`, {});
        return data;
    },

    async listDepartments(): Promise<string[]> {
        const {data} = await api.get<string[]>('/api/v1/auth/users/departments/');
        return data;
    },

    async bulkImportUsers(payload: UserBulkImportPayload): Promise<UserBulkSubmitResult> {
        try {
            const resp = await api.post('/api/v1/auth/users/bulk/', payload);
            if (resp.status === 202) {
                return {async: true, job: resp.data as BulkJob};
            }
            return {async: false, result: resp.data as UserImportResult};
        } catch (err) {
            if (
                axios.isAxiosError(err) &&
                err.response?.status === 422 &&
                (err.response.data as UserImportResult | undefined)?.status === 'validation_failed'
            ) {
                return {async: false, result: err.response.data as UserImportResult};
            }
            throw err;
        }
    },

    async exportUsers(params?: UserListParams): Promise<Blob> {
        const {data} = await api.get('/api/v1/auth/users/export/', {
            params,
            responseType: 'blob',
        });
        return data as Blob;
    },

    async bulkAssignRoles(payload: BulkRolesPayload): Promise<BulkRolesResult> {
        try {
            const {data} = await api.post<BulkRolesResult>('/api/v1/auth/users/bulk-roles/', payload);
            return data;
        } catch (err) {
            if (
                axios.isAxiosError(err) &&
                err.response?.status === 422 &&
                (err.response.data as BulkRolesResult | undefined)?.status === 'validation_failed'
            ) {
                return err.response.data as BulkRolesResult;
            }
            throw err;
        }
    },



    async listRoles(): Promise<PaginatedResponse<Role>> {
        const {data} = await api.get<PaginatedResponse<Role>>('/api/v1/auth/roles/');
        return data;
    },

    async createRole(payload: RolePayload): Promise<Role> {
        const {data} = await api.post<Role>('/api/v1/auth/roles/', payload);
        return data;
    },

    async updateRole(id: number, payload: Partial<RolePayload>): Promise<Role> {
        const {data} = await api.patch<Role>(`/api/v1/auth/roles/${id}/`, payload);
        return data;
    },

    async deleteRole(id: number): Promise<void> {
        await api.delete(`/api/v1/auth/roles/${id}/`);
    },

    // API keys (machine integrations)
    async listApiKeys(): Promise<PaginatedResponse<ApiKey>> {
        const {data} = await api.get<PaginatedResponse<ApiKey>>('/api/v1/auth/api-keys/');
        return data;
    },

    /** The response's `key` field is the plaintext secret — shown exactly once. */
    async issueApiKey(payload: ApiKeyPayload): Promise<ApiKeyIssued> {
        const {data} = await api.post<ApiKeyIssued>('/api/v1/auth/api-keys/', payload);
        return data;
    },

    async revokeApiKey(id: number): Promise<void> {
        await api.delete(`/api/v1/auth/api-keys/${id}/`);
    },
};
