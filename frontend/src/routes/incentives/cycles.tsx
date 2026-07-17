import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  AlertTriangle, Banknote, CalendarClock, Calculator, CheckCircle2, Download,
  IndianRupee, RefreshCw, SendHorizonal, ShieldX, Snowflake, Undo2, Users,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import {
  useApproveCycle, useCloseCycle, useComputeCycle, useCycleReadiness, useCycleRegister,
  useCycleReview, useCycles, useDisburseCycle, useFinalizeCycle, useOpenCycle, useRejectCycle,
  useReleasePayout, useSubmitCycle,
} from '../../hooks/useIncentives';
import { incentiveService } from '../../services/incentiveService';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Textarea } from '../../components/ui/Textarea';
import { Tooltip } from '../../components/ui/Tooltip';
import { PageHeader } from '../../components/ui/PageHeader';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { StatCard } from '../../components/data/StatCard';
import { BulkJobProgress } from '../../components/jobs/BulkJobProgress';
import { formatCurrency } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { CycleStatus, PayoutCycle, ReadinessCheck } from '../../types/incentive';

const READINESS_DOT: Record<string, string> = {
  green: 'bg-green-500', warning: 'bg-amber-500', red: 'bg-red-500',
};

/** Where the cycle is in the close process, for a compact progress rail. */
const STAGES: { status: CycleStatus; label: string }[] = [
  { status: 'open', label: 'Open' },
  { status: 'computing', label: 'Finalized' },
  { status: 'under_review', label: 'Review' },
  { status: 'approved', label: 'Approved' },
  { status: 'disbursed', label: 'Disbursed' },
];

export default function CycleWorkspacePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { can, canWrite } = useRBAC();
  const { selectedPeriodId } = usePeriodSelector();

  const isOperator = canWrite('final_payout');
  const isApprover = can('payout_approve');

  const { data: cyclesResp, isLoading } = useCycles();
  const cycles = useMemo(() => cyclesResp?.results ?? [], [cyclesResp]);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const effectiveId = selectedId ?? cycles[0]?.id ?? null;
  const cycle = cycles.find((c) => c.id === effectiveId) ?? null;

  const periodHasCycle = selectedPeriodId !== null
    && cycles.some((c) => c.target_period === selectedPeriodId);

  const openCycle = useOpenCycle();
  const finalize = useFinalizeCycle();
  const compute = useComputeCycle();
  const submit = useSubmitCycle();
  const approve = useApproveCycle();
  const reject = useRejectCycle();
  const disburse = useDisburseCycle();
  const close = useCloseCycle();

  const [job, setJob] = useState<{ id: number; kind: 'finalize' | 'compute' } | null>(null);
  const [confirm, setConfirm] = useState<'finalize' | 'compute' | 'submit' | 'approve' | 'close' | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [disbursing, setDisbursing] = useState(false);
  const [paymentRef, setPaymentRef] = useState('');

  const onError = (fallback: string) => (e: unknown) => notify.error(apiErrorMessage(e, fallback));

  const readiness = useCycleReadiness(
    cycle && (cycle.status === 'open' || cycle.status === 'finalizing') ? cycle.id : null,
  );
  const reviewEnabled = !!cycle && ['under_review', 'approved', 'disbursed', 'closed'].includes(cycle.status);
  const review = useCycleReview(cycle?.id ?? null, reviewEnabled);
  const registerEnabled = !!cycle && ['under_review', 'approved', 'disbursed', 'closed'].includes(cycle.status);
  const register = useCycleRegister(cycle?.id ?? null, registerEnabled);

  const isOwnSubmission = cycle?.submitted_by !== null && cycle?.submitted_by === user?.id;

  const doFinalize = (override: boolean) => {
    if (!cycle) return;
    finalize.mutate({ id: cycle.id, override, reason: override ? overrideReason.trim() : '' }, {
      onSuccess: (j) => { setJob({ id: j.id, kind: 'finalize' }); notify.success('Finalizing — freezing achievements'); },
      onError: onError('Sorry, we couldn’t finalize the cycle'),
    });
    setConfirm(null);
    setOverrideOpen(false);
  };

  const doCompute = () => {
    if (!cycle) return;
    compute.mutate(cycle.id, {
      onSuccess: (j) => { setJob({ id: j.id, kind: 'compute' }); notify.success('Computing final payouts'); },
      onError: onError('Sorry, we couldn’t compute the cycle'),
    });
    setConfirm(null);
  };

  const downloadCsv = async () => {
    if (!cycle) return;
    try {
      const blob = await incentiveService.downloadRegisterCsv(cycle.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `register-${cycle.period_code}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      notify.error(apiErrorMessage(e, 'Sorry, we couldn’t download the register'));
    }
  };

  return (
    <div className="p-6">
      <PageHeader
        title="Payout Cycles"
        description="The monthly incentive close: run the readiness checklist, freeze achievements, compute every scheme in one cycle, review, approve and disburse."
        actions={
          isOperator && selectedPeriodId !== null && !periodHasCycle ? (
            <Button icon={<CalendarClock size={16} />} loading={openCycle.isPending}
              onClick={() => openCycle.mutate(selectedPeriodId, {
                onSuccess: (c) => { setSelectedId(c.id); notify.success('Cycle opened'); },
                onError: onError('Sorry, we couldn’t open the cycle'),
              })}>
              Open cycle for selected period
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <TableSkeleton />
      ) : cycles.length === 0 ? (
        <Card>
          <EmptyState icon={IndianRupee} title="No payout cycles yet"
            description={isOperator
              ? 'Pick a period in the header, then open its cycle to begin the month-close.'
              : 'Payout cycles will appear here once the operations team opens one.'} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
          <MonthRail cycles={cycles} selectedId={effectiveId} onSelect={setSelectedId} />

          {cycle && (
            <div className="space-y-4">
              <StageHeader cycle={cycle} />

              {job && (
                <Card>
                  <BulkJobProgress jobId={job.id} onDone={(j) => {
                    setJob(null);
                    if (j.status === 'completed') {
                      notify.success(job.kind === 'finalize' ? 'Achievements frozen' : 'Final payouts computed');
                    } else {
                      notify.error('The job finished with problems — check its errors');
                    }
                  }} />
                </Card>
              )}

              {/* Readiness + finalize */}
              {(cycle.status === 'open' || cycle.status === 'finalizing') && (
                <ReadinessPanel
                  checks={readiness.data?.checks ?? []}
                  ready={readiness.data?.is_ready ?? null}
                  loading={readiness.isLoading}
                  onRecompute={() => void readiness.refetch()}
                  canAct={isOperator}
                  onFinalize={() => setConfirm('finalize')}
                  onOverride={() => { setOverrideReason(''); setOverrideOpen(true); }}
                />
              )}

              {/* Compute */}
              {cycle.status === 'computing' && (
                <Card>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-900">Achievements frozen</p>
                      <p className="text-sm text-gray-500">
                        Finalized {cycle.finalized_by_name ? `by ${cycle.finalized_by_name}` : ''}.
                        Compute the final payout runs for every active scheme.
                      </p>
                    </div>
                    {isOperator && (
                      <Button icon={<Calculator size={16} />} loading={compute.isPending}
                        onClick={() => setConfirm('compute')}>Compute final payouts</Button>
                    )}
                  </div>
                </Card>
              )}

              {/* Review board */}
              {reviewEnabled && review.data && (
                <ReviewBoard
                  cycle={cycle}
                  review={review.data}
                  isApprover={isApprover}
                  isOperator={isOperator}
                  isOwnSubmission={!!isOwnSubmission}
                  onSubmit={() => setConfirm('submit')}
                  onApprove={() => setConfirm('approve')}
                  onReject={() => { setRejectReason(''); setRejecting(true); }}
                  onDisburse={() => { setPaymentRef(''); setDisbursing(true); }}
                  onOpenPayout={(id) => navigate(`/incentives/payouts/${id}`)}
                />
              )}

              {/* Disbursement register */}
              {registerEnabled && (
                <Card padding="none">
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="font-medium text-gray-900">Disbursement register</p>
                      <p className="text-xs text-gray-500">
                        Held payouts are excluded. {register.data
                          ? `${register.data.payee_count} payees · ${formatCurrency(register.data.total_payout)}`
                          : ''}{register.data && register.data.held_count > 0 ? ` · ${register.data.held_count} held` : ''}
                      </p>
                    </div>
                    <Button variant="outline" size="sm" icon={<Download size={14} />} onClick={downloadCsv}>
                      Download CSV
                    </Button>
                  </div>
                  {register.data && register.data.rows.length > 0 && (
                    <SimpleTable
                      rows={register.data.rows}
                      rowKey={(r) => r.entity_code}
                      columns={[
                        { header: 'Payee', render: (r) => (
                          <><p className="font-medium text-gray-900">{r.entity_name}</p>
                            <p className="text-xs text-gray-500">{r.entity_code}</p></>
                        ) },
                        { header: 'Scheme', render: (r) => <span className="text-gray-600">{r.scheme_code}</span> },
                        { header: 'Type', render: (r) => (
                          r.kind === 'adjustment'
                            ? <Badge variant="purple">Adj · {r.adjustment_for}</Badge>
                            : <span className="text-xs text-gray-400">Final</span>) },
                        { header: 'Eligible VP', align: 'right', render: (r) => (
                          <span className="text-gray-500">{formatCurrency(r.eligible_vp)}</span>) },
                        { header: 'Gates', render: (r) => <StatusBadge status={r.gatekeeper_status} /> },
                        { header: 'Payout', align: 'right', render: (r) => (
                          <span className={`font-semibold ${parseFloat(r.total_payout) < 0 ? 'text-red-600' : 'text-gray-900'}`}>
                            {formatCurrency(r.total_payout)}</span>) },
                        { header: 'Ref', render: (r) => <span className="text-xs text-gray-500">{r.payment_ref || '—'}</span> },
                      ]}
                    />
                  )}
                </Card>
              )}

              {cycle.status === 'disbursed' && isOperator && (
                <div className="flex justify-end">
                  <Button variant="outline" icon={<Snowflake size={16} />} loading={close.isPending}
                    onClick={() => setConfirm('close')}>Close &amp; archive cycle</Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Confirmations */}
      <ConfirmDialog open={confirm === 'finalize'} onClose={() => setConfirm(null)}
        onConfirm={() => doFinalize(false)} title="Finalize this cycle?"
        message="One last achievement compute runs and the period's numbers are frozen. Payouts are then computed off the frozen figures."
        confirmLabel="Finalize" />
      <ConfirmDialog open={confirm === 'compute'} onClose={() => setConfirm(null)}
        onConfirm={doCompute} title="Compute final payouts?"
        message="A final run is computed for every active scheme of the period, off the frozen achievements."
        confirmLabel="Compute" />
      <ConfirmDialog open={confirm === 'submit'} onClose={() => setConfirm(null)}
        onConfirm={() => { if (cycle) submit.mutate(cycle.id, {
          onSuccess: () => notify.success('Cycle submitted for approval'),
          onError: onError('Sorry, we couldn’t submit the cycle') }); setConfirm(null); }}
        title="Submit cycle for approval?"
        message="A checker with payout-approval rights must approve the cycle. You can still hold individual payees before disbursement."
        confirmLabel="Submit" />
      <ConfirmDialog open={confirm === 'approve'} onClose={() => setConfirm(null)}
        onConfirm={() => { if (cycle) approve.mutate(cycle.id, {
          onSuccess: () => notify.success('Cycle approved'),
          onError: onError('Sorry, we couldn’t approve the cycle') }); setConfirm(null); }}
        title="Approve this cycle?"
        message={`${cycle ? formatCurrency(cycle.total_payout) : ''} across all schemes will be locked for disbursement.`}
        confirmLabel="Approve" />
      <ConfirmDialog open={confirm === 'close'} onClose={() => setConfirm(null)}
        onConfirm={() => { if (cycle) close.mutate(cycle.id, {
          onSuccess: () => notify.success('Cycle closed'),
          onError: onError('Sorry, we couldn’t close the cycle') }); setConfirm(null); }}
        title="Close and archive this cycle?"
        message="After closing, restatements are made through adjustment runs on a later cycle."
        confirmLabel="Close" />

      {/* Override readiness */}
      <Modal open={overrideOpen} onClose={() => setOverrideOpen(false)} title="Finalize with an override" size="md"
        footer={<div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setOverrideOpen(false)}>Cancel</Button>
          <Button variant="danger" disabled={!overrideReason.trim()} loading={finalize.isPending}
            onClick={() => doFinalize(true)}>Override &amp; finalize</Button>
        </div>}>
        <p className="mb-3 text-sm text-gray-600">
          Readiness has red checks. Finalizing anyway is recorded in the audit trail with your reason.
        </p>
        <Textarea label="Why finalize despite red checks?" rows={3} value={overrideReason}
          onChange={(e) => setOverrideReason(e.target.value)}
          placeholder="e.g. DMS backfill lands tomorrow; pay on the frozen numbers and true up next cycle." />
      </Modal>

      {/* Reject */}
      <Modal open={rejecting} onClose={() => setRejecting(false)} title="Send cycle back to review" size="md"
        footer={<div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setRejecting(false)}>Cancel</Button>
          <Button variant="danger" disabled={!rejectReason.trim()} loading={reject.isPending}
            onClick={() => { if (!cycle) return; reject.mutate({ id: cycle.id, reason: rejectReason.trim() }, {
              onSuccess: () => { setRejecting(false); notify.success('Cycle sent back to review'); },
              onError: onError('Sorry, we couldn’t reject the cycle') }); }}>Send back</Button>
        </div>}>
        <Textarea label="Why is this cycle being sent back?" rows={3} value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="e.g. Two disputes still open — hold those payees and resubmit." />
      </Modal>

      {/* Disburse */}
      <Modal open={disbursing} onClose={() => setDisbursing(false)} title="Disburse this cycle" size="md"
        footer={<div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDisbursing(false)}>Cancel</Button>
          <Button loading={disburse.isPending} onClick={() => { if (!cycle) return;
            disburse.mutate({ id: cycle.id, paymentRef: paymentRef.trim() }, {
              onSuccess: () => { setDisbursing(false); notify.success('Cycle disbursed'); },
              onError: onError('Sorry, we couldn’t disburse the cycle') }); }}>Disburse</Button>
        </div>}>
        <p className="mb-3 text-sm text-gray-600">
          Final runs are marked paid and the register is cut. Held payouts are excluded and ride the next cycle.
        </p>
        <Input label="Payment reference" value={paymentRef}
          onChange={(e) => setPaymentRef(e.target.value)} placeholder="e.g. NEFT batch id or payroll cycle" />
      </Modal>
    </div>
  );
}

function MonthRail({ cycles, selectedId, onSelect }: {
  cycles: PayoutCycle[]; selectedId: number | null; onSelect: (id: number) => void;
}) {
  return (
    <Card padding="none">
      <ul className="divide-y divide-gray-100">
        {cycles.map((c) => (
          <li key={c.id}>
            <button type="button" onClick={() => onSelect(c.id)}
              className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                c.id === selectedId ? 'bg-primary-50' : 'hover:bg-gray-50'}`}>
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-900">{c.period_code}</span>
                <StatusBadge status={c.status} />
              </div>
              <span className="text-xs text-gray-500">{formatCurrency(c.total_payout)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function StageHeader({ cycle }: { cycle: PayoutCycle }) {
  const activeIdx = Math.max(0, STAGES.findIndex((s) => s.status === cycle.status));
  const paidIdx = cycle.status === 'disbursed' || cycle.status === 'closed' ? STAGES.length - 1 : activeIdx;
  return (
    <Card>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{cycle.period_name}</h2>
          <p className="text-sm text-gray-500">{cycle.period_code} · {cycle.period_type}</p>
        </div>
        <StatusBadge status={cycle.status} />
      </div>
      <div className="mt-4 flex items-center gap-1">
        {STAGES.map((s, i) => (
          <div key={s.status} className="flex flex-1 items-center gap-1">
            <div className={`h-1.5 flex-1 rounded-full ${i <= paidIdx ? 'bg-primary' : 'bg-gray-200'}`} />
            <span className={`whitespace-nowrap text-xs ${i <= paidIdx ? 'text-primary' : 'text-gray-400'}`}>
              {s.label}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ReadinessPanel({ checks, ready, loading, onRecompute, canAct, onFinalize, onOverride }: {
  checks: ReadinessCheck[]; ready: boolean | null; loading: boolean; onRecompute: () => void;
  canAct: boolean; onFinalize: () => void; onOverride: () => void;
}) {
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-gray-900">Readiness</h3>
          {ready === true && <Badge variant="success">Ready</Badge>}
          {ready === false && <Badge variant="warning">Not ready</Badge>}
        </div>
        <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} loading={loading}
          onClick={onRecompute}>Recompute</Button>
      </div>
      <ul className="space-y-2">
        {checks.map((c) => (
          <li key={c.key} className="flex items-start gap-3">
            <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${READINESS_DOT[c.status] ?? 'bg-gray-300'}`} />
            <div>
              <p className="text-sm font-medium text-gray-800">{c.label}</p>
              <p className="text-xs text-gray-500">{c.detail}</p>
            </div>
          </li>
        ))}
        {checks.length === 0 && <li className="text-sm text-gray-500">Recompute to see the checklist.</li>}
      </ul>
      {canAct && (
        <div className="mt-4 flex justify-end gap-2">
          {ready === false && (
            <Button variant="outline" icon={<AlertTriangle size={16} />} onClick={onOverride}>
              Finalize with override
            </Button>
          )}
          <Tooltip content={ready === false ? 'Resolve red checks or use override' : 'Freeze achievements and proceed'}>
            <Button icon={<Snowflake size={16} />} disabled={ready !== true} onClick={onFinalize}>
              Finalize
            </Button>
          </Tooltip>
        </div>
      )}
    </Card>
  );
}

function ReviewBoard({ cycle, review, isApprover, isOperator, isOwnSubmission,
  onSubmit, onApprove, onReject, onDisburse, onOpenPayout }: {
  cycle: PayoutCycle;
  review: NonNullable<ReturnType<typeof useCycleReview>['data']>;
  isApprover: boolean; isOperator: boolean; isOwnSubmission: boolean;
  onSubmit: () => void; onApprove: () => void; onReject: () => void; onDisburse: () => void;
  onOpenPayout: (id: number) => void;
}) {
  const releasePayout = useReleasePayout();
  const s = review.stats;
  return (
    <>
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="font-medium text-gray-900">Review</h3>
          {cycle.submitted_by_name && <span className="text-xs text-gray-500">submitted by {cycle.submitted_by_name}</span>}
          {cycle.approved_by_name && <span className="text-xs text-gray-500">· approved by {cycle.approved_by_name}</span>}
          {isOwnSubmission && cycle.status === 'under_review' && (
            <span className="text-xs font-medium text-amber-600">
              You submitted this cycle — a different reviewer must approve it (four-eyes rule).
            </span>
          )}
          <div className="ml-auto flex gap-2">
            {isOperator && cycle.status === 'under_review' && cycle.submitted_by === null && (
              <Button size="sm" icon={<SendHorizonal size={14} />} onClick={onSubmit}>Submit</Button>
            )}
            {isApprover && cycle.status === 'under_review' && cycle.submitted_by !== null && (
              <>
                <Tooltip content={isOwnSubmission ? 'You submitted this cycle — a different reviewer must approve' : 'Approve the cycle'}>
                  <Button size="sm" icon={<CheckCircle2 size={14} />} disabled={isOwnSubmission} onClick={onApprove}>Approve</Button>
                </Tooltip>
                <Button size="sm" variant="outline" icon={<Undo2 size={14} />} onClick={onReject}>Send back</Button>
              </>
            )}
            {isApprover && cycle.status === 'approved' && (
              <Button size="sm" icon={<Banknote size={14} />} onClick={onDisburse}>Disburse</Button>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatCard label="Total payout" value={formatCurrency(s.total_payout)} borderColor="green" icon={IndianRupee} />
          <StatCard label="Payees" value={String(s.payees)} borderColor="blue" icon={Users} />
          <StatCard label="Held" value={String(s.held)} borderColor="amber" icon={AlertTriangle} />
          <StatCard label="Gatekeeper failed" value={String(s.gated)} borderColor="red" icon={ShieldX} />
          <StatCard label="With exception" value={String(s.exceptions)} borderColor="purple" icon={AlertTriangle} />
        </div>

        {review.variance && (
          <p className="mt-3 text-sm text-gray-600">
            vs {review.variance.prior_period_code}: {formatCurrency(review.variance.prior_total)} →{' '}
            <span className={parseFloat(review.variance.delta) >= 0 ? 'text-green-600' : 'text-red-600'}>
              {parseFloat(review.variance.delta) >= 0 ? '+' : ''}{formatCurrency(review.variance.delta)} ({review.variance.delta_pct}%)
            </span>
          </p>
        )}
        {s.adjustments > 0 && (
          <p className="mt-2 text-sm text-gray-600">
            {s.adjustments} adjustment{s.adjustments > 1 ? 's' : ''} riding this cycle ·{' '}
            net <span className={parseFloat(s.adjustments_net) >= 0 ? 'text-green-600' : 'text-red-600'}>
              {formatCurrency(s.adjustments_net)}</span> · grand total{' '}
            <strong>{formatCurrency(s.grand_total)}</strong>
          </p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h4 className="mb-3 text-sm font-medium text-gray-900">Multiplier distribution</h4>
          <ul className="space-y-1.5">
            {review.multiplier_distribution.map((b) => (
              <li key={b.bucket} className="flex items-center gap-2 text-sm">
                <span className="w-16 text-gray-600">{b.bucket}</span>
                <span className="h-3 rounded bg-primary/70" style={{ width: `${Math.min(100, b.count * 12)}px` }} />
                <span className="text-xs text-gray-500">{b.count}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card padding="none">
          <p className="px-4 py-3 text-sm font-medium text-gray-900">Held payees</p>
          {review.outliers.held.length === 0 ? (
            <p className="px-4 pb-4 text-sm text-gray-500">None held.</p>
          ) : (
            <SimpleTable
              rows={review.outliers.held}
              rowKey={(r) => r.payout_id}
              columns={[
                { header: 'Payee', render: (r) => (
                  <><p className="font-medium text-gray-900">{r.entity_name}</p>
                    <p className="text-xs text-gray-500">{r.entity_code}</p></>) },
                { header: 'Payout', align: 'right', render: (r) => formatCurrency(r.total_payout) },
                { header: '', align: 'right', render: (r) => (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => onOpenPayout(r.payout_id)}>View</Button>
                    {isOperator && cycle.status === 'under_review' && (
                      <Button size="sm" variant="outline" onClick={() => releasePayout.mutate(r.payout_id, {
                        onSuccess: () => notify.success('Payout released'),
                        onError: (e) => notify.error(apiErrorMessage(e, 'Couldn’t release')) })}>Release</Button>
                    )}
                  </div>) },
              ]}
            />
          )}
        </Card>
      </div>
    </>
  );
}
