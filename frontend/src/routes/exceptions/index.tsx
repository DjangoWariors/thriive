import { useState } from 'react';
import { AlertTriangle, Check, Plus, Search, X } from 'lucide-react';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import { useEntitySearch } from '../../hooks/useEntities';
import { useRBAC } from '../../hooks/useRBAC';
import {
  useApproveException, useCreateException, useExceptionCategories, usePayoutExceptions,
  useRejectException, useScheme, useSchemes, useWithdrawException,
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
import { StatCard } from '../../components/data/StatCard';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Textarea } from '../../components/ui/Textarea';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { formatCurrency, formatDate } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type {
  ExceptionStatus, KpiExceptionAction, PayoutException,
} from '../../types/incentive';

const ACTION_OPTIONS: { value: KpiExceptionAction; label: string }[] = [
  { value: 'actual_performance', label: 'Compute normally' },
  { value: 'default_1x', label: 'Pay as if on target (1×)' },
  { value: 'zero', label: 'Pay nothing' },
];

const ACTION_PHRASES: Record<KpiExceptionAction, string> = {
  actual_performance: 'computed normally',
  default_1x: 'paid as if exactly on target (1×)',
  zero: 'not paid',
};

const STATUS_FILTERS: { value: '' | ExceptionStatus; label: string }[] = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
];

function actionSummary(e: PayoutException): string {
  const parts: string[] = [];
  if (e.sales_kpi_action !== 'actual_performance') {
    parts.push(`sales ${e.sales_kpi_action === 'default_1x' ? '1×' : 'zero'}`);
  }
  if (e.execution_kpi_action !== 'actual_performance') {
    parts.push(`execution ${e.execution_kpi_action === 'default_1x' ? '1×' : 'zero'}`);
  }
  if (e.gatekeeper_action === 'exempted') parts.push('gatekeeper exempted');
  return parts.length ? parts.join(' · ') : 'actuals';
}

export default function ExceptionsPage() {
  const { selectedPeriodId } = usePeriodSelector();
  const { can, canWrite } = useRBAC();
  const canRaise = canWrite('exception_management');
  const canDecide = can('exception_approve');

  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<'' | ExceptionStatus>('');
  const [raising, setRaising] = useState(false);
  const [rejecting, setRejecting] = useState<PayoutException | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [approving, setApproving] = useState<PayoutException | null>(null);
  const [withdrawing, setWithdrawing] = useState<PayoutException | null>(null);

  const params = selectedPeriodId !== null
    ? { period: selectedPeriodId, page, ...(statusFilter ? { status: statusFilter } : {}) }
    : undefined;
  const { data: resp, isLoading } = usePayoutExceptions(params);
  const { data: allResp } = usePayoutExceptions(
    selectedPeriodId !== null ? { period: selectedPeriodId } : undefined,
  );
  const approve = useApproveException();
  const reject = useRejectException();
  const withdraw = useWithdrawException();

  const all = allResp?.results ?? [];
  const counts = {
    pending: all.filter((e) => e.status === 'pending').length,
    approved: all.filter((e) => e.status === 'approved').length,
    rejected: all.filter((e) => e.status === 'rejected').length,
    total: allResp?.count ?? 0,
  };
  const rows = resp?.results ?? [];

  return (
    <div className="p-6">
      <PageHeader
          title="Payout Exceptions"
          description="Approved overrides of performance treatment — leave, transfers, data issues. They apply only to runs computed after approval (maker raises, a different checker approves)."
          actions={<>{canRaise && selectedPeriodId !== null && (
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setRaising(true)}>
            Raise exception
          </Button>
        )}</>}
      />

      {selectedPeriodId === null ? (
        <Card>
          <EmptyState icon={AlertTriangle} title="Pick a period"
                      description="Choose a period from the selector in the header." />
        </Card>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Pending" value={String(counts.pending)} borderColor="amber" />
            <StatCard label="Approved" value={String(counts.approved)} borderColor="green" />
            <StatCard label="Rejected" value={String(counts.rejected)} borderColor="red" />
            <StatCard label="Total" value={String(counts.total)} borderColor="blue" />
          </div>

          <div className="mb-4 w-48">
            <Select value={statusFilter}
                    onChange={(e) => { setStatusFilter(e.target.value as '' | ExceptionStatus); setPage(1); }}
                    options={STATUS_FILTERS} />
          </div>

          {isLoading ? (
            <TableSkeleton/>
          ) : rows.length === 0 ? (
            <Card>
              <EmptyState icon={AlertTriangle} title="No exceptions"
                          description="Nothing has been raised for this period and filter." />
            </Card>
          ) : (
            <Card padding="none">
              <SimpleTable
                rows={rows}
                rowKey={(e) => e.id}
                columns={[
                  {header: 'Person', render: (e) => (
                    <>
                      <p className="font-medium text-gray-900">{e.entity_name}</p>
                      <p className="text-xs text-gray-500">{e.entity_code}</p>
                    </>
                  )},
                  {header: 'Category', render: (e) => (
                    <>
                      {e.category ? <Badge variant="purple">{e.category}</Badge> : <span className="text-gray-400">—</span>}
                      {e.parent !== null && (
                        <span title="Auto-created by a multi-month exception">
                          <Badge variant="default" className="ml-1">auto</Badge>
                        </span>
                      )}
                    </>
                  )},
                  {header: 'Treatment', render: (e) => <span className="text-xs text-gray-600">{actionSummary(e)}</span>},
                  {header: 'Impact', align: 'right', render: (e) => (
                    <span className="text-gray-700">
                      {e.impact_amount != null && e.impact_amount !== ''
                        ? formatCurrency(e.impact_amount)
                        : <span className="text-gray-300">—</span>}
                    </span>
                  )},
                  {header: 'Reason', className: 'max-w-56', render: (e) => (
                    <span className="block truncate text-gray-600" title={e.reason}>{e.reason}</span>
                  )},
                  {header: 'Scheme', render: (e) => <span className="text-gray-500">{e.scheme_code ?? 'All'}</span>},
                  {header: 'Status', render: (e) => (
                    <>
                      <StatusBadge status={e.status} />
                      {e.status === 'pending' && e.current_step_name && (
                        <p className="mt-0.5 text-xs text-gray-400">at {e.current_step_name}</p>
                      )}
                      {e.status === 'rejected' && e.rejection_reason && (
                        <p className="mt-0.5 max-w-44 truncate text-xs text-danger" title={e.rejection_reason}>
                          {e.rejection_reason}
                        </p>
                      )}
                    </>
                  )},
                  {header: 'Raised', render: (e) => (
                    <span className="text-xs text-gray-500">
                      {formatDate(e.created_at)}
                      {e.requested_by_name && <p className="text-gray-500">{e.requested_by_name}</p>}
                    </span>
                  )},
                  {header: 'Actions', align: 'right', render: (e) => (
                    <div className="flex justify-end gap-1">
                      {canDecide && e.status === 'pending' && (
                        <>
                          <Button variant="ghost" size="sm" aria-label={`Approve exception for ${e.entity_name}`}
                                  onClick={() => setApproving(e)}>
                            <Check className="h-4 w-4 text-success" />
                          </Button>
                          <Button variant="ghost" size="sm" aria-label={`Reject exception for ${e.entity_name}`}
                                  onClick={() => { setRejectReason(''); setRejecting(e); }}>
                            <X className="h-4 w-4 text-danger" />
                          </Button>
                        </>
                      )}
                      {canRaise && e.status === 'pending' && (
                        <Button variant="ghost" size="sm" aria-label={`Withdraw exception for ${e.entity_name}`}
                                onClick={() => setWithdrawing(e)}>
                          <span className="text-xs text-gray-500">Withdraw</span>
                        </Button>
                      )}
                    </div>
                  )},
                ]}
              />
              <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage} />
            </Card>
          )}

          <RaiseModal open={raising} onClose={() => setRaising(false)} periodId={selectedPeriodId} />
        </>
      )}

      <ConfirmDialog
        open={approving !== null}
        onClose={() => setApproving(null)}
        onConfirm={() => {
          if (approving) approve.mutate(approving.id, {
            onSuccess: () => notify.success('Exception approved — it applies to the next computed run'),
            onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t approve it')),
          });
          setApproving(null);
        }}
        title="Approve this exception?"
        message={`${approving?.entity_name ?? ''}: ${approving ? actionSummary(approving) : ''}. It will apply to payout runs computed from now on.`}
        confirmLabel="Approve"
      />

      <ConfirmDialog
        open={withdrawing !== null}
        onClose={() => setWithdrawing(null)}
        onConfirm={() => {
          if (withdrawing) withdraw.mutate(withdrawing.id, {
            onSuccess: () => notify.success('Exception withdrawn'),
            onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t withdraw it')),
          });
          setWithdrawing(null);
        }}
        title="Withdraw this exception?"
        message="The pending request will be removed."
        confirmLabel="Withdraw"
        variant="danger"
      />

      <Modal open={rejecting !== null} onClose={() => setRejecting(null)}
             title="Reject this exception" size="md"
             footer={
               <div className="flex justify-end gap-2">
                 <Button variant="outline" onClick={() => setRejecting(null)}>Cancel</Button>
                 <Button variant="danger" disabled={!rejectReason.trim()} loading={reject.isPending}
                         onClick={() => {
                           if (!rejecting) return;
                           reject.mutate({ id: rejecting.id, reason: rejectReason.trim() }, {
                             onSuccess: () => { setRejecting(null); notify.success('Exception rejected'); },
                             onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t reject it')),
                           });
                         }}>
                   Reject
                 </Button>
               </div>
             }>
        <Textarea label="Why is this being rejected?" rows={3} value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)} />
      </Modal>
    </div>
  );
}

function RaiseModal({ open, onClose, periodId }: { open: boolean; onClose: () => void; periodId: number }) {
  const [query, setQuery] = useState('');
  const [entityId, setEntityId] = useState<number | null>(null);
  const [entityLabel, setEntityLabel] = useState('');
  const [schemeId, setSchemeId] = useState<number | null>(null);
  const [category, setCategory] = useState('');
  const [salesAction, setSalesAction] = useState<KpiExceptionAction>('actual_performance');
  const [executionAction, setExecutionAction] = useState<KpiExceptionAction>('actual_performance');
  const [gatekeeperExempt, setGatekeeperExempt] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [reason, setReason] = useState('');
  const [referenceDate, setReferenceDate] = useState('');

  const { data: matches } = useEntitySearch(query);
  const { data: schemesResp } = useSchemes();
  const { data: schemeDetail } = useScheme(schemeId);
  const { data: catResp } = useExceptionCategories();
  const create = useCreateException();
  const categories = catResp?.results ?? [];

  // Name the invisible classification: which of the scheme's KPIs sit in each bucket.
  const kpiNames = (cat: 'sales' | 'execution') =>
    (schemeDetail?.kpis ?? [])
      .filter((k) => k.incentive_category === cat)
      .map((k) => k.kpi_name)
      .join(', ');
  const salesNames = kpiNames('sales');
  const executionNames = kpiNames('execution');

  const selectedCat = categories.find((c) => c.code === category);
  const needsDate = Boolean(
    selectedCat && (selectedCat.requires_dates || selectedCat.duration_config?.type === 'join_day_cutoff'),
  );
  // Mirror of the backend's effect_months — preview only; the server re-derives it.
  const coveredMonths = (() => {
    const cfg = selectedCat?.duration_config;
    if (!cfg?.type) return 1;
    if (cfg.type === 'fixed') return Math.max(1, cfg.effect_months ?? 1);
    if (!referenceDate) return null; // unknown until the date is set
    const day = Number(referenceDate.slice(8, 10));
    return day <= (cfg.cutoff_day ?? 15)
      ? Math.max(1, cfg.months_on_or_before ?? 2)
      : Math.max(1, cfg.months_after ?? 3);
  })();

  const pickCategory = (code: string) => {
    setCategory(code);
    const cat = categories.find((c) => c.code === code);
    if (cat) {
      setSalesAction(cat.default_sales_kpi_action);
      setExecutionAction(cat.default_execution_kpi_action);
      setGatekeeperExempt(cat.default_gatekeeper_action === 'exempted');
    }
  };

  const reset = () => {
    setQuery(''); setEntityId(null); setEntityLabel(''); setSchemeId(null); setCategory('');
    setSalesAction('actual_performance'); setExecutionAction('actual_performance');
    setGatekeeperExempt(false); setShowAdvanced(false); setReason(''); setReferenceDate('');
  };

  const save = () => {
    if (entityId === null || !reason.trim()) return;
    create.mutate({
      entity: entityId,
      target_period: periodId,
      scheme: schemeId,
      category: category.trim(),
      sales_kpi_action: salesAction,
      execution_kpi_action: executionAction,
      gatekeeper_action: gatekeeperExempt ? 'exempted' : 'no_exemption',
      reason: reason.trim(),
      reference_date: referenceDate || null,
    }, {
      onSuccess: () => { notify.success('Exception raised — pending approval'); reset(); onClose(); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t raise the exception')),
    });
  };

  return (
    <Modal open={open} onClose={() => { reset(); onClose(); }} title="Raise a payout exception" size="lg"
           footer={
             <div className="flex justify-end gap-2">
               <Button variant="outline" onClick={() => { reset(); onClose(); }}>Cancel</Button>
               <Button onClick={save} disabled={entityId === null || !reason.trim()} loading={create.isPending}>
                 Raise exception
               </Button>
             </div>
           }>
      <div className="space-y-4">
        {entityId === null ? (
          <div>
            <Input label="Person" placeholder="Search by name or code…" value={query}
                   onChange={(e) => setQuery(e.target.value)} leftIcon={<Search className="h-4 w-4" />} />
            {query && (matches ?? []).length > 0 && (
              <div className="mt-1 max-h-44 overflow-auto rounded-lg border border-gray-200">
                {(matches ?? []).map((m) => (
                  <button key={m.id} type="button"
                          className="block w-full px-3 py-2 text-left text-sm hover:bg-primary-50"
                          onClick={() => { setEntityId(m.id); setEntityLabel(`${m.name} (${m.code})`); }}>
                    <span className="font-medium text-gray-900">{m.name}</span>{' '}
                    <span className="text-xs text-gray-500">{m.code}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm">
            <span className="font-medium text-gray-900">{entityLabel}</span>
            <Button variant="ghost" size="sm" onClick={() => setEntityId(null)}>Change</Button>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <Select label="Scheme (optional)"
                  value={schemeId ? String(schemeId) : ''}
                  onChange={(e) => setSchemeId(e.target.value ? Number(e.target.value) : null)}
                  options={[{ value: '', label: 'All schemes' },
                            ...(schemesResp?.results ?? []).map((s) => ({ value: String(s.id), label: s.name }))]} />
          <Select label="Category"
                  value={category}
                  onChange={(e) => pickCategory(e.target.value)}
                  options={[{ value: '', label: 'Select a reason…' },
                            ...categories.map((c) => ({ value: c.code, label: c.name }))]} />
        </div>

        {category === '' && !showAdvanced && (
          <p className="text-xs text-gray-500">
            Pick a reason above to apply its standard treatment — or{' '}
            <button type="button" className="font-medium text-primary underline underline-offset-2"
                    onClick={() => setShowAdvanced(true)}>
              set the treatment manually
            </button>.
          </p>
        )}

        {category !== '' && (
          <div className="space-y-1 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
            <p className="text-xs font-medium uppercase tracking-wide text-blue-500">
              What this exception does
            </p>
            <p>
              <strong>Sales KPIs</strong>{salesNames ? ` (${salesNames})` : ''} — {ACTION_PHRASES[salesAction]}.
            </p>
            <p>
              <strong>Execution KPIs</strong>{executionNames ? ` (${executionNames})` : ''} — {ACTION_PHRASES[executionAction]}.
            </p>
            <p>
              <strong>Gate criteria</strong> — {gatekeeperExempt ? 'waived for this person' : 'still apply'}.
            </p>
            {!showAdvanced && (
              <button type="button"
                      className="pt-1 text-xs font-medium text-blue-700 underline underline-offset-2"
                      onClick={() => setShowAdvanced(true)}>
                Adjust manually
              </button>
            )}
          </div>
        )}

        {showAdvanced && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Select label={`Sales KPIs${salesNames ? ` — ${salesNames}` : ''}`} value={salesAction}
                      onChange={(e) => setSalesAction(e.target.value as KpiExceptionAction)}
                      options={ACTION_OPTIONS} />
              <Select label={`Execution KPIs${executionNames ? ` — ${executionNames}` : ''}`} value={executionAction}
                      onChange={(e) => setExecutionAction(e.target.value as KpiExceptionAction)}
                      options={ACTION_OPTIONS} />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" className="h-4 w-4 accent-primary"
                     checked={gatekeeperExempt} onChange={(e) => setGatekeeperExempt(e.target.checked)} />
              Exempt from the gate criteria
            </label>
          </>
        )}

        {needsDate && (
          <div className="w-56">
            <Input label={selectedCat?.duration_config?.type === 'join_day_cutoff' ? 'Joining date' : 'Reference date'}
                   type="date" value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} />
          </div>
        )}

        {coveredMonths !== null && coveredMonths > 1 && (
          <p className="rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-dark">
            Covers this month <strong>+ {coveredMonths - 1} following month{coveredMonths > 2 ? 's' : ''}</strong> —
            on approval, an approved exception is created automatically for each covered month.
          </p>
        )}
        {needsDate && coveredMonths === null && (
          <p className="text-xs text-gray-500">Set the date to see how many months this covers.</p>
        )}

        <Textarea label="Reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="What happened, with dates — approvers and auditors read this" />
      </div>
    </Modal>
  );
}
