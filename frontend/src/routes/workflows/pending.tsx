import { useMemo, useState } from 'react';
import { Inbox, UserCheck } from 'lucide-react';
import { useRBAC } from '../../hooks/useRBAC';
import {
  useApproveStep, useBulkApprove, useBulkReject, useDelegations, usePendingApprovals,
  useRejectStep, useWorkflowInstance,
} from '../../hooks/useWorkflows';
import { useAuthStore } from '../../stores/authStore';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Modal } from '../../components/ui/Modal';
import { Pagination } from '../../components/ui/Pagination';
import { Select } from '../../components/ui/Select';
import { Spinner } from '../../components/ui/Spinner';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Textarea } from '../../components/ui/Textarea';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { StatCard } from '../../components/data/StatCard';
import { ApprovalCard } from '../../components/workflow/ApprovalCard';
import { ApprovalTimeline } from '../../components/workflow/ApprovalTimeline';
import { DelegationsDialog, isActiveNow } from '../../components/workflow/DelegationsDialog';
import { BulkActionBar } from '../../components/workflow/BulkActionBar';
import { WorkflowStepper } from '../../components/workflow/WorkflowStepper';
import { formatCurrency, formatDate } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { PendingApproval } from '../../types/workflow';

export default function WorkflowsPendingPage() {
  const { can } = useRBAC();
  const canDecide = can('workflow_management');

  const [page, setPage] = useState(1);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detailId, setDetailId] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<PendingApproval | null>(null);
  const [approving, setApproving] = useState<PendingApproval | null>(null);
  const [bulkReject, setBulkReject] = useState(false);
  const [reason, setReason] = useState('');
  const [delegationsOpen, setDelegationsOpen] = useState(false);

  const { data: resp, isLoading } = usePendingApprovals({ page });
  const { data: delegationsResp } = useDelegations();
  const me = useAuthStore((s) => s.user);
  const activeCover = (delegationsResp?.results ?? []).filter(isActiveNow);
  const myCover = activeCover.filter((d) => d.delegator === me?.id);
  const coveringFor = activeCover.filter((d) => d.delegate === me?.id && d.delegator !== me?.id);
  const approve = useApproveStep();
  const reject = useRejectStep();
  const bulkApproveM = useBulkApprove();
  const bulkRejectM = useBulkReject();

  const rows = useMemo(() => {
    const all = resp?.results ?? [];
    return overdueOnly ? all.filter((r) => r.is_overdue) : all;
  }, [resp, overdueOnly]);

  const overdueCount = (resp?.results ?? []).filter((r) => r.is_overdue).length;
  const selectedIds = [...selected];

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const doApprove = (item: PendingApproval) =>
    approve.mutate({ id: item.id }, {
      onSuccess: () => { notify.success('Approved'); setApproving(null); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Couldn’t approve')),
    });

  const doReject = () => {
    if (!rejecting || !reason.trim()) return;
    reject.mutate({ id: rejecting.id, reason: reason.trim() }, {
      onSuccess: () => { notify.success('Rejected'); setRejecting(null); setReason(''); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Couldn’t reject')),
    });
  };

  const doBulkApprove = () =>
    bulkApproveM.mutate({ ids: selectedIds }, {
      onSuccess: (r) => {
        notify.success(`Approved ${r.processed.length}${r.errors.length ? `, ${r.errors.length} failed` : ''}`);
        setSelected(new Set());
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Bulk approve failed')),
    });

  const doBulkReject = () => {
    if (!reason.trim()) return;
    bulkRejectM.mutate({ ids: selectedIds, reason: reason.trim() }, {
      onSuccess: (r) => {
        notify.success(`Rejected ${r.processed.length}${r.errors.length ? `, ${r.errors.length} failed` : ''}`);
        setSelected(new Set()); setBulkReject(false); setReason('');
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Bulk reject failed')),
    });
  };

  return (
    <div className="p-6">
      <PageHeader
          title="Approvals"
          description="Requests waiting on your decision — routed to you by the workflow engine. Approve or reject individually, or clear many at once."
          actions={
            <Button variant="secondary" icon={<UserCheck className="h-4 w-4" />}
                    onClick={() => setDelegationsOpen(true)}>
              Out of office
            </Button>
          }
      />

      {myCover.length > 0 && (
        <div className="mb-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-2.5 text-sm text-blue-900">
          {myCover.map((d) => (
            <p key={d.id}>
              <span className="font-medium">{d.delegate_name ?? `User #${d.delegate}`}</span>
              {' '}can act on your approvals until {formatDate(d.end_date)}.{' '}
              <button type="button" className="font-medium underline underline-offset-2"
                      onClick={() => setDelegationsOpen(true)}>
                Manage
              </button>
            </p>
          ))}
        </div>
      )}
      {coveringFor.length > 0 && (
        <div className="mb-3 rounded-lg border border-purple-100 bg-purple-50 px-4 py-2.5 text-sm text-purple-900">
          {coveringFor.map((d) => (
            <p key={d.id}>
              You're covering for{' '}
              <span className="font-medium">{d.delegator_name ?? `User #${d.delegator}`}</span>
              {' '}until {formatDate(d.end_date)} — their pending approvals appear in this list too.
            </p>
          ))}
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatCard label="Awaiting you" value={String(resp?.count ?? 0)} borderColor="amber" />
        <StatCard label="Overdue" value={String(overdueCount)} borderColor="red" />
        <StatCard label="Selected" value={String(selected.size)} borderColor="blue" />
      </div>

      <div className="mb-4 w-56">
        <Select
          value={overdueOnly ? 'overdue' : 'all'}
          onChange={(e) => setOverdueOnly(e.target.value === 'overdue')}
          options={[
            { value: 'all', label: 'All pending' },
            { value: 'overdue', label: 'Overdue only' },
          ]}
        />
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState icon={Inbox} title="Nothing to approve"
                      description="You're all caught up. New requests routed to you will appear here." />
        </Card>
      ) : (
        <>
          <div className="space-y-2">
            {rows.map((item) => (
              <ApprovalCard
                key={item.id}
                item={item}
                selected={selected.has(item.id)}
                canDecide={canDecide}
                onToggleSelect={() => toggle(item.id)}
                onOpen={() => setDetailId(item.id)}
                onApprove={() => setApproving(item)}
                onReject={() => { setReason(''); setRejecting(item); }}
              />
            ))}
          </div>
          <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage} />
        </>
      )}

      <BulkActionBar
        count={selected.size}
        busy={bulkApproveM.isPending}
        onApprove={doBulkApprove}
        onReject={() => { setReason(''); setBulkReject(true); }}
        onClear={() => setSelected(new Set())}
      />

      <DetailDrawer id={detailId} onClose={() => setDetailId(null)} />

      <DelegationsDialog open={delegationsOpen} onClose={() => setDelegationsOpen(false)} />

      <ConfirmDialog
        open={approving !== null}
        onClose={() => setApproving(null)}
        onConfirm={() => approving && doApprove(approving)}
        title="Approve this request?"
        message={approving ? ((approving.context_data.title as string) || `Request #${approving.id}`) : ''}
        confirmLabel="Approve"
      />

      <Modal open={rejecting !== null || bulkReject}
             onClose={() => { setRejecting(null); setBulkReject(false); }}
             title={bulkReject ? `Reject ${selected.size} requests` : 'Reject this request'}
             size="md"
             footer={
               <div className="flex justify-end gap-2">
                 <Button variant="outline" onClick={() => { setRejecting(null); setBulkReject(false); }}>
                   Cancel
                 </Button>
                 <Button variant="danger" disabled={!reason.trim()}
                         loading={reject.isPending || bulkRejectM.isPending}
                         onClick={bulkReject ? doBulkReject : doReject}>
                   Reject
                 </Button>
               </div>
             }>
        <Textarea label="Reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="Approvers and auditors read this" />
      </Modal>
    </div>
  );
}

function DetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: inst, isLoading } = useWorkflowInstance(id);
  return (
    <Modal open={id !== null} onClose={onClose} title="Approval detail" size="lg">
      {isLoading || !inst ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold text-gray-900">
                {(inst.context_data.title as string) || inst.subject_summary.entity_name || `Request #${inst.id}`}
              </p>
              <p className="text-xs text-gray-500">
                {inst.definition_name} · raised by {inst.initiated_by_name ?? 'system'}
              </p>
            </div>
            <StatusBadge status={inst.status} />
          </div>

          {inst.subject_summary.reason && (
            <div className="rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
              {inst.subject_summary.reason}
            </div>
          )}

          {inst.context_data.impact_amount != null && inst.context_data.impact_amount !== '' && (
            <p className="text-sm text-gray-600">
              Estimated impact:{' '}
              <span className="font-semibold text-gray-900">
                {formatCurrency(inst.context_data.impact_amount as string)}
              </span>
            </p>
          )}

          <div className="rounded-lg border border-gray-100 p-3">
            <WorkflowStepper steps={inst.steps} />
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Activity</p>
            <ApprovalTimeline actions={inst.actions} />
          </div>
        </div>
      )}
    </Modal>
  );
}
