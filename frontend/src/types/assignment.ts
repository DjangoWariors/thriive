// Mirrors apps/assignments serializers. The effective-dated bridge between the
// organisation tree (assignee = a person/Entity) and the geography tree (scope = a
// GeographyNode territory). Sales attach to geography; ownership is resolved here.

export type AssignmentRole = 'owner' | 'stand_in' | 'supervisor';

export interface AssigneeRef {
    id: number;
    name: string;
    code: string;
    path: string;
}

export interface ScopeRef {
    id: number;
    name: string;
    code: string;
    level: string;
    path: string;
}

export interface Assignment {
    id: number;
    assignee: AssigneeRef;
    scope: ScopeRef;
    role_in_scope: AssignmentRole;
    effective_from: string;
    effective_to: string | null;
    reason: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export interface AssignmentListParams {
    scope?: number;
    assignee?: number;
    role?: AssignmentRole;
    open?: boolean;
    /** Search by assignee name or territory name/code. */
    q?: string;
    page?: number;
    page_size?: number;
}

export interface CreateAssignmentPayload {
    assignee_id: number;
    scope_id: number;
    role_in_scope?: AssignmentRole;
    effective_from: string;
    reason?: string;
}

export interface TransferAssignmentPayload {
    scope_id: number;
    new_assignee_id: number;
    role_in_scope?: AssignmentRole;
    effective_from: string;
    reason?: string;
}

export interface EndAssignmentPayload {
    effective_to: string;
    reason?: string;
}

export interface OwnerOfResult {
    owner: AssigneeRef | null;
}
