import { Check, X, Clock, ChevronUp, Minus } from 'lucide-react';
import { cn } from '../../utils/cn';
import type { WorkflowStep, WorkflowStepStatus } from '../../types/workflow';

const STEP_UI: Record<WorkflowStepStatus, { ring: string; icon: typeof Check }> = {
  approved: { ring: 'bg-success text-white border-success', icon: Check },
  auto_approved: { ring: 'bg-success text-white border-success', icon: Check },
  rejected: { ring: 'bg-danger text-white border-danger', icon: X },
  active: { ring: 'bg-primary text-white border-primary animate-pulse', icon: Clock },
  escalated: { ring: 'bg-warning text-white border-warning', icon: ChevronUp },
  skipped: { ring: 'bg-gray-100 text-gray-400 border-gray-200', icon: Minus },
  pending: { ring: 'bg-white text-gray-400 border-gray-300', icon: Clock },
};

/** Horizontal step indicator: Raised → step names → Resolved. */
export function WorkflowStepper({ steps }: { steps: WorkflowStep[] }) {
  const ordered = [...steps].sort((a, b) => a.order - b.order);
  return (
    <div className="flex items-start overflow-x-auto py-2">
      <Node label="Raised" sublabel="" state="approved" />
      {ordered.map((s) => (
        <Node
          key={s.id}
          label={s.name}
          sublabel={s.assignee_name ?? s.assignee_role_code ?? ''}
          state={s.status}
          connect
        />
      ))}
    </div>
  );
}

function Node({
  label, sublabel, state, connect = false,
}: {
  label: string;
  sublabel: string;
  state: WorkflowStepStatus;
  connect?: boolean;
}) {
  const ui = STEP_UI[state] ?? STEP_UI.pending;
  const Icon = ui.icon;
  return (
    <div className="flex items-start">
      {connect && <div className="mt-3.5 h-0.5 w-8 shrink-0 bg-gray-200" />}
      <div className="flex w-24 shrink-0 flex-col items-center text-center">
        <div className={cn('flex h-8 w-8 items-center justify-center rounded-full border-2', ui.ring)}>
          <Icon className="h-4 w-4" />
        </div>
        <p className="mt-1.5 text-xs font-medium text-gray-700 leading-tight">{label}</p>
        {sublabel && <p className="text-[10px] text-gray-500 leading-tight truncate w-full">{sublabel}</p>}
      </div>
    </div>
  );
}
