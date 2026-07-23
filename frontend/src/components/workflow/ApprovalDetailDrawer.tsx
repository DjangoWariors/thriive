import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Clock, Inbox, X } from 'lucide-react';
import { useWorkflowInstance } from '../../hooks/useWorkflows';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { StatusBadge } from '../ui/StatusBadge';
import { TableSkeleton } from '../ui/Skeleton';
import { ApprovalTimeline } from './ApprovalTimeline';
import { WorkflowStepper } from './WorkflowStepper';
import { formatCurrency, formatDate } from '../../utils/format';
import { apiErrorMessage } from '../../utils/apiError';

interface ApprovalDetailDrawerProps {
  /** Workflow instance to show; null keeps the drawer closed. */
  id: number | null;
  onClose: () => void;
  /** Decision actions, passed only when the viewer may decide. */
  onApprove?: () => void;
  onReject?: () => void;
}

/**
 * Everything behind one row of the approval inbox: what is being asked, by whom, on whose
 * behalf, what it costs, where it sits in the chain and what has already happened to it.
 * The card can only carry a title and a chip; nobody should approve a payout change from that.
 */
export function ApprovalDetailDrawer({ id, onClose, onApprove, onReject }: ApprovalDetailDrawerProps) {
  const { data: inst, isLoading, error } = useWorkflowInstance(id);

  useEffect(() => {
    if (id === null) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [id, onClose]);

  if (id === null) return null;

  const s = inst?.subject_summary;
  const title = (inst?.context_data.title as string) || s?.entity_name || `Request #${id}`;
  const impact = inst?.context_data.impact_amount;
  const open = inst?.status === 'pending' || inst?.status === 'in_review' || inst?.status === 'escalated';

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-xl animate-in slide-in-from-right duration-200"
        role="dialog"
        aria-modal="true"
        aria-label="Approval details"
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <Avatar name={s?.entity_name || title} size="lg" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
              <p className="text-sm text-gray-500">{inst?.definition_name ?? ''}</p>
              {inst && (
                <div className="mt-1 flex items-center gap-1.5">
                  <StatusBadge status={inst.status} />
                  {inst.is_overdue && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-2 py-0.5 text-[10px] font-medium text-danger">
                      <Clock className="h-3 w-3" /> Overdue
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-4 rounded-lg p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <TableSkeleton />
          ) : error || !inst ? (
            <EmptyState icon={Inbox} title="Not available"
                        description={apiErrorMessage(error, 'This request is no longer visible to you.')} />
          ) : (
            <>
              <Section title="Request">
                <Field label="Raised by" value={inst.initiated_by_name ?? 'System'} />
                <Field label="Raised on" value={formatDate(inst.created_at)} />
                <Field label="Waiting at" value={inst.current_step_name} />
                <Field label="Due" value={inst.sla_due_at ? formatDate(inst.sla_due_at) : null} />
                <Field label="Resolved"
                       value={inst.resolved_at ? formatDate(inst.resolved_at) : null} />
              </Section>

              <Section title="Subject">
                <Field label="Person" value={s?.entity_name} />
                <Field label="Code" value={s?.entity_code} />
                <Field label="Scheme" value={s?.scheme_code} />
                {s?.category && (
                  <div className="py-1"><Badge variant="purple">{s.category}</Badge></div>
                )}
                {impact != null && impact !== '' && (
                  <Field label="Estimated impact" value={formatCurrency(impact as string)} />
                )}
                {s?.total_payout != null && (
                  <Field label="Total payout" value={formatCurrency(s.total_payout)} />
                )}
                {s?.entities_processed != null && (
                  <Field label="People affected" value={String(s.entities_processed)} />
                )}
              </Section>

              {s?.reason && (
                <Section title="Reason">
                  <p className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
                    {s.reason}
                  </p>
                </Section>
              )}

              <Section title="Approval chain">
                <div className="rounded-lg border border-gray-100 p-3">
                  <WorkflowStepper steps={inst.steps} />
                </div>
              </Section>

              <Section title="Activity">
                <ApprovalTimeline actions={inst.actions} />
              </Section>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-gray-100 px-6 py-4">
          <Button variant="outline" onClick={onClose}>Close</Button>
          {inst && open && onReject && (
            <Button variant="danger" onClick={onReject}>Reject</Button>
          )}
          {inst && open && onApprove && (
            <Button onClick={onApprove}>Approve</Button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h3>
      {children}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="text-right font-medium text-gray-900">{value || '—'}</span>
    </div>
  );
}
