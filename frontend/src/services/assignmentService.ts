import api from './api';
import type {PaginatedResponse} from '../types/api';
import type {
    Assignment,
    AssignmentListParams,
    CreateAssignmentPayload,
    EndAssignmentPayload,
    OwnerOfResult,
    ScopeRef,
    TransferAssignmentPayload,
} from '../types/assignment';

export const assignmentService = {
    async list(params: AssignmentListParams = {}): Promise<PaginatedResponse<Assignment>> {
        const {data} = await api.get<PaginatedResponse<Assignment>>('/api/v1/assignments/', {params});
        return data;
    },

    async create(payload: CreateAssignmentPayload): Promise<Assignment> {
        const {data} = await api.post<Assignment>('/api/v1/assignments/', payload);
        return data;
    },

    async transfer(payload: TransferAssignmentPayload): Promise<Assignment> {
        const {data} = await api.post<Assignment>('/api/v1/assignments/transfer/', payload);
        return data;
    },

    async end(id: number, payload: EndAssignmentPayload): Promise<Assignment> {
        const {data} = await api.post<Assignment>(`/api/v1/assignments/${id}/end/`, payload);
        return data;
    },

    async ownerOf(scope: number, on?: string): Promise<OwnerOfResult> {
        const {data} = await api.get<OwnerOfResult>('/api/v1/assignments/owner-of/', {
            params: {scope, ...(on ? {on} : {})},
        });
        return data;
    },

    async scopesOwnedBy(user?: number, on?: string): Promise<ScopeRef[]> {
        const {data} = await api.get<ScopeRef[]>('/api/v1/assignments/scopes-owned-by/', {
            params: {...(user ? {user} : {}), ...(on ? {on} : {})},
        });
        return data;
    },
};
