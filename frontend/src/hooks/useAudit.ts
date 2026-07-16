import {useMutation, useQuery} from '@tanstack/react-query';
import {auditService} from '../services/auditService';
import type {AccessLogParams, AuditLogParams, ComputationLogParams} from '../types/audit';

export function useAuditLogs(params?: AuditLogParams) {
    return useQuery({
        queryKey: ['audit', 'logs', params ?? {}],
        queryFn: () => auditService.listLogs(params),
    });
}

export function useComputationLogs(params?: ComputationLogParams) {
    return useQuery({
        queryKey: ['audit', 'computation-logs', params ?? {}],
        queryFn: () => auditService.listComputationLogs(params),
    });
}

export function useAccessLogs(params?: AccessLogParams) {
    return useQuery({
        queryKey: ['audit', 'access-logs', params ?? {}],
        queryFn: () => auditService.listAccessLogs(params),
    });
}

export function useVerifyChain() {
    return useMutation({mutationFn: () => auditService.verifyChain()});
}
