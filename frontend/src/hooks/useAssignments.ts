import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {assignmentService} from '../services/assignmentService';
import type {
    AssignmentListParams,
    CreateAssignmentPayload,
    EndAssignmentPayload,
    TransferAssignmentPayload,
} from '../types/assignment';

const assignmentQueryKeys = {
    all: () => ['assignments'] as const,
    list: (params: AssignmentListParams) => ['assignments', 'list', params] as const,
    ownerOf: (scope: number, on?: string) => ['assignments', 'owner-of', scope, on] as const,
    scopesOwnedBy: (user?: number, on?: string) => ['assignments', 'scopes-owned-by', user, on] as const,
};

export function useAssignments(params: AssignmentListParams = {}) {
    return useQuery({
        queryKey: assignmentQueryKeys.list(params),
        queryFn: () => assignmentService.list(params),
    });
}


function useInvalidateAssignments() {
    const qc = useQueryClient();
    return () => qc.invalidateQueries({queryKey: assignmentQueryKeys.all()});
}

export function useCreateAssignment() {
    const invalidate = useInvalidateAssignments();
    return useMutation({
        mutationFn: (payload: CreateAssignmentPayload) => assignmentService.create(payload),
        onSuccess: invalidate,
    });
}

export function useTransferAssignment() {
    const invalidate = useInvalidateAssignments();
    return useMutation({
        mutationFn: (payload: TransferAssignmentPayload) => assignmentService.transfer(payload),
        onSuccess: invalidate,
    });
}

export function useEndAssignment() {
    const invalidate = useInvalidateAssignments();
    return useMutation({
        mutationFn: ({id, payload}: {id: number; payload: EndAssignmentPayload}) =>
            assignmentService.end(id, payload),
        onSuccess: invalidate,
    });
}
