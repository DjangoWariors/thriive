import { Check, X, ChevronsUp, MessageSquare, Play, UserCog } from 'lucide-react';
import { cn } from '../../utils/cn';
import { formatRelative } from '../../utils/format';
import type { WorkflowAction, WorkflowActionType } from '../../types/workflow';

const ACTION_UI: Record<WorkflowActionType, { icon: typeof Check; tone: string; verb: string }> = {
  initiate: { icon: Play, tone: 'text-gray-500 bg-gray-100', verb: 'raised the request' },
  approve: { icon: Check, tone: 'text-success bg-success/10', verb: 'approved' },
  auto_approve: { icon: Check, tone: 'text-success bg-success/10', verb: 'auto-approved (SLA)' },
  reject: { icon: X, tone: 'text-danger bg-danger/10', verb: 'rejected' },
  escalate: { icon: ChevronsUp, tone: 'text-warning bg-warning/10', verb: 'escalated (SLA)' },
  comment: { icon: MessageSquare, tone: 'text-gray-500 bg-gray-100', verb: 'commented' },
  delegate: { icon: UserCog, tone: 'text-info bg-info/10', verb: 'delegated' },
  reassign: { icon: UserCog, tone: 'text-info bg-info/10', verb: 'reassigned' },
};

/** Chronological list of every action taken on a workflow — the audit trail. */
export function ApprovalTimeline({ actions }: { actions: WorkflowAction[] }) {
  if (actions.length === 0) {
    return <p className="text-sm text-gray-400">No activity yet.</p>;
  }
  return (
    <ol className="space-y-3">
      {actions.map((a) => {
        const ui = ACTION_UI[a.action] ?? ACTION_UI.comment;
        const Icon = ui.icon;
        return (
          <li key={a.id} className="flex gap-3">
            <div className={cn('mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full', ui.tone)}>
              <Icon className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0">
              <p className="text-sm text-gray-800">
                <span className="font-medium">{a.action_by_name ?? 'System'}</span>{' '}
                <span className="text-gray-500">{ui.verb}</span>
                {a.step_order > 0 && <span className="text-gray-400"> · step {a.step_order}</span>}
              </p>
              {a.comments && <p className="text-xs text-gray-500 italic">“{a.comments}”</p>}
              <p className="text-[11px] text-gray-500">{formatRelative(a.created_at)}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
