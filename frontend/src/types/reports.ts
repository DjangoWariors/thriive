// Mirrors apps/reports/serializers.py and models.py.

export type ReportParamType =
    'string' | 'integer' | 'decimal' | 'date' | 'boolean' | 'choice' | 'email' | 'phone';

export interface ReportParamField {
    key: string;
    label: string;
    type: ReportParamType;
    required: boolean;
    options?: string[];
}

export type ReportCategory =
    'sales' | 'coverage' | 'targets' | 'incentive' | 'compliance' | 'master';

export type ReportFormat = 'xlsx' | 'pdf' | 'csv';

export type ReportStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface ReportDefinition {
    id: number;
    name: string;
    code: string;
    category: ReportCategory;
    description: string;
    param_schema: ReportParamField[];
    default_formats: ReportFormat[];
    required_permission: string;
    is_confidential: boolean;
}

export interface ReportExecution {
    id: number;
    definition: number;
    definition_code: string;
    definition_name: string;
    requested_by: number | null;
    requested_by_label: string | null;
    parameters: Record<string, unknown>;
    status: ReportStatus;
    is_terminal: boolean;
    format: ReportFormat;
    row_count: number;
    file_size: number;
    error: string;
    computation_refs: unknown[];
    expires_at: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
}

export interface GenerateReportPayload {
    code: string;
    parameters: Record<string, unknown>;
    format: ReportFormat;
}

export interface ReportExecutionParams {
    page?: number;
    status?: ReportStatus;
    code?: string;
}

export type ScheduleDelivery = 'in_app' | 'email' | 'both' | 'target';

/** Recurring report run, synced to a celery-beat crontab. */
export interface ReportSchedule {
    id: number;
    name: string;
    definition_code: string;
    definition_name: string;
    parameters: Record<string, unknown>;
    format: ReportFormat;
    cron_minute: string;
    cron_hour: string;
    cron_day_of_week: string;
    cron_day_of_month: string;
    cron_month_of_year: string;
    recipients: {users?: number[]; roles?: string[]; entities?: number[]};
    delivery: ScheduleDelivery;
    delivery_target: number | null;
    delivery_target_code: string | null;
    is_enabled: boolean;
    last_run_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface ReportSchedulePayload {
    name: string;
    definition_code: string;
    parameters: Record<string, unknown>;
    format: ReportFormat;
    cron_minute: string;
    cron_hour: string;
    cron_day_of_week: string;
    cron_day_of_month: string;
    cron_month_of_year: string;
    recipients: {users?: number[]; roles?: string[]; entities?: number[]};
    delivery: ScheduleDelivery;
    delivery_target?: number | null;
}

export type DeliveryTargetKind = 's3' | 'sftp';

/** Outbound destination for scheduled extracts (data lake / client SFTP). */
export interface DeliveryTarget {
    id: number;
    code: string;
    name: string;
    kind: DeliveryTargetKind;
    /** Non-secret connection details; the secret lives in the env var named below. */
    config: Record<string, unknown>;
    credential_env: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export interface DeliveryTargetPayload {
    code: string;
    name: string;
    kind: DeliveryTargetKind;
    config: Record<string, unknown>;
    credential_env?: string;
}
