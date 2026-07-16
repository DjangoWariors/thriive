import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  AlertTriangle, Banknote, Calculator, CheckCircle2, Eye, IndianRupee,
  SendHorizonal, ShieldX, Undo2, Users,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import {
  useApproveRun, useComputeRun, useMarkRunPaid, usePayoutRuns, usePayouts,
  usePayoutSummary, useRejectRun, useSchemes, useSubmitRun,
} from '../../hooks/useIncentives';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { Pagination } from '../../components/ui/Pagination';
import { Select } from '../../components/ui/Select';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Textarea } from '../../components/ui/Textarea';
import { Tooltip } from '../../components/ui/Tooltip';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { StatCard } from '../../components/data/StatCard';
import { BulkJobProgress } from '../../components/jobs/BulkJobProgress';
import { formatCurrency } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { PayoutRun } from '../../types/incentive';

export default function PayoutSummaryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { can, canWrite } = useRBAC();
  const { selectedPeriodId } = usePeriodSelector();

  const [schemeId, setSchemeId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [computeJobId, setComputeJobId] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<'compute' | 'submit' | 'approve' | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [markingPaid, setMarkingPaid] = useState(false);
  const [paymentRef, setPaymentRef] = useState('');

  const isOperator = canWrite('final_payout');
  const isApprover = can('payout_approve');

  const { data: schemesResp } = useSchemes();
  const schemes = schemesResp?.results ?? [];
  const effectiveSchemeId = schemeId ?? schemes[0]?.id ?? null;

  const runParams = selectedPeriodId !== null && effectiveSchemeId !== null
    ? { period: selectedPeriodId, scheme: effectiveSchemeId } : undefined;
  const { data: runsResp, refetch: refetchRuns } = usePayoutRuns(runParams);
  const run: PayoutRun | undefined = useMemo(
    () => (runsResp?.results ?? []).find((r) => r.status !== 'superseded' && r.status !== 'failed')
      ?? (runsResp?.results ?? [])[0],
    [runsResp],
  );
  const liveRun = run && run.status !== 'superseded' && run.status !== 'failed' ? run : undefined;

  const payoutParams = selectedPeriodId !== null
    ? { period: selectedPeriodId, ...(effectiveSchemeId ? { scheme: effectiveSchemeId } : {}), page }
    : undefined;
  const { data: payoutsResp, isLoading: loadingPayouts } =
    usePayouts(payoutParams, selectedPeriodId !== null);
  const { data: summary } = usePayoutSummary(
    selectedPeriodId !== null
      ? { period: selectedPeriodId, ...(effectiveSchemeId ? { scheme: effectiveSchemeId } : {}) }
      : undefined,
    selectedPeriodId !== null,
  );

  const computeRun = useComputeRun();
  const submitRun = useSubmitRun();
  const approveRun = useApproveRun();
  const rejectRun = useRejectRun();
  const markPaid = useMarkRunPaid();

  const onError = (fallback: string) => (e: unknown) => notify.error(apiErrorMessage(e, fallback));

  const doCompute = () => {
    if (selectedPeriodId === null || effectiveSchemeId === null) return;
    computeRun.mutate({ schemeId: effectiveSchemeId, periodId: selectedPeriodId }, {
      onSuccess: (job) => {
        setComputeJobId(job.id);
        notify.success('Payout computation started');
      },
      onError: onError('Sorry, we couldn’t start the computation'),
    });
    setConfirming(null);
  };

  const isOwnSubmission = liveRun?.submitted_by !== null && liveRun?.submitted_by === user?.id;

  const payouts = payoutsResp?.results ?? [];

  return (
    <div className="p-6">
      <PageHeader
          title="Payouts"
          description="Computed incentives per person for the selected period — every number traces back to achievements, tiers and the scheme version used."
          actions={
            <div className="w-72">
              <Select
                aria-label="Scheme"
                value={effectiveSchemeId ? String(effectiveSchemeId) : ''}
                onChange={(e) => { setSchemeId(e.target.value ? Number(e.target.value) : null); setPage(1); }}
                options={schemes.map((s) => ({ value: String(s.id), label: `${s.name} (v${s.version})` }))}
                placeholder="Choose a scheme…"
              />
            </div>
          }
      />

      {selectedPeriodId === null ? (
        <Card>
          <EmptyState icon={IndianRupee} title="Pick a period"
                      description="Choose a period from the selector in the header to see payouts." />
        </Card>
      ) : (
        <>
          {/* Run lifecycle banner */}
          <Card className="mb-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-700">Payout run:</span>
                {liveRun ? <StatusBadge status={liveRun.status} /> : <Badge variant="default">Not computed</Badge>}
              </div>
              {liveRun && (
                <span className="text-xs text-gray-500">
                  {liveRun.entities_processed} entities · {formatCurrency(liveRun.total_payout)} total
                  {liveRun.error_count > 0 && (
                    <span className="text-danger"> · {liveRun.error_count} skipped</span>
                  )}
                  {liveRun.status === 'under_review' && liveRun.submitted_by_name &&
                    ` · submitted by ${liveRun.submitted_by_name}`}
                  {liveRun.status === 'approved' && liveRun.approved_by_name &&
                    ` · approved by ${liveRun.approved_by_name}`}
                  {liveRun.status === 'paid' && liveRun.payment_ref && ` · ref ${liveRun.payment_ref}`}
                </span>
              )}
              {liveRun?.rejection_reason && liveRun.status === 'computed' && (
                <span className="text-xs text-danger">Rejected: {liveRun.rejection_reason}</span>
              )}

              <div className="ml-auto flex gap-2">
                {isOperator && (!liveRun || liveRun.status === 'computed') && (
                  <Button size="sm" variant={liveRun ? 'outline' : 'primary'}
                          icon={<Calculator size={14} />}
                          loading={computeRun.isPending}
                          onClick={() => setConfirming('compute')}>
                    {liveRun ? 'Recompute' : 'Compute payouts'}
                  </Button>
                )}
                {isOperator && liveRun?.status === 'computed' && (
                  <Button size="sm" icon={<SendHorizonal size={14} />}
                          loading={submitRun.isPending}
                          onClick={() => setConfirming('submit')}>
                    Submit for review
                  </Button>
                )}
                {isApprover && liveRun?.status === 'under_review' && (
                  <>
                    <Tooltip content={isOwnSubmission
                      ? 'You submitted this run — a different reviewer must approve it'
                      : 'Approve and lock this run'}>
                      <Button size="sm" icon={<CheckCircle2 size={14} />}
                              disabled={isOwnSubmission}
                              loading={approveRun.isPending}
                              onClick={() => setConfirming('approve')}>
                        Approve
                      </Button>
                    </Tooltip>
                    <Button size="sm" variant="outline" icon={<Undo2 size={14} />}
                            onClick={() => { setRejectReason(''); setRejecting(true); }}>
                      Reject
                    </Button>
                  </>
                )}
                {isApprover && liveRun?.status === 'approved' && (
                  <Button size="sm" icon={<Banknote size={14} />}
                          onClick={() => { setPaymentRef(''); setMarkingPaid(true); }}>
                    Mark paid
                  </Button>
                )}
              </div>
            </div>

            {computeJobId !== null && (
              <div className="mt-3">
                <BulkJobProgress jobId={computeJobId} onDone={(job) => {
                  setComputeJobId(null);
                  void refetchRuns();
                  if (job.status === 'completed') notify.success('Payouts computed');
                  else notify.error('Computation finished with problems — check the run errors');
                }} />
              </div>
            )}
          </Card>

          {/* Summary cards */}
          {summary && (
            <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-5">
              <StatCard label="Total payout" value={formatCurrency(summary.total_payout)}
                        borderColor="green" icon={IndianRupee} />
              <StatCard label="People paid" value={String(summary.entities)}
                        borderColor="blue" icon={Users} />
              <StatCard label="Capped" value={String(summary.capped_count)}
                        subtitle="Hit the overall cap" borderColor="amber" icon={AlertTriangle} />
              <StatCard label="Gatekeeper failed" value={String(summary.gatekeeper_failed_count)}
                        subtitle="Zeroed by the hurdle" borderColor="red" icon={ShieldX} />
              <StatCard label="With exception" value={String(summary.exception_count)}
                        borderColor="purple" icon={AlertTriangle} />
            </div>
          )}

          {/* Payout table */}
          {loadingPayouts ? (
            <TableSkeleton/>
          ) : payouts.length === 0 ? (
            <Card>
              <EmptyState icon={IndianRupee} title="No payouts yet"
                          description={isOperator
                            ? 'Compute the run for this scheme and period to generate payouts.'
                            : 'Payouts will appear here once the run for this period is computed.'} />
            </Card>
          ) : (
            <Card padding="none">
              <SimpleTable
                rows={payouts}
                rowKey={(p) => p.id}
                onRowClick={(p) => navigate(`/incentives/payouts/${p.id}`)}
                columns={[
                  {header: 'Person', render: (p) => (
                    <>
                      <p className="font-medium text-gray-900">{p.entity_name}</p>
                      <p className="text-xs text-gray-500">{p.entity_code} · {p.entity_type_code}</p>
                    </>
                  )},
                  {header: 'Eligible VP', align: 'right', render: (p) => (
                    <span className="text-gray-600">
                      {formatCurrency(p.eligible_vp)}
                      {parseFloat(p.proration_factor) < 1 && (
                        <p className="text-xs text-amber-600">
                          prorated ×{parseFloat(p.proration_factor).toFixed(2)}
                        </p>
                      )}
                    </span>
                  )},
                  {header: 'Multiplier', align: 'right', render: (p) => (
                    <span className="text-gray-600">{parseFloat(p.total_multiplier).toFixed(2)}×</span>
                  )},
                  {header: 'Gates', render: (p) => <StatusBadge status={p.gatekeeper_status} />},
                  {header: 'Gross', align: 'right', render: (p) => (
                    <span className="text-gray-500">{formatCurrency(p.gross_payout)}</span>
                  )},
                  {header: 'Payout', align: 'right', render: (p) => (
                    <span className="font-semibold text-gray-900">{formatCurrency(p.total_payout)}</span>
                  )},
                  {header: 'Flags', render: (p) => (
                    <div className="flex gap-1">
                      {p.capped && <Badge variant="warning">Capped</Badge>}
                      {p.has_exception && <Badge variant="purple">Exception</Badge>}
                    </div>
                  )},
                  {header: 'Actions', align: 'right', render: (p) => (
                    <Button variant="ghost" size="sm" aria-label={`View breakdown for ${p.entity_name}`}>
                      <Eye className="h-4 w-4" />
                    </Button>
                  )},
                ]}
              />
              <Pagination count={payoutsResp?.count ?? 0} page={page} onPageChange={setPage} />
            </Card>
          )}
        </>
      )}

      {/* Confirmations */}
      <ConfirmDialog
        open={confirming === 'compute'}
        onClose={() => setConfirming(null)}
        onConfirm={doCompute}
        title={liveRun ? 'Recompute this run?' : 'Compute payouts?'}
        message={liveRun
          ? 'The current computed run will be superseded and payouts recalculated from the latest achievements, variable pay and approved exceptions.'
          : 'Payouts will be calculated for every eligible person using the latest achievements, variable pay and approved exceptions.'}
        confirmLabel={liveRun ? 'Recompute' : 'Compute'}
      />
      <ConfirmDialog
        open={confirming === 'submit'}
        onClose={() => setConfirming(null)}
        onConfirm={() => {
          if (liveRun) submitRun.mutate(liveRun.id, {
            onSuccess: () => notify.success('Run submitted for review'),
            onError: onError('Sorry, we couldn’t submit the run'),
          });
          setConfirming(null);
        }}
        title="Submit for review?"
        message="A reviewer with payout-approval rights will check and approve this run. You won’t be able to recompute while it’s under review."
        confirmLabel="Submit"
      />
      <ConfirmDialog
        open={confirming === 'approve'}
        onClose={() => setConfirming(null)}
        onConfirm={() => {
          if (liveRun) approveRun.mutate(liveRun.id, {
            onSuccess: () => notify.success('Run approved — payouts are now locked'),
            onError: onError('Sorry, we couldn’t approve the run'),
          });
          setConfirming(null);
        }}
        title="Approve this run?"
        message={`${liveRun?.entities_processed ?? 0} payouts totalling ${formatCurrency(liveRun?.total_payout ?? '0')} will be locked. Corrections after this require rejecting and recomputing.`}
        confirmLabel="Approve"
      />

      {/* Reject modal */}
      <Modal open={rejecting} onClose={() => setRejecting(false)} title="Reject this run" size="md"
             footer={
               <div className="flex justify-end gap-2">
                 <Button variant="outline" onClick={() => setRejecting(false)}>Cancel</Button>
                 <Button variant="danger" disabled={!rejectReason.trim()}
                         loading={rejectRun.isPending}
                         onClick={() => {
                           if (!liveRun) return;
                           rejectRun.mutate({ id: liveRun.id, reason: rejectReason.trim() }, {
                             onSuccess: () => { setRejecting(false); notify.success('Run rejected — it can be recomputed'); },
                             onError: onError('Sorry, we couldn’t reject the run'),
                           });
                         }}>
                   Reject run
                 </Button>
               </div>
             }>
        <Textarea label="Why is this run being rejected?" rows={3} value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="e.g. Variable pay for the new joiners is missing" />
      </Modal>

      {/* Mark paid modal */}
      <Modal open={markingPaid} onClose={() => setMarkingPaid(false)} title="Mark run as paid" size="md"
             footer={
               <div className="flex justify-end gap-2">
                 <Button variant="outline" onClick={() => setMarkingPaid(false)}>Cancel</Button>
                 <Button loading={markPaid.isPending}
                         onClick={() => {
                           if (!liveRun) return;
                           markPaid.mutate({ id: liveRun.id, paymentRef: paymentRef.trim() }, {
                             onSuccess: () => { setMarkingPaid(false); notify.success('Run marked as paid'); },
                             onError: onError('Sorry, we couldn’t mark the run as paid'),
                           });
                         }}>
                   Mark paid
                 </Button>
               </div>
             }>
        <Input label="Payment reference (optional)" value={paymentRef}
               onChange={(e) => setPaymentRef(e.target.value)}
               placeholder="e.g. NEFT batch id or payroll cycle" />
      </Modal>
    </div>
  );
}
