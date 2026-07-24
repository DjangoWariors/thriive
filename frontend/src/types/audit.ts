// Mirrors apps/audit/serializers.py (AuditLogSerializer, ComputationLogSerializer).

export interface AuditLogEntry {
    id: number;
    action: string;
    entity_type: string;
    entity_id: number | null;
    user_id: number | null;
    user_label: string | null;
    changes: Record<string, unknown> | null;
    prev_hash: string | null;
    row_hash: string | null;
    timestamp: string;
}

export interface ComputationLogEntry {
    id: number;
    computation_type: string;
    entity_id: number | null;
    entity_label: string | null;
    period_id: number | null;
    period_label: string | null;
    triggered_by_id: number | null;
    config_snapshot: Record<string, unknown> | null;
    result_snapshot: Record<string, unknown> | null;
    timestamp: string;
}

export interface AccessLogEntry {
    id: number;
    user_id: number | null;
    user_label: string | null;
    resource: string;
    object_id: number | null;
    subject_entity_id: number | null;
    action: string;
    request_id: string;
    ip_address: string | null;
    timestamp: string;
}

export interface ChainVerifyResult {
    ok: boolean;
    broken_at: number | null;
    reason: string | null;
    checked: number;
}

export interface AuditLogParams {
    page?: number;
    action?: string;
    entity_type?: string;
    user?: number;
    q?: string;
    date_from?: string;
    date_to?: string;
}

export interface ComputationLogParams {
    page?: number;
    computation_type?: string;
    period?: number;
    entity?: number;
}

export interface AccessLogParams {
    page?: number;
    resource?: string;
    subject_entity?: number;
    user?: number;
    date_from?: string;
    date_to?: string;
}
