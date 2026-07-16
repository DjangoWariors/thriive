import api from './api';
import type {PaginatedResponse} from '../types/api';
import type {
    AccessLogEntry,
    AccessLogParams,
    AuditLogEntry,
    AuditLogParams,
    ChainVerifyResult,
    ComputationLogEntry,
    ComputationLogParams,
} from '../types/audit';

export const auditService = {

    async listLogs(params?: AuditLogParams): Promise<PaginatedResponse<AuditLogEntry>> {
        const {data} = await api.get<PaginatedResponse<AuditLogEntry>>('/api/v1/audit/logs/', {params});
        return data;
    },

    async listComputationLogs(
        params?: ComputationLogParams,
    ): Promise<PaginatedResponse<ComputationLogEntry>> {
        const {data} = await api.get<PaginatedResponse<ComputationLogEntry>>(
            '/api/v1/audit/computation-logs/',
            {params},
        );
        return data;
    },

    async listAccessLogs(params?: AccessLogParams): Promise<PaginatedResponse<AccessLogEntry>> {
        const {data} = await api.get<PaginatedResponse<AccessLogEntry>>(
            '/api/v1/audit/access-logs/',
            {params},
        );
        return data;
    },

    async verifyChain(): Promise<ChainVerifyResult> {
        const {data} = await api.post<ChainVerifyResult>('/api/v1/audit/verify/', {});
        return data;
    },
};
