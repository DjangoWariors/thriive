// Mirrors apps/workflows serializers. IDs are numbers; money/impact are strings.

export type WorkflowStatus =
  | 'pending'
  | 'in_review'
  | 'approved'
  | 'rejected'
  | 'escalated'
  | 'auto_approved'
  | 'cancelled';

export type WorkflowStepStatus =
  | 'pending'
  | 'active'
  | 'approved'
  | 'rejected'
  | 'skipped'
  | 'escalated'
  | 'auto_approved';

export type WorkflowActionType =
  | 'initiate'
  | 'approve'
  | 'reject'
  | 'escalate'
  | 'comment'
  | 'delegate'
  | 'reassign'
  | 'auto_approve';

export interface WorkflowStep {
  id: number;
  order: number;
  name: string;
  approval_mode: 'single' | 'all' | 'any';
  status: WorkflowStepStatus;
  assignee_user: number | null;
  assignee_name: string | null;
  assignee_role_code: string;
  assignee_user_ids: number[];
  sla_due_at: string | null;
  activated_at: string | null;
  resolved_at: string | null;
}

export interface WorkflowAction {
  id: number;
  step: number | null;
  step_order: number;
  action: WorkflowActionType;
  action_by: number | null;
  action_by_name: string | null;
  comments: string;
  created_at: string;
}

export interface WorkflowSubjectSummary {
  kind?: string;
  entity_name?: string;
  entity_code?: string;
  category?: string;
  reason?: string;
  period_id?: number | null;
  scheme_id?: number | null;
  scheme_code?: string;
  total_payout?: string;
  entities_processed?: number;
}

export interface WorkflowInstance {
  id: number;
  definition: number;
  definition_code: string;
  definition_name: string;
  subject_type: string;
  subject_id: number;
  status: WorkflowStatus;
  current_step: number;
  current_step_name: string | null;
  anchor_entity: number | null;
  anchor_entity_name: string | null;
  initiated_by: number | null;
  initiated_by_name: string | null;
  context_data: Record<string, unknown>;
  sla_due_at: string | null;
  is_overdue: boolean;
  resolved_at: string | null;
  created_at: string;
  subject_summary: WorkflowSubjectSummary;
  steps: WorkflowStep[];
  actions: WorkflowAction[];
}

export interface PendingApproval {
  id: number;
  definition_code: string;
  subject_type: string;
  subject_id: number;
  status: WorkflowStatus;
  current_step: number;
  current_step_name: string | null;
  anchor_entity_name: string | null;
  initiated_by_name: string | null;
  context_data: Record<string, unknown> & {
    title?: string;
    impact_amount?: string | null;
    category_code?: string;
  };
  sla_due_at: string | null;
  is_overdue: boolean;
  subject_summary: WorkflowSubjectSummary;
  created_at: string;
}

export interface BulkActionResult {
  processed: number[];
  errors: { id: number; error: string }[];
}

export interface WorkflowDefinitionSummary {
  id: number;
  name: string;
  code: string;
}

export interface ApprovalDelegation {
  id: number;
  delegator: number;
  delegator_name: string | null;
  delegate: number;
  delegate_name: string | null;
  scope: string;
  start_date: string;
  end_date: string;
  reason: string;
  is_active: boolean;
  created_at: string;
}
