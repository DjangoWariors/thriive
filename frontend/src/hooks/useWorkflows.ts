import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { workflowService, type PendingParams } from '../services/workflowService';

const workflowKeys = {
  pending: (params?: object) => ['workflows', 'pending', params ?? {}] as const,
  pendingCount: () => ['workflows', 'pending-count'] as const,
  instance: (id: number) => ['workflows', 'instance', id] as const,
  history: (id: number) => ['workflows', 'history', id] as const,
  delegations: () => ['workflows', 'delegations'] as const,
  definitions: () => ['workflows', 'definitions'] as const,
};

function useInvalidate() {
  const qc = useQueryClient();
  return (...prefixes: string[][]) => {
    for (const prefix of prefixes) void qc.invalidateQueries({ queryKey: prefix });
  };
}

const WF_INVALIDATES: string[][] = [
  ['workflows', 'pending'],
  ['workflows', 'pending-count'],
  ['incentives', 'exceptions'],
];

export function usePendingApprovals(params?: PendingParams) {
  return useQuery({
    queryKey: workflowKeys.pending(params),
    queryFn: () => workflowService.listPending(params),
  });
}

export function usePendingCount(enabled = true) {
  return useQuery({
    queryKey: workflowKeys.pendingCount(),
    queryFn: () => workflowService.pendingCount(),
    refetchInterval: 60_000,
    enabled,
  });
}

export function useWorkflowInstance(id: number | null) {
  return useQuery({
    queryKey: workflowKeys.instance(id ?? 0),
    queryFn: () => workflowService.getInstance(id as number),
    enabled: id !== null && id > 0,
  });
}


export function useApproveStep() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, comments }: { id: number; comments?: string }) =>
      workflowService.approve(id, comments ?? ''),
    onSuccess: () => invalidate(...WF_INVALIDATES),
  });
}

export function useRejectStep() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      workflowService.reject(id, reason),
    onSuccess: () => invalidate(...WF_INVALIDATES),
  });
}

export function useBulkApprove() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ ids, comments }: { ids: number[]; comments?: string }) =>
      workflowService.bulkApprove(ids, comments ?? ''),
    onSuccess: () => invalidate(...WF_INVALIDATES),
  });
}

export function useBulkReject() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ ids, reason }: { ids: number[]; reason: string }) =>
      workflowService.bulkReject(ids, reason),
    onSuccess: () => invalidate(...WF_INVALIDATES),
  });
}

export function useWorkflowDefinitions(enabled = true) {
  return useQuery({
    queryKey: workflowKeys.definitions(),
    queryFn: () => workflowService.listDefinitions(),
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function useDelegations(enabled = true) {
  return useQuery({
    queryKey: workflowKeys.delegations(),
    queryFn: () => workflowService.listDelegations(),
    enabled,
  });
}

export function useCreateDelegation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: Parameters<typeof workflowService.createDelegation>[0]) =>
      workflowService.createDelegation(payload),
    onSuccess: () => invalidate([...workflowKeys.delegations()]),
  });
}

export function useEndDelegation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => workflowService.endDelegation(id),
    onSuccess: () => invalidate([...workflowKeys.delegations()]),
  });
}

