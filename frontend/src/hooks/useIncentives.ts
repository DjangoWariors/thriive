import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { incentiveService } from '../services/incentiveService';
import type {
  ExceptionListParams,
  ExceptionPayload,
  PayoutListParams,
  RunListParams,
  SchemePayload,
} from '../types/incentive';

const incentiveKeys = {
  schemes: (params?: object) => ['incentives', 'schemes', params ?? {}] as const,
  scheme: (id: number) => ['incentives', 'scheme', id] as const,
  schemeVersions: (id: number) => ['incentives', 'scheme-versions', id] as const,
  variablePay: (params?: object) => ['incentives', 'variable-pay', params ?? {}] as const,
  runs: (params?: RunListParams) => ['incentives', 'runs', params ?? {}] as const,
  payouts: (params?: PayoutListParams) => ['incentives', 'payouts', params ?? {}] as const,
  payoutSummary: (params?: PayoutListParams) =>
    ['incentives', 'payout-summary', params ?? {}] as const,
  payout: (id: number) => ['incentives', 'payout', id] as const,
  exceptions: (params?: ExceptionListParams) =>
    ['incentives', 'exceptions', params ?? {}] as const,
  exception: (id: number) => ['incentives', 'exception', id] as const,
};

function useInvalidate() {
  const qc = useQueryClient();
  return (...prefixes: string[][]) => {
    for (const prefix of prefixes) void qc.invalidateQueries({ queryKey: prefix });
  };
}

// ── schemes ─────────────────────────────────────────────────────────────────

export function useSchemes(params?: { entity_type?: string; include_inactive?: boolean; page_size?: number }) {
  return useQuery({
    queryKey: incentiveKeys.schemes(params),
    queryFn: () => incentiveService.listSchemes(params),
  });
}

export function useScheme(id: number | null) {
  return useQuery({
    queryKey: incentiveKeys.scheme(id ?? 0),
    queryFn: () => incentiveService.getScheme(id as number),
    enabled: id !== null && id > 0,
  });
}


export function useCreateScheme() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: SchemePayload) => incentiveService.createScheme(payload),
    onSuccess: () => invalidate(['incentives', 'schemes']),
  });
}

export function useUpdateScheme() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: SchemePayload }) =>
      incentiveService.updateScheme(id, payload),
    onSuccess: () => invalidate(['incentives']),
  });
}

export function useDeactivateScheme() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.deactivateScheme(id),
    onSuccess: () => invalidate(['incentives', 'schemes']),
  });
}

// ── variable pay ────────────────────────────────────────────────────────────

export function useVariablePay(params?: { period?: number; entity?: number; page?: number }) {
  return useQuery({
    queryKey: incentiveKeys.variablePay(params),
    queryFn: () => incentiveService.listVariablePay(params),
  });
}

export function useUpsertVariablePay() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: {
      entity: number; target_period: number; amount: string;
      eligible_working_days?: number | null;
    }) => incentiveService.upsertVariablePay(payload),
    onSuccess: () => invalidate(['incentives', 'variable-pay']),
  });
}

export function useBulkImportVariablePay() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ targetPeriod, rows }: {
      targetPeriod: number; rows: Array<Record<string, unknown>>;
    }) => incentiveService.bulkImportVariablePay(targetPeriod, rows),
    onSuccess: () => invalidate(['incentives', 'variable-pay']),
  });
}

// ── payout runs ─────────────────────────────────────────────────────────────

export function usePayoutRuns(params?: RunListParams) {
  return useQuery({
    queryKey: incentiveKeys.runs(params),
    queryFn: () => incentiveService.listRuns(params),
  });
}

// ── payouts ─────────────────────────────────────────────────────────────────

export function usePayouts(params?: PayoutListParams, enabled = true) {
  return useQuery({
    queryKey: incentiveKeys.payouts(params),
    queryFn: () => incentiveService.listPayouts(params),
    enabled,
  });
}

export function usePayoutSummary(params?: PayoutListParams, enabled = true) {
  return useQuery({
    queryKey: incentiveKeys.payoutSummary(params),
    queryFn: () => incentiveService.payoutSummary(params),
    enabled,
  });
}

export function usePayout(id: number | null) {
  return useQuery({
    queryKey: incentiveKeys.payout(id ?? 0),
    queryFn: () => incentiveService.getPayout(id as number),
    enabled: id !== null && id > 0,
  });
}

// ── exceptions ──────────────────────────────────────────────────────────────

export function usePayoutExceptions(params?: ExceptionListParams) {
  return useQuery({
    queryKey: incentiveKeys.exceptions(params),
    queryFn: () => incentiveService.listExceptions(params),
  });
}

export function useException(id: number | null) {
  return useQuery({
    queryKey: incentiveKeys.exception(id ?? 0),
    queryFn: () => incentiveService.getException(id as number),
    enabled: id !== null && id > 0,
  });
}

export function useExceptionCategories() {
  return useQuery({
    queryKey: ['incentives', 'exception-categories'],
    queryFn: () => incentiveService.listExceptionCategories(),
    staleTime: 5 * 60_000,
  });
}

// The open detail drawer reads its own record, so a decision must refresh both the
// list and that single-record key or the drawer keeps showing "pending".
const EXCEPTION_INVALIDATES: string[][] = [['incentives', 'exceptions'], ['incentives', 'exception']];

export function useCreateException() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: ExceptionPayload) => incentiveService.createException(payload),
    onSuccess: () => invalidate(...EXCEPTION_INVALIDATES),
  });
}

export function useWithdrawException() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.withdrawException(id),
    onSuccess: () => invalidate(...EXCEPTION_INVALIDATES),
  });
}

export function useApproveException() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.approveException(id),
    onSuccess: () => invalidate(...EXCEPTION_INVALIDATES),
  });
}

export function useRejectException() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      incentiveService.rejectException(id, reason),
    onSuccess: () => invalidate(...EXCEPTION_INVALIDATES),
  });
}

// ── payout cycles (month-close) ───────────────────────────────────────────────

// Every cycle transition (and every hold/release inside one) can move the readiness
// checklist, the review board, the register and an individual payout's hold badge —
// they are separate queries, so listing all of them here is what keeps the workspace
// from showing pre-mutation numbers until the user reloads.
const CYCLE_INVALIDATES: string[][] = [
  ['incentives', 'cycles'],
  ['incentives', 'cycle-readiness'],
  ['incentives', 'cycle-review'],
  ['incentives', 'cycle-register'],
  ['incentives', 'payouts'],
  ['incentives', 'payout'],
  ['incentives', 'payout-summary'],
  ['achievements', 'dashboard'],
];

export function useCycles(params?: { status?: string; period?: number }) {
  return useQuery({
    queryKey: ['incentives', 'cycles', params ?? {}] as const,
    queryFn: () => incentiveService.listCycles(params),
  });
}

export function useCycleReadiness(id: number | null) {
  return useQuery({
    queryKey: ['incentives', 'cycle-readiness', id ?? 0] as const,
    queryFn: () => incentiveService.cycleReadiness(id as number),
    enabled: id !== null && id > 0,
  });
}

export function useCycleReview(id: number | null, enabled = true) {
  return useQuery({
    queryKey: ['incentives', 'cycle-review', id ?? 0] as const,
    queryFn: () => incentiveService.cycleReview(id as number),
    enabled: enabled && id !== null && id > 0,
  });
}

export function useCycleRegister(id: number | null, enabled = true) {
  return useQuery({
    queryKey: ['incentives', 'cycle-register', id ?? 0] as const,
    queryFn: () => incentiveService.cycleRegister(id as number),
    enabled: enabled && id !== null && id > 0,
  });
}

export function useOpenCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (periodId: number) => incentiveService.openCycle(periodId),
    onSuccess: () => invalidate(['incentives', 'cycles']),
  });
}

export function useFinalizeCycle() {
  return useMutation({
    mutationFn: ({ id, override, reason }: { id: number; override?: boolean; reason?: string }) =>
      incentiveService.finalizeCycle(id, override ?? false, reason ?? ''),
  });
}

export function useComputeCycle() {
  return useMutation({
    mutationFn: (id: number) => incentiveService.computeCycle(id),
  });
}

export function useSubmitCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.submitCycle(id),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

export function useApproveCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.approveCycle(id),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

export function useRejectCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      incentiveService.rejectCycle(id, reason),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

export function useDisburseCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, paymentRef, registerRef }:
      { id: number; paymentRef: string; registerRef?: string }) =>
      incentiveService.disburseCycle(id, paymentRef, registerRef ?? ''),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

export function useCloseCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.closeCycle(id),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

/** Finalize and compute return a background job rather than the mutated cycle, so the
 *  workspace has to refresh itself when that job reports done. */
export function useInvalidateCycles() {
  const invalidate = useInvalidate();
  return () => invalidate(...CYCLE_INVALIDATES);
}

export function useHoldPayout() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      incentiveService.holdPayout(id, reason),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

export function useReleasePayout() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => incentiveService.releasePayout(id),
    onSuccess: () => invalidate(...CYCLE_INVALIDATES),
  });
}

