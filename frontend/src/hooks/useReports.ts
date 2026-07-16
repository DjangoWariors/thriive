import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {reportService} from '../services/reportService';
import type {PaginatedResponse} from '../types/api';
import type {
    GenerateReportPayload,
    ReportExecution,
    ReportExecutionParams,
} from '../types/reports';

const POLL_INTERVAL_MS = 2000;

export function useReportDefinitions() {
    return useQuery({
        queryKey: ['reports', 'definitions'],
        queryFn: () => reportService.listDefinitions(),
        staleTime: 5 * 60_000, // catalog is seeded, rarely changes
    });
}

export function useReportExecutions(params?: ReportExecutionParams) {
    return useQuery({
        queryKey: ['reports', 'executions', params ?? {}],
        queryFn: () => reportService.listExecutions(params),
        // Keep polling while any execution is still queued/running, then stop.
        refetchInterval: (query) => {
            const data = query.state.data as PaginatedResponse<ReportExecution> | undefined;
            const anyPending = data?.results.some((e) => !e.is_terminal);
            return anyPending ? POLL_INTERVAL_MS : false;
        },
    });
}

export function useGenerateReport() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload: GenerateReportPayload) => reportService.generate(payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['reports', 'executions']}),
    });
}
