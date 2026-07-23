import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, X } from 'lucide-react';
import { useException } from '../../hooks/useIncentives';
import { useWorkflowInstance } from '../../hooks/useWorkflows';
import { useRBAC } from '../../hooks/useRBAC';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { StatusBadge } from '../ui/StatusBadge';
import { TableSkeleton } from '../ui/Skeleton';
import { ApprovalTimeline } from '../workflow/ApprovalTimeline';
import { WorkflowStepper } from '../workflow/WorkflowStepper';
import { ACTION_PHRASES } from '../../utils/exceptionText';
import { formatCurrency, formatDate } from '../../utils/format';
import { apiErrorMessage } from '../../utils/apiError';
import type { PayoutException } from '../../types/incentive';

interface ExceptionDetailDrawerProps {
  /** The exception to show; null keeps the drawer closed. */
  id: number | null;
  onClose: () => void;
  /** Decision actions, passed only when the viewer may take them. */
  onApprove?: (e: PayoutException) => void;
  onReject?: (e: PayoutException) => void;
  onWithdraw?: (e: PayoutException) => void;
}

/**
 * The whole story of one exception: what it changes about the computation, why it was
 * raised, how many months it covers, and where its approval stands. The list row can only
 * show a truncated reason and a status chip — an approver deciding on someone's pay needs
 * the rest before they click Approve.
 */
export function ExceptionDetailDrawer({
  id, onClose, onApprove, onReject, onWithdraw,
}: ExceptionDetailDrawerProps) {
  const { can } = useRBAC();
  const { data: exc, isLoading, error } = useException(id);

  // The approval trail lives on the workflow instance, which is a different permission.
  // Without it the rest of the drawer still stands; we just omit the trail.
  const workflowId = can('workflow_management') ? exc?.workflow_id ?? null : null;
  const { data: instance } = useWorkflowInstance(workflowId);

  useEffect(() => {
    if (id === null) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [id, onClose]);

  if (id === null) return null;

  const pending = exc?.status === 'pending';

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-xl animate-in slide-in-from-right duration-200"
        role="dialog"
        aria-modal="true"
        aria-label="Exception details"
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <Avatar name={exc?.entity_name || 'Exception'} size="lg" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{exc?.entity_name ?? 'Exception'}</h2>
              <p className="text-sm text-gray-500">
                {exc ? `${exc.entity_code} · ${exc.period_code}` : `#${id}`}
              </p>
              {exc && (
                <div className="mt-1 flex items-center gap-1.5">
                  <StatusBadge status={exc.status} />
                  {exc.parent !== null && (
                    <Badge variant="default">auto</Badge>
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
          ) : error || !exc ? (
            <EmptyState icon={AlertTriangle} title="Not available"
                        description={apiErrorMessage(error, 'This exception is outside your area.')} />
          ) : (
            <>
              <div className="space-y-1 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
                <p className="text-xs font-medium uppercase tracking-wide text-blue-500">
                  What this exception does
                </p>
                <p><strong>Sales KPIs</strong> — {ACTION_PHRASES[exc.sales_kpi_action]}.</p>
                <p><strong>Execution KPIs</strong> — {ACTION_PHRASES[exc.execution_kpi_action]}.</p>
                <p>
                  <strong>Gate criteria</strong> —{' '}
                  {exc.gatekeeper_action === 'exempted' ? 'waived for this person' : 'still apply'}.
                </p>
              </div>

              <Section title="Request">
                <Field label="Category" value={exc.category_name || exc.category} />
                <Field label="Scheme" value={exc.scheme_code ?? 'All schemes'} />
                <Field label="Period" value={exc.period_code} />
                {/* Only date-keyed categories (new joiner, transfer…) carry one — for the rest
                    the row would be a permanent dash. Same for the workflow-supplied impact. */}
                {exc.reference_date && (
                  <Field label="Reference date" value={formatDate(exc.reference_date)} />
                )}
                <Field label="Raised by" value={exc.requested_by_name || 'System'} />
                <Field label="Raised on" value={formatDate(exc.created_at)} />
                {/* Absent for readers without payout access — the drawer simply omits it
                    rather than announcing that a figure is being withheld. */}
                {exc.impact_amount != null && exc.impact_amount !== '' && (
                  <Field label="Variable pay at stake" value={formatCurrency(exc.impact_amount)} />
                )}
              </Section>

              <Section title="Reason">
                <p className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
                  {exc.reason || '—'}
                </p>
              </Section>

              {(exc.parent !== null || exc.children_count > 0) && (
                <Section title="Coverage">
                  {exc.parent !== null ? (
                    <p className="text-sm text-gray-600">
                      Auto-created for a later month by exception #{exc.parent}. Approving or
                      rejecting the original governs this one.
                    </p>
                  ) : (
                    <p className="text-sm text-gray-600">
                      Covers this month <strong>+ {exc.children_count} following month
                      {exc.children_count > 1 ? 's' : ''}</strong> — one approved exception was
                      created automatically for each.
                    </p>
                  )}
                </Section>
              )}

              {exc.status !== 'pending' && (
                <Section title="Decision">
                  <Field label={exc.status === 'approved' ? 'Approved by' : 'Rejected by'}
                         value={exc.approved_by_name} />
                  <Field label="Decided on"
                         value={exc.approved_at ? formatDate(exc.approved_at) : null} />
                  {exc.rejection_reason && (
                    <p className="mt-2 rounded-lg border border-danger-100 bg-danger-50 p-3 text-sm text-danger">
                      {exc.rejection_reason}
                    </p>
                  )}
                </Section>
              )}

              {instance && (
                <Section title="Approval trail">
                  <div className="mb-4 rounded-lg border border-gray-100 p-3">
                    <WorkflowStepper steps={instance.steps} />
                  </div>
                  <ApprovalTimeline actions={instance.actions} />
                </Section>
              )}
              {!instance && exc.status === 'pending' && exc.current_step_name && (
                <Section title="Approval">
                  <p className="text-sm text-gray-600">Waiting at {exc.current_step_name}.</p>
                </Section>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-gray-100 px-6 py-4">
          <Button variant="outline" onClick={onClose}>Close</Button>
          {exc && pending && onWithdraw && (
            <Button variant="ghost" onClick={() => onWithdraw(exc)}>Withdraw</Button>
          )}
          {exc && pending && onReject && (
            <Button variant="danger" onClick={() => onReject(exc)}>Reject</Button>
          )}
          {exc && pending && onApprove && (
            <Button onClick={() => onApprove(exc)}>Approve</Button>
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
