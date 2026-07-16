import api from './api';
import type {PaginatedResponse} from '../types/api';
import type {
    DeliveryTarget,
    DeliveryTargetPayload,
    GenerateReportPayload,
    ReportDefinition,
    ReportExecution,
    ReportExecutionParams,
    ReportSchedule,
    ReportSchedulePayload,
} from '../types/reports';

export const reportService = {

    // The definitions endpoint is unpaginated (pagination_class = None) → plain array.
    async listDefinitions(): Promise<ReportDefinition[]> {
        const {data} = await api.get<ReportDefinition[]>('/api/v1/reports/definitions/');
        return data;
    },

    async generate(payload: GenerateReportPayload): Promise<ReportExecution> {
        const {data} = await api.post<ReportExecution>('/api/v1/reports/generate/', payload);
        return data;
    },

    async listExecutions(params?: ReportExecutionParams): Promise<PaginatedResponse<ReportExecution>> {
        const {data} = await api.get<PaginatedResponse<ReportExecution>>(
            '/api/v1/reports/executions/', {params},
        );
        return data;
    },

    async download(id: number): Promise<Blob> {
        const {data} = await api.get(`/api/v1/reports/executions/${id}/download/`, {
            responseType: 'blob',
        });
        return data as Blob;
    },

    // recurring schedules (celery-beat backed)
    async listSchedules(): Promise<PaginatedResponse<ReportSchedule>> {
        const {data} = await api.get<PaginatedResponse<ReportSchedule>>('/api/v1/reports/schedules/');
        return data;
    },

    async createSchedule(payload: ReportSchedulePayload): Promise<ReportSchedule> {
        const {data} = await api.post<ReportSchedule>('/api/v1/reports/schedules/', payload);
        return data;
    },

    async updateSchedule(id: number, payload: Partial<ReportSchedulePayload>): Promise<ReportSchedule> {
        const {data} = await api.patch<ReportSchedule>(`/api/v1/reports/schedules/${id}/`, payload);
        return data;
    },

    async deleteSchedule(id: number): Promise<void> {
        await api.delete(`/api/v1/reports/schedules/${id}/`);
    },

    async toggleSchedule(id: number): Promise<ReportSchedule> {
        const {data} = await api.post<ReportSchedule>(`/api/v1/reports/schedules/${id}/toggle/`, {});
        return data;
    },

    async runScheduleNow(id: number): Promise<{ recipients: number; delivered: number }> {
        const {data} = await api.post(`/api/v1/reports/schedules/${id}/run-now/`, {});
        return data as { recipients: number; delivered: number };
    },

    //delivery targets (data lake / SFTP)
    async listDeliveryTargets(): Promise<PaginatedResponse<DeliveryTarget>> {
        const {data} = await api.get<PaginatedResponse<DeliveryTarget>>('/api/v1/reports/delivery-targets/');
        return data;
    },

    async createDeliveryTarget(payload: DeliveryTargetPayload): Promise<DeliveryTarget> {
        const {data} = await api.post<DeliveryTarget>('/api/v1/reports/delivery-targets/', payload);
        return data;
    },

    async updateDeliveryTarget(id: number, payload: Partial<DeliveryTargetPayload>): Promise<DeliveryTarget> {
        const {data} = await api.patch<DeliveryTarget>(`/api/v1/reports/delivery-targets/${id}/`, payload);
        return data;
    },

    async deleteDeliveryTarget(id: number): Promise<void> {
        await api.delete(`/api/v1/reports/delivery-targets/${id}/`);
    },

    async testDeliveryTarget(id: number): Promise<{ ok: boolean; written?: string; error?: string }> {
        const {data} = await api.post(`/api/v1/reports/delivery-targets/${id}/test/`, {});
        return data as { ok: boolean; written?: string; error?: string };
    },
};
